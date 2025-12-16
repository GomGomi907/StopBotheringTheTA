from pathlib import Path
import json
from typing import Iterable, Optional

from src.records.models import Record


class RecordWriter:
    """JSONL로 레코드 적재."""

    def __init__(self, base_path: Path = Path("data/raw")) -> None:
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.out_path = self.base_path / "records.jsonl"

    def append(self, record: Record) -> None:
        with self.out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def append_many(self, records: Iterable[Record]) -> None:
        with self.out_path.open("a", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
