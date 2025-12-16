import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict
import asyncio

from src.config.settings import Settings
from src.llm.client import LLMClient
from src.processing.metadata import MetadataExtractor

logger = logging.getLogger(__name__)

class DataRefiner:
    def __init__(self):
        self.settings = Settings.from_env()
        self.client = LLMClient()
        self.extractor = MetadataExtractor()
        self.kb_path = Path("data/knowledge_base.json")
        
    def load_raw_data(self) -> Dict[str, List[Dict]]:
        """record.jsonl에서 데이터를 로드하고 과목별로 그룹화"""
        records_path = self.settings.raw_records_dir / "records.jsonl"
        if not records_path.exists():
            return {}

        grouped_data = defaultdict(list)
        
        with open(records_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    # 메타데이터 추출 (Title, Date, URL 등 1차 가공)
                    meta = self.extractor.summarize_record(rec)
                    
                    # 과목 ID/이름 매핑
                    payload = rec.get("payload", {})
                    cid = "common"
                    cname = "일반 공지"
                    
                    if isinstance(payload, dict):
                        cid = str(payload.get("course_id", "common"))
                    
                    # 태그 기반 폴백
                    tags = rec.get("tags", [])
                    if cid == "common" and len(tags) > 1:
                        cid = tags[1]
                        
                    # 과목명 (rec.title은 페이지 타이틀일 수 있으므로 주의)
                    if rec.get("category") == "course":
                        # 코스 정보 레코드에서 과목명 추출
                        pass 
                    
                    # 메타데이터에 원본 ID 주입 (중복 방지용)
                    meta["original_id"] = f"{cid}_{meta['url']}"
                    meta["course_id"] = cid
                    # meta["course_name"]은 나중에 매핑
                    
                    grouped_data[cid].append(meta)
                except Exception:
                    continue
                    
        return grouped_data

    def run_refinement(self, course_names: Dict[str, str]):
        """ETL 실행: Raw Data -> LLM Refinement -> Knowledge Base"""
        raw_grouped = self.load_raw_data()
        knowledge_base = []
        
        total_courses = len(raw_grouped)
        print(f"🚀 [Refiner] {total_courses}개 과목 데이터 정제 시작...")

        for cid, items in raw_grouped.items():
            c_name = course_names.get(str(cid), f"Course {cid}")
            if c_name == "common": c_name = "일반 공지"
            
            print(f"  - Processing {c_name} ({len(items)} items)...")
            
            # Chunking (LLM Context Limit 고려, 10개씩)
            chunk_size = 10
            for i in range(0, len(items), chunk_size):
                chunk = items[i:i+chunk_size]
                
                # LLM 호출
                refined_chunk = self.client.refine_chunk(c_name, chunk)
                
                # 결과 병합
                for item in refined_chunk:
                    item["course_name"] = c_name
                    item["course_id"] = cid
                    knowledge_base.append(item)
                    
        # 저장
        with open(self.kb_path, "w", encoding="utf-8") as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)
            
        print(f"✅ [Refiner] 정제 완료! {len(knowledge_base)}개 항목 저장됨: {self.kb_path}")
        return knowledge_base

if __name__ == "__main__":
    # Test Runner
    # (실제 실행 시에는 dashboard.py 등에서 course_names를 넘겨받아야 함)
    # 여기서는 임시 테스트용
    refiner = DataRefiner()
    # 임시 코스명 맵 (테스트용)
    test_map = {} 
    refiner.run_refinement(test_map)
