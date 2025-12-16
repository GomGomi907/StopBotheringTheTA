import logging
import time
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urljoin

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class HttpClient:
    """공통 HTTP 클라이언트. 재시도/타임아웃/헤더 설정 포함."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        cookies: Optional[Dict[str, str]] = None,
        timeout: float = 15,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.client = httpx.Client(
            headers=headers,
            cookies=cookies,
            timeout=timeout,
            follow_redirects=True,
        )
        self.max_retries = max_retries

    def _full_url(self, url: str) -> str:
        if self.base_url and not url.startswith("http"):
            return urljoin(f"{self.base_url}/", url.lstrip("/"))
        return url

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        target = self._full_url(url)
        logger.debug("GET %s %s", target, kwargs.get("params"))
        resp = self.client.get(target, **kwargs)
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = self.get(url, **kwargs)
        return resp.json()

    def iter_paginated(self, url: str, params: Optional[Dict[str, Any]] = None) -> Iterable[httpx.Response]:
        """Canvas 스타일 Link 헤더 기반 페이지네이션."""
        target = self._full_url(url)
        next_url = target
        q = params or {}
        while next_url:
            resp = self.client.get(next_url, params=q)
            resp.raise_for_status()
            yield resp
            next_url = self._parse_next_link(resp.headers.get("Link"))
            q = None  # 이후 요청은 Link에 포함된 URL 사용

    @staticmethod
    def _parse_next_link(link_header: Optional[str]) -> Optional[str]:
        if not link_header:
            return None
        parts = link_header.split(",")
        for part in parts:
            section = part.split(";")
            if len(section) < 2:
                continue
            url_part = section[0].strip(" <>")
            rel = section[1].strip()
            if rel == 'rel="next"':
                return url_part
        return None

    def download_to_file(self, url: str, dest_path: str, chunk_size: int = 1024 * 32) -> None:
        """단순 파일 다운로드."""
        target = self._full_url(url)
        with self.client.stream("GET", target) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
        time.sleep(0.1)
