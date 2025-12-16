import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from bs4 import BeautifulSoup
import re

from src.config.settings import Settings
from src.core.cookies import load_cookies
from src.core.http import HttpClient
from src.records.models import Record, make_id
from src.records.writer import RecordWriter

logger = logging.getLogger(__name__)


@dataclass
class BoardConfig:
    name: str
    url: str
    category: str = "notice"
    tags: Optional[List[str]] = None


def load_board_configs(path: Path, base_url: Optional[str] = None) -> List[BoardConfig]:
    """JSON 파일에서 게시판 설정을 로드한다."""
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    boards: List[BoardConfig] = []
    for item in raw:
        url = item["url"]
        if base_url and url.startswith("/"):
            url = base_url.rstrip("/") + url
        boards.append(
            BoardConfig(
                name=item.get("name", url),
                url=url,
                category=item.get("category", "notice"),
                tags=item.get("tags", []),
            )
        )
    return boards


class NoticesCrawler:
    """포털/학과 공지 크롤러 (HTML 원문 적재)."""

    def __init__(
        self,
        settings: Settings,
        writer: RecordWriter,
        cookies_path: Path = Path("data/cookies_portal.json"),
    ) -> None:
        self.settings = settings
        self.writer = writer
        self.cookies_path = cookies_path

    def _client(self) -> HttpClient:
        cookies = load_cookies(self.cookies_path)
        return HttpClient(
            headers={"User-Agent": self.settings.user_agent},
            cookies=cookies,
            timeout=self.settings.timeout,
            max_retries=self.settings.max_retries,
        )

    def crawl(self, boards: List[BoardConfig], max_pages: int = 1) -> None:
        client = self._client()
        for board in boards:
            logger.info("크롤링 시작: %s", board.name)
            # 페이지네이션 규칙을 알 수 없으므로 기본 URL만 수집. max_pages는 URL에 {page}가 있을 때만 적용.
            urls = []
            if "{page}" in board.url:
                urls = [board.url.format(page=p) for p in range(1, max_pages + 1)]
            else:
                urls = [board.url]

            for u in urls:
                try:
                    resp = client.get(u)
                except Exception as e:
                    logger.error("요청 실패: %s (%s)", u, e)
                    continue
                rec = Record(
                    id=make_id([board.name, u]),
                    source="portal",
                    category=board.category,
                    tags=board.tags or [],
                    url=u,
                    title=board.name,
                    payload={
                        "html": resp.text,
                        "status": resp.status_code,
                        "headers": dict(resp.headers),
                    },
                )
                self.writer.append(rec)
                logger.info("저장 완료: %s", u)

                # [Deep Crawling] 상세 페이지 심층 수집
                try:
                    detail_urls = self._extract_detail_links(resp.text, u)
                    logger.info(f"  [Deep] 상세 URL {len(detail_urls)}개 발견 (Base: {u})")
                    for d_url in detail_urls:
                        self._fetch_detail_page(client, d_url, board)
                except Exception as e:
                    logger.warning(f"  [Deep] 상세 페이지 수집 엔트리 에러: {e}")

    def _extract_detail_links(self, html: str, base_url: str) -> List[str]:
        """목록 페이지에서 상세 게시글 URL을 추출 (Heuristic)"""
        soup = BeautifulSoup(html, "html.parser")
        links = set()
        
        # Base Host 추출 (ex: https://portal.dankook.ac.kr)
        if base_url.startswith("http"):
            host_parts = base_url.split("/")
            host = f"{host_parts[0]}//{host_parts[2]}"
        else:
            host = ""

        for a in soup.find_all("a", href=True):
            href = a["href"]
            href_lower = href.lower()
            
            # Heuristic: 상세 페이지 패턴
            # 1. 'view', 'read' 키워드
            # 2. articleNo, seq, id 등 식별자 파라미터
            is_detail = False
            if any(k in href_lower for k in ["view", "read", "detail"]):
                is_detail = True
            if any(k in href_lower for k in ["articleno=", "seq=", "id=", "no=", "board_no="]):
                is_detail = True
            
            # Filter out common non-content links
            if any(k in href_lower for k in ["login", "logout", "admin", "delete", "modify", "write", "javascript", "#"]):
                is_detail = False

            if is_detail:
                full_url = href
                if href.startswith("/"):
                    full_url = f"{host}{href}"
                elif not href.startswith("http"):
                    # 상대 경로 (query string only or relative path)
                     # 단순히 base_url + href 하기엔 위험하므로 host 기준 처리 권장
                     # 혹은 쿼리스트링(?seq=...)인 경우
                     if href.startswith("?"):
                         # base_url에서 쿼리만 교체해야 함. 복잡성 회피 위해 ? 시작은 일단 base_url + href
                         full_url = f"{base_url}{href}" # rough approximation
                     else:
                         # folder relative?
                         pass 
                
                if full_url.startswith("http"):
                    links.add(full_url)
        
        return list(links)

    def _fetch_detail_page(self, client: HttpClient, url: str, board: BoardConfig) -> None:
        """상세 페이지 진입하여 본문 및 첨부파일 정보 수집"""
        try:
            resp = client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # 본문 텍스트 추출 (Main Content Area 감지 어렵으므로 전체 텍스트)
            # 불필요한 공백 제거
            text_content = re.sub(r'\s+', ' ', soup.get_text()).strip()
            
            # 첨부파일 링크 탐지
            files = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # 파일 확장자 기반 감지
                if any(href.lower().endswith(ext) for ext in [".pdf", ".hwp", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".jpg", ".png"]):
                     files.append({
                         "name": a.get_text(strip=True),
                         "url": href
                     })

            self.writer.append(Record(
                id=make_id([board.name, url, "detail"]),
                source="portal",
                category="notice_detail",
                tags=board.tags + ["detail"],
                url=url,
                title=f"{board.name} (상세)", # 실제 제목 파싱은 selector 필요하므로 생략
                payload={
                    "content": text_content, # RAG용 텍스트
                    "html": resp.text,       # 원본 보존
                    "files": files,
                    "parent_url": board.url
                }
            ))
            logger.info(f"    -> [Deep] 상세 수집 완료 ({len(files)} files)")
            
        except Exception as e:
            logger.debug(f"    -> [Deep] 상세 수집 스킵/실패: {e}")
