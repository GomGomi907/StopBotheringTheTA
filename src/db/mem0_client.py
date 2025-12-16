import os
import logging
from typing import List, Dict, Optional, Any
from mem0 import Memory
from src.config.settings import Settings

logger = logging.getLogger(__name__)

class AcademicMemory:
    """
    Wrapper for Mem0 Memory Client.
    Manages semantic storage of academic records (notices, assignments).
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AcademicMemory, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        settings = Settings.from_env()
        
        # [Config]
        # Use Local Ollama for everything to avoid API Keys
        config = {
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": "data/mem0_storage_v3", # Local Qdrant (Fresh V3)
                    "embedding_model_dims": 768,
                }
            },
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": "gpt-oss", # Reuse project's main model
                    "temperature": 0.1
                }
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": "nomic-embed-text"
                }
            }
        }
        
        try:
            self.memory = Memory.from_config(config)
            logger.info("AcademicMemory (Mem0) initialized with Local Ollama & Qdrant.")
        except Exception as e:
            logger.error(f"Failed to init Mem0: {e}")
            self.memory = None

        self._initialized = True

    def add_record(self, text: str, user_id: str, metadata: Dict[str, Any] = None) -> None:
        """
        Add a single academic record to memory.
        :param text: Content summary (e.g. "[SW중심] 해커톤 모집 안내...")
        :param user_id: 'student_id' or 'global_agent'
        :param metadata: {course_id, url, date, type...}
        """
        if not self.memory: return

        try:
            # Mem0 add expects specific format. 
            # messages: List[Dict] = [{"role": "user", "content": ...}] matches chat style
            # OR simple text? SDK docs say .add(messages, user_id, metadata)
            
            # Since we are storing "Facts" or "Context", passing it as a system/user msg works.
            # But Mem0 extracts facts. If we want raw retrieval, we might rely on vector search.
            
            self.memory.add(
                messages=[{"role": "user", "content": text}], 
                user_id=user_id,
                metadata=metadata
            )
        except Exception as e:
            logger.warning(f"Mem0 add failed: {e}")

    def search(self, query: str, user_id: str, limit: int = 5) -> List[Dict]:
        """
        Semantic search for relevant memories.
        """
        if not self.memory: return []
        
        try:
            # .search returns list of results
            results = self.memory.search(query=query, user_id=user_id, limit=limit)
            return results
        except Exception as e:
            logger.error(f"Mem0 search failed: {e}")
            return []

    def get_all(self, user_id: str) -> List[Dict]:
        if not self.memory: return []
        try:
            return self.memory.get_all(user_id=user_id)
        except Exception as e:
            return []
