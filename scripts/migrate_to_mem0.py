import json
import asyncio
import logging
from pathlib import Path
from src.db.mem0_client import AcademicMemory

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def migrate():
    # 1. Load Data
    db_path = Path("data/structured_db.json")
    if not db_path.exists():
        logger.error("No structured_db.json found. Run ETL first.")
        return

    with open(db_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info(f"Loaded {len(data)} records. Initializing Mem0...")

    # 2. Init Memory
    memory = AcademicMemory()
    if not memory.memory:
        logger.error("Failed to initialize Mem0. Check configs.")
        return

    # 3. Iterate and Store
    user_id = "global_student_agent" # Shared memory for the agent
    
    count = 0
    for item in data:
        # Schema: item has 'title', 'content_summary', 'date', 'url', 'course_name', etc.
        
        # Construct meaningful text for embedding
        # "[Software Engineering] Assignment 1: Define Requirements..."
        course = item.get("course_name", "General")
        title = item.get("title", "No Title")
        summary = item.get("content_summary", "")
        date = item.get("date", "")
        
        text_payload = f"[{course}] {title}\nDate: {date}\nSummary: {summary}"
        
        # Metadata
        meta = {
            "course_id": item.get("course_id"),
            "url": item.get("url"),
            "type": item.get("category"),
            "original_id": item.get("original_id")
        }
        
        # Add to Mem0
        # Mem0 extracts facts. If we want pure retrieval, we hope it indexes the 'content'.
        memory.add_record(text_payload, user_id=user_id, metadata=meta)
        
        count += 1
        if count % 10 == 0:
            logger.info(f"Processed {count}/{len(data)} items...")

    logger.info(f"Migration Complete! {count} items stored in Mem0.")

if __name__ == "__main__":
    migrate()
