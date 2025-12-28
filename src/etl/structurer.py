import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import defaultdict
from datetime import datetime, timedelta

from src.config.settings import Settings
from src.llm.client import LLMClient
from src.processing.metadata import MetadataExtractor
from src.processing.date_parser import extract_date, validate_date, _make_naive

logger = logging.getLogger(__name__)

# Rule-based 카테고리 매핑
CATEGORY_MAP = {
    # Raw category -> ETL category
    "announcement": "notice",
    "discussion_raw": "notice",
    "syllabus": "material",
    "week_module": "material",
    "file_meta": "material",
    # Module item types
    "Assignment": "assignment",
    "Quiz": "quiz",
    "Page": "material",
    "File": "material",
    "ExternalUrl": "material",
    "ExternalTool": "video",  # LearningX 동영상 등
}

def _infer_category_static(raw_category: str, item_type: str, title: str) -> str:
    """Rule-based 카테고리 추론"""
    # 1. item_type 우선 (Assignment, Quiz 등)
    if item_type and item_type in CATEGORY_MAP:
        return CATEGORY_MAP[item_type]
    
    # 2. raw_category
    if raw_category and raw_category in CATEGORY_MAP:
        return CATEGORY_MAP[raw_category]
    
    # 3. 제목 키워드 기반
    title_lower = (title or "").lower()
    if any(kw in title_lower for kw in ["과제", "assignment", "report", "제출"]):
        return "assignment"
    if any(kw in title_lower for kw in ["퀴즈", "quiz", "시험", "test"]):
        return "quiz"
    if any(kw in title_lower for kw in ["공지", "안내", "notice"]):
        return "notice"
    
    # 4. 기본값
    return "material"


class DataStructurer:
    """
    [Robust ETL] Raw Data -> Structured Database Converter
    - LLM을 사용하여 비정형 데이터를 정형화 (Week, Date, Type 정규화)
    - 파일 매핑 및 주차 정보 연동
    - 학기별 데이터 분리 저장 지원
    """
    def __init__(self, semester: Optional[str] = None):
        self.settings = Settings.from_env()
        
        # 학기 설정 (외부에서 주입 가능)
        if semester:
            self.settings = self.settings.with_semester(semester)
        
        self.client = LLMClient()
        self.extractor = MetadataExtractor()
        
        # 학기별 경로 사용 (레거시 호환 포함)
        self.db_path = self.settings.structured_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.debug_log_path = self.settings.semester_dir / "etl_debug.log"
        
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
                    
                    # due_at 추출 (여러 위치에서 확인)
                    raw_due_at = (
                        payload.get("due_at") or 
                        payload.get("content_details", {}).get("due_at") or
                        payload.get("lock_at")
                    )
                    
                    enriched_chunk.append({
                        "original_id": item.get("id"),
                        "category": item.get("category"),
                        "item_type": item_type,  # [NEW] item_type 추가
                        "title": item.get("title"),
                        "body_text": final_body, 
                        "week_hint": week_hint,
                        "dates": {
                            "due_at": raw_due_at,
                            "posted_at": payload.get("posted_at") or payload.get("created_at"),
                        },
                        "parsed_date": self._preparse_date(raw_body, payload),
                        "files": []
                    })
                
                try:
                    normalized_results = self.client.normalize_items(c_name, enriched_chunk)
                    self._log_debug(f"  [Chunk {i}] Received {len(normalized_results)} items from LLM")
                    
                    # [NEW] enriched_chunk와 매핑하여 due_date/category 직접 보강
                    chunk_by_id = {c["original_id"]: c for c in enriched_chunk if c.get("original_id")}
                    
                    for res in normalized_results:
                        res["course_id"] = cid
                        res["course_name"] = c_name
                        
                        oid = res.get("original_id")
                        raw_chunk = chunk_by_id.get(oid, {})
                        
                        # [NEW] 카테고리 Rule-based 보강
                        inferred_cat = _infer_category_static(
                            raw_chunk.get("category", ""),
                            raw_chunk.get("item_type", ""),
                            res.get("title", "")
                        )
                        # LLM 결과가 없거나 generic하면 Rule-based로 덮어쓰기
                        if not res.get("category") or res.get("category") in ["other", "unknown"]:
                            res["category"] = inferred_cat
                        
                        # due_date 직접 추출 (LLM 실패 시 백업)
                        if not res.get("due_date"):
                            raw_dates = raw_chunk.get("dates", {})
                            due_at = raw_dates.get("due_at")
                            if due_at:
                                res["due_date"] = self._parse_iso_date(due_at)
                                self._log_debug(f"    [DUE] {res.get('title', 'N/A')[:20]} -> {res['due_date']}")
                        
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

    def _preparse_date(self, body_text: str, payload: Dict) -> Optional[Dict]:
        """
        [Rule-based] 텍스트에서 날짜를 미리 추출하여 LLM에 힌트 제공.
        LLM은 이 힌트를 참고하되, 최종 판단은 LLM이 함.
        """
        # posted_at을 anchor로 사용
        posted_at_str = payload.get("posted_at") or payload.get("created_at")
        anchor = None
        if posted_at_str:
            try:
                # ISO 형식 파싱 후 naive로 변환 (timezone 비교 오류 방지)
                anchor = datetime.fromisoformat(posted_at_str.replace("Z", "+00:00"))
                anchor = _make_naive(anchor)
            except ValueError:
                pass
        
        # 제목 + 본문에서 날짜 추출 시도
        title = payload.get("title", "")
        search_text = f"{title} {body_text}"
        
        parsed_date, confidence = extract_date(search_text, anchor)
        
        if parsed_date and confidence != 'none':
            # 검증
            if validate_date(parsed_date, title):
                return {
                    "date": parsed_date.strftime("%Y-%m-%d"),
                    "time": parsed_date.strftime("%H:%M") if parsed_date.hour or parsed_date.minute else None,
                    "confidence": confidence,
                    "source": "rule_based"
                }
        
        return None

    def _parse_iso_date(self, iso_str: str) -> Optional[str]:
        """ISO 8601 날짜 문자열을 YYYY-MM-DD HH:MM 형식으로 변환"""
        if not iso_str:
            return None
        try:
            # ISO 형식 파싱 (예: 2025-12-31T23:59:00Z)
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            dt = _make_naive(dt)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return None

