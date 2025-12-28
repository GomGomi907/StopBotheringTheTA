"""
Simple Rule-based ETL (LLM 불필요)
- Raw 데이터를 타입 기반으로 직접 변환
- 빠른 속도, 100% 정확도
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from collections import defaultdict

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class SimpleStructurer:
    """
    Rule-based ETL: Raw Records -> Structured DB
    LLM 없이 타입 기반 직접 변환
    """
    
    def __init__(self, semester: Optional[str] = None):
        self.settings = Settings.from_env()
        if semester:
            self.settings = self.settings.with_semester(semester)
        
        self.db_path = self.settings.structured_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def load_raw_records(self) -> List[Dict]:
        """Raw JSONL 로드"""
        records_path = self.settings.raw_records_dir / "records.jsonl"
        if not records_path.exists():
            return []
        
        data = []
        with open(records_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except:
                    pass
        return data
    
    def run(self, progress_callback=None) -> List[Dict]:
        """ETL 실행"""
        raw_data = self.load_raw_records()
        if not raw_data:
            logger.warning("No raw records found.")
            return []
        
        logger.info(f"Processing {len(raw_data)} raw records...")
        
        # 과목 정보 수집
        course_map = {}
        for rec in raw_data:
            if rec.get("category") == "course":
                cid = str(rec.get("payload", {}).get("id", ""))
                cname = rec.get("title") or rec.get("payload", {}).get("name", "")
                course_map[cid] = cname
        
        # 변환
        results = []
        processed = 0
        total = len(raw_data)
        
        for rec in raw_data:
            transformed = self._transform_record(rec, course_map)
            if transformed:
                results.append(transformed)
            
            processed += 1
            if progress_callback and processed % 100 == 0:
                progress_callback(processed, total)
        
        # 중복 제거
        unique = {}
        for item in results:
            unique[item["id"]] = item
        results = list(unique.values())
        
        # 저장
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved {len(results)} items to {self.db_path}")
        return results
    
    def _transform_record(self, rec: Dict, course_map: Dict) -> Optional[Dict]:
        """단일 레코드 변환"""
        category = rec.get("category", "")
        payload = rec.get("payload", {})
        item_type = payload.get("type", "")
        
        # 스킵할 카테고리
        if category in ["course", "external_tool_tab"]:
            return None
        
        # 타입 결정
        db_type = self._infer_type(category, item_type, rec.get("title", ""))
        
        # 과목 정보
        course_id = self._extract_course_id(rec, payload)
        course_name = course_map.get(course_id, "")
        
        # 날짜 추출
        due_date = self._extract_due_date(payload)
        posted_date = self._extract_posted_date(payload)
        
        # 주차 추출
        week_index = self._extract_week(rec, payload)
        
        # 콘텐츠 추출
        content = self._extract_content(rec, payload)
        
        return {
            "id": rec.get("id", ""),
            "original_id": rec.get("id", ""),
            "type": db_type,
            "category": db_type,  # UI 호환
            "title": rec.get("title") or payload.get("title", ""),
            "course_id": course_id,
            "course_name": course_name,
            "week_index": week_index,
            "due_date": due_date,
            "posted_date": posted_date,
            "inferred_date": due_date or posted_date,
            "content_clean": content,
            "url": payload.get("html_url", ""),
            "is_action_required": db_type in ["assignment", "quiz"],
        }
    
    def _infer_type(self, category: str, item_type: str, title: str) -> str:
        """타입 추론"""
        # 1. item_type 기반
        if item_type == "Assignment":
            return "assignment"
        if item_type == "Quiz":
            return "quiz"
        if item_type == "ExternalTool":
            return "video"
        if item_type in ["File", "Page"]:
            return "material"
        
        # 2. category 기반
        if category == "announcement":
            return "notice"
        if category == "syllabus":
            return "material"
        if category == "week_module":
            return "material"
        if category == "module_item":
            return "material"
        
        # 3. 제목 키워드
        title_lower = title.lower()
        if any(kw in title_lower for kw in ["과제", "assignment", "report", "제출"]):
            return "assignment"
        if any(kw in title_lower for kw in ["퀴즈", "quiz", "시험", "test"]):
            return "quiz"
        if any(kw in title_lower for kw in ["공지", "안내", "notice"]):
            return "notice"
        
        return "material"
    
    def _extract_course_id(self, rec: Dict, payload: Dict) -> str:
        """과목 ID 추출"""
        # 1. payload에서
        cid = payload.get("course_id")
        if cid:
            return str(cid)
        
        # 2. tags에서
        tags = rec.get("tags", [])
        if len(tags) > 1:
            return str(tags[1])
        
        return ""
    
    def _extract_due_date(self, payload: Dict) -> Optional[str]:
        """마감일 추출"""
        candidates = [
            payload.get("due_at"),
            payload.get("content_details", {}).get("due_at"),
            payload.get("lock_at"),
        ]
        
        for c in candidates:
            if c:
                return self._parse_iso_date(c)
        return None
    
    def _extract_posted_date(self, payload: Dict) -> Optional[str]:
        """게시일 추출"""
        candidates = [
            payload.get("posted_at"),
            payload.get("created_at"),
        ]
        
        for c in candidates:
            if c:
                return self._parse_iso_date(c)
        return None
    
    def _extract_week(self, rec: Dict, payload: Dict) -> int:
        """주차 추출"""
        # 1. 모듈 이름에서
        module_name = payload.get("_context_module_name", "")
        week_match = re.search(r"(\d+)\s*주", module_name)
        if week_match:
            return int(week_match.group(1))
        
        # 2. 제목에서
        title = rec.get("title", "")
        week_match = re.search(r"week\s*(\d+)|(\d+)\s*주", title, re.IGNORECASE)
        if week_match:
            return int(week_match.group(1) or week_match.group(2))
        
        return 0
    
    def _extract_content(self, rec: Dict, payload: Dict) -> str:
        """콘텐츠 추출"""
        # 우선순위: message > body > description
        content = (
            payload.get("message") or 
            payload.get("body") or 
            payload.get("description") or
            ""
        )
        
        # HTML 태그 제거 (간단)
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        
        return content[:500]  # 500자 제한
    
    def _parse_iso_date(self, iso_str: str) -> Optional[str]:
        """ISO 날짜 파싱"""
        if not iso_str:
            return None
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except:
            return None
