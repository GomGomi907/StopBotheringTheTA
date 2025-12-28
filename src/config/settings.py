import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()


def _default_semester() -> str:
    """현재 날짜 기준 학기 추정 (기본값)"""
    now = datetime.now()
    year = now.year
    month = now.month
    if 3 <= month <= 6:
        return f"{year}-1"  # 1학기
    elif 7 <= month <= 8:
        return f"{year}-summer"  # 여름 계절
    elif 9 <= month <= 12:
        return f"{year}-2"  # 2학기
    else:  # 1~2월
        return f"{year}-winter"  # 겨울 계절


@dataclass
class Settings:
    """환경 변수 기반 런타임 설정."""

    canvas_base_url: Optional[str] = os.getenv("CANVAS_BASE_URL")
    canvas_token: Optional[str] = os.getenv("CANVAS_TOKEN")
    canvas_session: Optional[str] = os.getenv("CANVAS_SESSION")
    notices_base_url: Optional[str] = os.getenv("NOTICES_BASE_URL")
    
    # 기본 데이터 경로
    data_base_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    files_dir: Path = Path(os.getenv("FILES_DIR", "data/files"))
    
    # 학기 설정
    current_semester: str = os.getenv("CURRENT_SEMESTER", _default_semester())
    
    user_agent: str = os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    timeout: float = float(os.getenv("HTTP_TIMEOUT", "15"))
    max_retries: int = int(os.getenv("HTTP_MAX_RETRIES", "3"))

    @property
    def raw_records_dir(self) -> Path:
        """학기별 raw 데이터 경로"""
        return self.data_base_dir / "semesters" / self.current_semester / "raw"
    
    @property
    def structured_db_path(self) -> Path:
        """학기별 정형화된 DB 경로"""
        return self.data_base_dir / "semesters" / self.current_semester / "structured_db.json"
    
    @property
    def semester_dir(self) -> Path:
        """현재 학기 데이터 디렉토리"""
        return self.data_base_dir / "semesters" / self.current_semester

    @classmethod
    def from_env(cls) -> "Settings":
        """dotenv -> 환경 변수 값을 로드."""
        return cls()
    
    def with_semester(self, semester: str) -> "Settings":
        """특정 학기로 설정을 복사하여 반환"""
        import copy
        new_settings = copy.copy(self)
        new_settings.current_semester = semester
        return new_settings

