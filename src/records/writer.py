from pathlib import Path
import json
from typing import Iterable, Optional

from src.records.models import Record


class RecordWriter:
    """JSONL로 레코드 적재. 학기별 디렉토리 지원."""

    def __init__(
        self, 
        base_path: Path = Path("data/raw"),
        semester: Optional[str] = None
    ) -> None:
        self.base_path = base_path
        self.semester = semester
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.out_path = self.base_path / "records.jsonl"

    def append(self, record: Record) -> None:
        # 학기 정보 주입 (record에 없으면)
        if self.semester and not record.semester:
            record.semester = self.semester
        
        with self.out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def append_many(self, records: Iterable[Record]) -> None:
        with self.out_path.open("a", encoding="utf-8") as f:
            for rec in records:
                # 학기 정보 주입
                if self.semester and not rec.semester:
                    rec.semester = self.semester
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")

