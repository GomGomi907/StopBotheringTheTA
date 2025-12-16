import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ContextRetriever:
    def __init__(self, data: List[Dict] = None):
        self.data = data
        self.db_path = Path("data/structured_db.json")
        
    def _load_data(self) -> List[Dict]:
        if self.data:
            return self.data
            
        if not self.db_path.exists():
            return []
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                # [Robust] Filter out non-dict items (e.g. error messages or raw strings in JSON)
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
            # Filter by week (+- 1 week variance?)
            # Strictly matching current week for now
            return [i for i in items if i.get("week_index") == current_week]
            
        if mode == "query" and query:
            # [Mem0 Integration] Semantic Search
            from src.db.mem0_client import AcademicMemory
            memory = AcademicMemory()
            hits = []
            
            # Mem0 Search
            results = memory.search(query, user_id="global_student_agent", limit=5)
            
            # [Fix] Robust Type Check for Mem0 Results
            if not isinstance(results, list):
                if isinstance(results, dict): results = [results]
                else: results = []
                
            for res in results:
                if not isinstance(res, dict): continue
                
                # Mem0 returns {'memory': '...', 'metadata': {...}, 'score': ...}
                # Map back to item structure as best as possible
                meta = res.get("metadata", {})
                if not isinstance(meta, dict): meta = {}
                
                hits.append({
                    "title": "🔍 " + str(res.get("memory", "")).split("\n")[0], # First line as title
                    "content_clean": str(res.get("memory", "")),
                    "course_name": meta.get("course_id", "Unknown"), # ID only in meta
                    "category": meta.get("type", "search_result"),
                    "url": meta.get("url"),
                    "_score": res.get("score")
                })
            return hits
            
        # Default: Return all (filtered by some relevance if needed)
        # For 'all', we might want to return everything or just recent?
        # Let's return everything for currently small DB
        return items

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
