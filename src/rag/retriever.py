import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from src.config.settings import Settings

logger = logging.getLogger(__name__)


class ContextRetriever:
    """
    RAG 컨텍스트 검색기
    - 학기별 데이터 로드 지원
    - 키워드 기반 검색 (Mem0 fallback)
    - 주차별/전체 필터링
    """
    
    def __init__(self, data: List[Dict] = None, semester: Optional[str] = None):
        self.data = data
        self.settings = Settings.from_env()
        
        # 학기 설정
        if semester:
            self.settings = self.settings.with_semester(semester)
        
        self.db_path = self.settings.structured_db_path
        
        # 레거시 경로 fallback
        if not self.db_path.exists():
            legacy = Path("data/structured_db.json")
            if legacy.exists():
                self.db_path = legacy
        
    def _load_data(self) -> List[Dict]:
        if self.data:
            return self.data
            
        if not self.db_path.exists():
            logger.warning(f"DB not found: {self.db_path}")
            return []
        
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                # [Robust] Filter out non-dict items
                self.data = [x for x in raw_data if isinstance(x, dict)]
                return self.data
        except Exception as e:
            logger.error(f"Failed to load DB: {e}")
            return []

    def retrieve_context(self, mode: str = "all", current_week: int = None, query: str = "") -> List[Dict]:
        """
        Retrieve context items based on mode/query.
        modes: 'all', 'weekly', 'query'
        """
        items = self._load_data()
        
        if mode == "weekly" and current_week:
            return [i for i in items if i.get("week_index") == current_week]
            
        if mode == "query" and query:
            # 간단한 키워드 검색 (Mem0 대신)
            return self._keyword_search(items, query)
            
        return items
    
    def _keyword_search(self, items: List[Dict], query: str, limit: int = 10) -> List[Dict]:
        """
        간단한 키워드 기반 검색 (TF-IDF 없이)
        - 제목, 내용에서 키워드 매칭
        - 매칭 횟수로 점수 계산
        """
        query_lower = query.lower()
        keywords = query_lower.split()
        
        scored_items = []
        for item in items:
            score = 0
            title = str(item.get("title", "")).lower()
            content = str(item.get("content_clean", "")).lower()
            course = str(item.get("course_name", "")).lower()
            
            search_text = f"{title} {content} {course}"
            
            for kw in keywords:
                # 키워드가 포함된 횟수
                score += search_text.count(kw) * 2
                # 제목에 있으면 가산점
                if kw in title:
                    score += 5
            
            if score > 0:
                item_copy = item.copy()
                item_copy["_search_score"] = score
                scored_items.append(item_copy)
        
        # 점수순 정렬
        scored_items.sort(key=lambda x: x.get("_search_score", 0), reverse=True)
        
        return scored_items[:limit]

    def get_weekly_context(self, today: datetime = None) -> Dict[str, Any]:
        # Legacy support or usage for Dashboard Summary
        # Update to use _load_data
        if today is None: today = datetime.now()
        kb = self._load_data()
        
        start_date = today - timedelta(days=3)
        end_date = today + timedelta(days=14)
        
        timeline_items = []
        course_briefing = {}
        
        for item in kb:
             # ... (Keep existing logic but use 'item')
             # Re-implementing simplified logic to avoid complex merge issues
             item_date_str = item.get("due_date") or item.get("inferred_date")
             item_date = None
             if item_date_str:
                 try: item_date = datetime.strptime(item_date_str[:10], "%Y-%m-%d")
                 except: pass
                 
             if item_date and start_date <= item_date <= end_date:
                 delta = (item_date - today).days
                 d_day = f"D-{delta}" if delta >= 0 else f"Overdue"
                 timeline_items.append({
                     "date": item_date_str[:10],
                     "d_day": d_day,
                     "title": item.get("title"),
                     "course": item.get("course_name"),
                     "category": item.get("category"),
                     "importance": 3 # Dummy
                 })
                 
             cname = item.get("course_name", "Unknown")
             if cname not in course_briefing: course_briefing[cname] = []
             course_briefing[cname].append(item)
             
        return {"timeline": timeline_items, "briefing": course_briefing}
