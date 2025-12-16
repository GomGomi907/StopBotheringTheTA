import json
import logging
import os
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re
from playwright.async_api import async_playwright

from src.config.settings import Settings
from src.core.cookies import load_cookies
from src.core.http import HttpClient
from src.records.models import Record, make_id
from src.records.writer import RecordWriter

logger = logging.getLogger(__name__)


class CanvasCrawler:
    """캔버스 LMS의 5대 핵심 탭(강의계획서, 공지, 주차학습, 게시판, 자료실) 구조를 반영한 크롤러."""

    def __init__(
        self,
        settings: Settings,
        writer: RecordWriter,
        cookies_path: Path = Path("data/cookies_canvas.json"),
        download_files: bool = False,
    ) -> None:
        self.settings = settings
        self.writer = writer
        self.cookies_path = cookies_path
        self.download_files = download_files
        self.base_url = settings.canvas_base_url or "https://canvas.dankook.ac.kr"

    def _client(self) -> HttpClient:
        cookies = load_cookies(self.cookies_path)
        headers = {"User-Agent": self.settings.user_agent}
        csrf = cookies.get("_csrf_token") or cookies.get("csrf_token")
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if self.settings.canvas_token:
            logger.warning("환경변수/설정에 CANVAS_TOKEN이 감지되었습니다. 쿠키보다 우선 사용됩니다.")
            headers["Authorization"] = f"Bearer {self.settings.canvas_token}"
        return HttpClient(
            base_url=self.base_url,
            headers=headers,
            cookies=cookies,
            timeout=self.settings.timeout,
            max_retries=self.settings.max_retries,
        )

    def crawl(self, course_ids: Optional[List[str]] = None) -> List[Dict]:
        """크롤링 진입점: 코스 목록 조회 후 각 코스별 구조적 수집 수행"""
        client = self._client()
        courses = self._fetch_courses(client)
        
        # 필터링
        if course_ids:
            course_ids_set = set(str(x) for x in course_ids)
            courses = [c for c in courses if str(c.get("id")) in course_ids_set]
            
        logger.info(f"총 {len(courses)}개 과목에 대해 구조적 크롤링을 시작합니다.")

        for course in courses:
            try:
                self._crawl_course_structure(client, course)
            except Exception as e:
                logger.error(f"코스 처리 중 치명적 오류 ({course.get('name')}): {e}")
                
        return courses

    def _crawl_course_structure(self, client: HttpClient, course: Dict) -> None:
        """한 과목의 5대 탭(계획서, 공지, 모듈, 게시판, 자료실)을 순회하며 수집"""
        cid = course.get("id")
        name = course.get("name")
        code = course.get("course_code") or str(cid)
        tags = ["canvas", str(cid)]
        
        logger.info(f"\n[{name}] 데이터 수집 시작 (ID: {cid})")
        
        # 0. 코스 기본 정보 저장
        self.writer.append(Record(
            id=make_id(["canvas", "course", str(cid)]),
            source="canvas",
            category="course",
            tags=tags,
            url=f"{self.base_url}/courses/{cid}",
            title=name,
            payload=course
        ))

        # 1. 강의계획서 (Syllabus)
        self._fetch_syllabus(client, cid, tags)
        
        # 2. 공지사항 (Announcements)
        self._fetch_announcements(client, cid, tags)
        
        # 3. 주차학습 (Modules) - 핵심: 주차별 구조화 & 파일/영상 링크
        self._fetch_modules(client, cid, tags)
        
        # 4. 게시판 (Discussions) - Q&A 등
        self._fetch_discussions(client, cid, tags)

        # 5. 외부 도구 탭 (Generic LTI Tabs) - 강의자료실 등이 탭으로 존재할 경우
        self._fetch_external_tool_tabs(client, cid, tags)
        
        # 6. 강의자료실 (Files) - 폴더 구조 파일
        # 사용자가 다운로드 옵션을 켰거나, 혹은 메타데이터라도 수집
        if self.download_files:
            self._fetch_files(client, cid, tags)
        else:
            logger.info("파일 다운로드 옵션이 꺼져있어 '강의자료실' 상세 스캔은 건너뜁니다.")

    # --- 개별 탭 수집 메서드 ---

    def _fetch_syllabus(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 1: 강의계획서"""
        url = f"/api/v1/courses/{cid}"
        params = {"include[]": "syllabus_body"}
        try:
            resp = client.get(url, params=params)
            data = self._decode_json(resp)
            
            body = data.get("syllabus_body", "")
            if body:
                self.writer.append(Record(
                    id=make_id([f"syllabus-{cid}"]),
                    source="canvas",
                    category="syllabus",
                    tags=tags,
                    url=url,
                    title="강의계획서",
                    payload={"body": body, "raw": data}
                ))
                logger.info("  [V] 강의계획서 수집 완료")
            else:
                logger.info("  [ ] 강의계획서 내용 없음")
        except Exception as e:
            logger.error(f"  [X] 강의계획서 실패: {e}")

    def _fetch_announcements(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 2: 공지사항"""
        url = f"/api/v1/courses/{cid}/discussion_topics"
        # [Robust ETL] 모든 디스커션 토픽을 가져오되, 여기서는 공지사항으로 분류된 것만 태깅
        # API 특성상 only_announcements=true를 쓰면 공지사항만 옴.
        params = {"only_announcements": "true", "per_page": 50}
        
        items = self._fetch_list(client, url, params)
        if items:
            for item in items:
                self.writer.append(Record(
                    id=make_id([str(item.get("id")), "announcement"]),
                    source="canvas",
                    category="announcement",
                    tags=tags,
                    url=item.get("html_url") or url,
                    title=item.get("title"),
                    payload=item # Full JSON Payload (Body 포함)
                ))
            logger.info(f"  [V] 공지사항 {len(items)}개 수집 (Full Context)")
        else:
            logger.info("  [ ] 공지사항 없음")

    def _fetch_modules(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 3: 주차학습 (Modules) - 구조적 저장"""
        url = f"/api/v1/courses/{cid}/modules"
        # items, content_details 포함하여 상세 정보 획득
        params = {"include[]": ["items", "content_details"], "per_page": 50}
        
        modules = self._fetch_list(client, url, params)
        if not modules:
            logger.info("  [ ] 주차학습(모듈) 없음")
            return

        count_items = 0
        for mod in modules:
            # 모듈(주차) 단위로 레코드 생성
            mod_name = mod.get("name")
            mod_id = mod.get("id")
            mod_items = mod.get("items", [])
            count_items += len(mod_items)
            
            # 모듈 자체 레코드
            self.writer.append(Record(
                id=make_id([str(mod_id), "module"]),
                source="canvas",
                category="week_module",
                tags=tags,
                url=mod.get("items_url") or url,
                title=mod_name,
                payload=mod
            ))
            
            # [Robust ETL] 모듈 아이템들도 개별 레코드로 저장 (파일 매핑을 위해 중요)
            for item in mod_items:
                # 아이템에 모듈 컨텍스트 주입
                item["_context_module_id"] = mod_id
                item["_context_module_name"] = mod_name
                
                # [Deep Crawling] Page 타입 본문 수집
                if item.get("type") == "Page" and item.get("url"):
                    body = self._fetch_page_content(client, item.get("url"))
                    if body:
                        item["body"] = body # Payload에 본문 추가
                        logger.info(f"  [Deep] 페이지 본문 확보: {item.get('title')}")

                self.writer.append(Record(
                    id=make_id([str(item.get("id")), "module_item"]),
                    source="canvas",
                    category="module_item", # 나중에 ETL에서 type별로 분류
                    tags=tags,
                    url=item.get("html_url") or url,
                    title=item.get("title"),
                    payload=item
                ))
            
        logger.info(f"  [V] 주차학습 수집: {len(modules)}주차, 총 {count_items}개 아이템 (개별 저장 완료)")

    def _fetch_discussions(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 4: 게시판 (Q&A 등)"""
        url = f"/api/v1/courses/{cid}/discussion_topics"
        # [Robust ETL] 모든 토픽 수집 (공지사항 포함일 수 있음 -> ETL에서 중복 제거/병합)
        params = {"per_page": 50}
        
        items = self._fetch_list(client, url, params)
        if items:
            for item in items:
                # [Robust ETL] 필터링 제거. 모든 것을 저장한다.
                # 단, 공지사항 API에서 가져온 것과 ID가 겹칠 수 있으므로 ID 생성 규칙 주의
                # 여기서는 "discussion" suffixes를 붙임. 나중에 Original ID로 병합.
                
                self.writer.append(Record(
                    id=make_id([str(item.get("id")), "discussion"]),
                    source="canvas",
                    category="discussion_raw", # Raw Discussion
                    tags=tags,
                    url=item.get("html_url") or url,
                    title=item.get("title"),
                    payload=item
                ))
            logger.info(f"  [V] 게시판/토론 {len(items)}개 수집 (No Filter)")

    def _fetch_external_tool_tabs(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 5: 외부 도구 탭 (External Tools)"""
        url = f"/api/v1/courses/{cid}/tabs"
        params = {"per_page": 50}
        
        tabs = self._fetch_list(client, url, params)
        if not tabs: return
        
        count = 0
        for tab in tabs:
            # Skip standard tabs
            if tab.get("id") in ["home", "announcements", "assignments", "modules", "files", "grades", "people", "pages", "discussions", "quizzes", "syllabus", "outcomes", "conferences", "collaborations", "settings"]:
                continue
            
            # 외부 도구(external) 타입이거나 url에 external_tools가 포함된 경우
            is_external = (tab.get("type") == "external") or ("external_tools" in str(tab.get("html_url")))
            
            if is_external:
                self.writer.append(Record(
                    id=make_id([tab.get("html_url"), "tab_lti"]),
                    source="canvas",
                    category="external_tool_tab", # LTI 다운로더가 식별할 키
                    tags=tags,
                    url=tab.get("html_url"),
                    title=f"{tab.get('label')} (Tab)",
                    payload=tab
                ))
                count += 1
                
        if count > 0:
            logger.info(f"  [V] 외부 도구 탭 {count}개 발견")
            
    def _fetch_files(self, client: HttpClient, cid: int, tags: List[str]) -> None:
        """탭 5: 강의자료실 (Files)"""
        url = f"/api/v1/courses/{cid}/files"
        params = {"per_page": 100} # 파일 메타데이터 조회
        
        # 파일은 폴더 구조가 중요할 수 있으나, API는 플랫하게 줄 수도 있음.
        # 일단 전체 파일 목록을 가져와서 개별 레코드로 저장
        try:
            files = self._fetch_list(client, url, params)
            if files:
                for f in files:
                    self.writer.append(Record(
                        id=make_id([str(f.get("id")), "file_meta"]),
                        source="canvas",
                        category="file_meta",
                        tags=tags,
                        url=f.get("url"), # 다운로드 API URL
                        title=f.get("display_name"),
                        payload=f
                    ))
                logger.info(f"  [V] 강의자료실 파일 {len(files)}개 메타 수집")
            else:
                try: 
                    # 404/401 체크 (권한 없음 등)
                     logger.debug("  [ ] 강의자료실 접근 불가 또는 비어있음")
                except: pass
        except Exception as e:
            # 404 등은 조용히 넘어감 (선택 탭)
            if "404" not in str(e) and "401" not in str(e):
                logger.warning(f"  [!] 강의자료실 수집 중 에러: {e}")

    def _fetch_page_content(self, client: HttpClient, api_url: str) -> Optional[str]:
        """[Deep Crawling] Page 아이템의 API URL을 통해 본문 HTML을 가져옵니다."""
        try:
            # api_url 예: .../api/v1/courses/123/pages/my-page-url
            resp = client.get(api_url)
            data = self._decode_json(resp)
            return data.get("body")
        except Exception as e:
            logger.warning(f"  [!] 페이지 본문 조회 실패 ({api_url}): {e}")
            return None

    # --- Helpers ---

    def _fetch_list(self, client: HttpClient, url: str, params: Dict = None) -> List[Dict]:
        """페이지네이션 처리된 리스트 조회 헬퍼"""
        results = []
        try:
            for resp in client.iter_paginated(url, params=params):
                data = self._decode_json(resp)
                if isinstance(data, list):
                    results.extend(data)
                elif isinstance(data, dict) and "id" in data: # 단일 객체 리턴 방어
                    results.append(data)
        except Exception as e:
             # 특정 탭이 없을 때 404가 뜰 수 있음 -> 빈 리스트 반환
             if "404" in str(e) or "401" in str(e):
                 return []
             logger.warning(f"API 요청 실패 ({url}): {e}")
        return results

    def _fetch_courses(self, client: HttpClient) -> List[Dict]:
        """활성 코스 목록 조회"""
        try:
            resp = client.get("/api/v1/courses", params={"enrollment_state": "active", "per_page": 50})
            data = self._decode_json(resp)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"코스 목록 조회 실패: {e}")
            return []

    @staticmethod
    def _decode_json(resp) -> any:
        text = resp.text.lstrip()
        if text.startswith("while(1);"):
            text = text[9:]
        return json.loads(text)
