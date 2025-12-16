import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta

from src.config.settings import Settings
from src.llm.client import LLMClient
from src.processing.metadata import MetadataExtractor

logger = logging.getLogger(__name__)

class DataStructurer:
    """
    [Robust ETL] Raw Data -> Structured Database Converter
    - LLM을 사용하여 비정형 데이터를 정형화 (Week, Date, Type 정규화)
    - 파일 매핑 및 주차 정보 연동
    """
    def __init__(self):
        self.settings = Settings.from_env()
        self.client = LLMClient()
        self.extractor = MetadataExtractor()
        self.db_path = Path("data/structured_db.json")
        self.debug_log_path = Path("data/etl_debug.log")
        
    def _log_debug(self, msg: str):
        with open(self.debug_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
            
    def load_raw_records(self) -> List[Dict]:
        records_path = self.settings.raw_records_dir / "records.jsonl"
        if not records_path.exists():
            return []
        
        data = []
        with open(records_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except: pass
        return data

    def run_normalization(self, target_course_id: str = None, progress_callback=None) -> List[Dict]:
        """전체 ETL 실행: Raw Records -> Structured DB (Incremental)"""
        raw_data = self.load_raw_records()
        if not raw_data:
            self._log_debug("No raw records found !!")
            logger.warning("No raw records found.")
            return []
            
        self._log_debug(f"Loaded {len(raw_data)} raw records.")

        # 0. 기존 DB 로드 (Incremental)
        existing_db = []
        processed_ids = set()
        if self.db_path.exists():
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    existing_db = json.load(f)
                    for item in existing_db:
                        if "original_id" in item:
                            processed_ids.add(item["original_id"])
            except Exception as e:
                logger.warning(f"기존 DB 로드 실패: {e}")

        # 1. 과목별 그룹화
        grouped = defaultdict(list)
        course_info = {}
        
        for rec in raw_data:
            payload = rec.get("payload", {})
            cid = str(payload.get("course_id") or "common")
            if cid == "common":
                tags = rec.get("tags", [])
                if len(tags) > 1: cid = tags[1]
            
            if rec.get("category") == "course":
                course_info[str(payload.get("id"))] = rec.get("name") or rec.get("title")
                
            grouped[cid].append(rec)

        new_items_db = []
        
        # 2. 과목별 처리
        total_courses = len(grouped)
        for idx, (cid, items) in enumerate(grouped.items(), 1):
            if target_course_id and cid != target_course_id:
                continue
                
            c_name = course_info.get(cid, f"Course {cid}")
            if c_name == "common": c_name = "일반 공지" # Normalization
            
            # [UI Feed] Notify User
            if progress_callback:
                progress_callback(c_name, idx, total_courses)
            
            # Module Context 구축
            module_map = self._build_module_map(items)
            
            # 중복 제거 & 이미 처리된 항목 필터링
            unique_items = self._deduplicate_items(items)
            items_to_process = []
            
            for item in unique_items:
                # [Filter] Skip Navigation Tabs
                cat = item.get("category")
                if cat in ["external_tool_tab"]:
                    continue
                
                # [Context Strategy] Course/Syllabus are "Global Context Providers"
                # We don't necessarily want them as separate 'cards' in the UI if they just duplicate info,
                # BUT we absolutely need them for context.
                # Let's keep them in the processing loop but mark them.
                # actually, 'course' category is useful for the Course Name map, but maybe not as a DB item?
                # The user wants "Item 1 explains Items 2~10". Item 1 IS the Course/Syllabus.
                # So we should PROCESS it.
                if cat == "course":
                     # We might want to save it as a "Course Overview" item too?
                     # For now, let's allow it into processing so we can extract its context.
                     pass 


                # [User Request] Skip logic disabled (Force Re-process)
                items_to_process.append(item)
            
            if not items_to_process:
                logger.info(f"Skipping Course: {c_name} (All {len(unique_items)} items up-to-date)")
                continue

            # [Context Propagation] Sort by Module ID then Position to ensure linear order
            items_to_process.sort(key=lambda x: (
                x.get("payload", {}).get("_context_module_id") or 0,
                x.get("payload", {}).get("position") or 0
            ))

            logger.info(f"Processing Course: {c_name} ({len(items_to_process)} new items)")
            self._log_debug(f"Course: {c_name} | Processing {len(items_to_process)} items (Sorted)")
            
            # [Context Strategy] Build Course Global Context (Syllabus/Course Info)
            course_global_context = ""
            # Find syllabus or course item in this batch (or whole list)
            # Since we have `items_to_process`, let's scan them first for high-level context
            for item in items_to_process:
                if item.get("category") in ["course", "syllabus"]:
                     p = item.get("payload", {})
                     body = p.get("body") or p.get("conent") or item.get("title")
                     if isinstance(body, str):
                         course_global_context += f"[{item.get('category').upper()}] {body[:1000]}\n"
            
            logger.info(f"Course: {c_name} | Global Context Length: {len(course_global_context)}")

            # Context State
            current_module_id = None
            context_buffer = "" 

            # LLM Batch Processing
            chunk_size = 5
            for i in range(0, len(items_to_process), chunk_size):
                chunk = items_to_process[i:i+chunk_size]
                self._log_debug(f"  [Chunk {i}] Sending {len(chunk)} items...")
                
                enriched_chunk = []
                for item in chunk:
                    payload = item.get("payload", {})
                    mod_id = payload.get("_context_module_id") 
                    week_hint = module_map.get(mod_id, "")
                    
                    # Manage Module Context
                    if mod_id != current_module_id:
                        current_module_id = mod_id
                        context_buffer = "" 
                    
                    raw_body = self.extractor.summarize_item(payload, "", "").get("content_summary", "")
                    item_type = payload.get("type", "")
                    cat = item.get("category")

                    # Update Context Buffer (Modules/Pages)
                    if item_type in ["Page", "SubHeader"] or cat == "announcement":
                         context_buffer += f"\n[Module Context: {item.get('title')}] {raw_body[:500]}..."
                    
                    # [Context Injection] Hierarchy: Course > Module > Item
                    final_body = ""
                    
                    # 1. Course Context
                    if course_global_context:
                        final_body += f"=== COURSE CONTEXT ===\n{course_global_context}\n"
                    
                    # 2. Module Context
                    if context_buffer and item_type not in ["SubHeader"]:
                         final_body += f"=== MODULE CONTEXT ===\n{context_buffer}\n"
                    
                    # 3. Item Content
                    final_body += f"=== ITEM CONTENT ===\n{raw_body}"
                    
                    # Prevent self-duplication if item IS the context provider
                    # (LLM can handle it, but cleaner to avoid exact duplicates if possible)
                    
                    enriched_chunk.append({
                        "original_id": item.get("id"),
                        "category": item.get("category"), # Keep 'course' category for now
                        "title": item.get("title"),
                        "body_text": final_body, 
                        "week_hint": week_hint,
                        "dates": {
                            "due_at": payload.get("due_at"),
                            "posted_at": payload.get("posted_at") or payload.get("created_at"),
                        },
                        "files": []
                    })
                
                try:
                    normalized_results = self.client.normalize_items(c_name, enriched_chunk)
                    self._log_debug(f"  [Chunk {i}] Received {len(normalized_results)} items from LLM")
                    
                    for res in normalized_results:
                        res["course_id"] = cid
                        res["course_name"] = c_name
                        if "original_id" not in res:
                             # Try to match by index if sizes match?
                             pass
                        new_items_db.append(res)
                        
                except Exception as e:
                    self._log_debug(f"  [Chunk {i}] Failed: {str(e)}")
                    logger.error(f"Normalization failed for chunk: {e}")

        # 3. 병합 및 저장
        raw_final = existing_db + new_items_db
        
        # Deduplicate Final DB (Prevent duplicate keys in UI)
        clean_map = {}
        for item in raw_final:
            oid = item.get("original_id")
            if oid:
                clean_map[oid] = item
            else:
                # No ID items (fallback)
                clean_map[f"noid_{len(clean_map)}"] = item
                
        final_db = list(clean_map.values())
        
        if len(raw_final) != len(final_db):
            logger.info(f"Removed {len(raw_final) - len(final_db)} duplicates during merge.")
            
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(final_db, f, ensure_ascii=False, indent=2)
            
        return final_db

    def _build_module_map(self, items: List[Dict]) -> Dict[int, str]:
        """Module ID -> Module Name (Week Hint) 매핑"""
        mapping = {}
        for item in items:
            if item.get("category") == "week_module":
                p = item.get("payload", {})
                mapping[p.get("id")] = p.get("name")
        return mapping

    def _deduplicate_items(self, items: List[Dict]) -> List[Dict]:
        """Announcement와 Discussion 중복 제거 (URL/Title 유사성)"""
        seen_ids = set()
        unique = []
        
        # 공지사항 우선
        announcements = [i for i in items if i.get("category") == "announcement"]
        others = [i for i in items if i.get("category") != "announcement"]
        
        for item in announcements:
            pid = str(item.get("payload", {}).get("id"))
            seen_ids.add(pid)
            unique.append(item)
            
        for item in others:
            pid = str(item.get("payload", {}).get("id"))
            if pid in seen_ids:
                continue
            
            # 카테고리가 file_meta, module_item 등인 경우 다 포함
            # 단, module_item 중 type이 Page/Discussion인 경우 중복될 수 있음.
            # 일단은 다 포함하고 LLM에게 맡김 (Rule-based로 하면 복잡)
            unique.append(item)
            
        return unique
