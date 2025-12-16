import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    """환경 변수 기반 런타임 설정."""

    canvas_base_url: Optional[str] = os.getenv("CANVAS_BASE_URL")
    canvas_token: Optional[str] = os.getenv("CANVAS_TOKEN")
    canvas_session: Optional[str] = os.getenv("CANVAS_SESSION")
    notices_base_url: Optional[str] = os.getenv("NOTICES_BASE_URL")
    raw_records_dir: Path = Path(os.getenv("RAW_RECORDS_DIR", "data/raw"))
    files_dir: Path = Path(os.getenv("FILES_DIR", "data/files"))
    user_agent: str = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))
    max_retries: int = int(os.getenv("HTTP_MAX_RETRIES", "3"))

    @classmethod
    def from_env(cls) -> "Settings":
        """dotenv -> 환경 변수 값을 로드."""
        return cls()
