from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import hashlib


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_id(parts: List[str]) -> str:
    """여러 문자열을 합쳐 안정적인 해시 ID 생성."""
    joined = "|".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


@dataclass
class Record:
    """LLM 정제용 공통 레코드."""

    source: str  # 예: portal/canvas
    category: str  # 예: notice/assignment/module/file/listing
    tags: List[str] = field(default_factory=list)
    url: Optional[str] = None
    title: Optional[str] = None
    created_at: Optional[str] = None  # 원본 생성 시각
    updated_at: Optional[str] = None  # 원본 수정 시각
    payload: Any = None  # HTML/JSON 등 원본 데이터
    id: Optional[str] = None
    fetched_at: str = field(default_factory=now_iso)
    semester: Optional[str] = None  # 학기 식별자 (예: 2025-2)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

