import logging
import json
import httpx
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, api_url: str = "http://localhost:11434", model: str = "gpt-oss:20B"):
        self.api_url = api_url
        self.model = model
        self.timeout = 180.0  # 3분 (사용자 요청)

    def generate_course_report(self, course_name: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """특정 과목의 데이터를 받아 Ollama로 요약 JSON 생성"""
        
        # 오늘 날짜 주입 (D-Day 계산용)
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        # 시스템 프롬프트 (JSON 강제 + Context-Aware)
        system_prompt = (
            f"You are a smart academic assistant. Today is **{today_str}**.\n"
            "Analyze the provided course data and extract structured data in JSON format.\n"
            "DO NOT write any conversational text. OUTPUT ONLY VALID JSON.\n\n"
            "[JSON SCHEMA]\n"
            "{\n"
            "  \"summary\": \"One-line summary (Korean)\",\n"
            "  \"urgency_score\": 0 to 10 (int),\n"
            "  \"deadlines\": [\n"
            "    { \n"
            "      \"title\": \"task name\", \n"
            "      \"date\": \"YYYY-MM-DD (calculated)\", \n"
            "      \"d_day\": \"D-X\", \n"
            "      \"confidence\": \"high|medium|low\" \n"
            "    }\n"
            "  ],\n"
            "  \"announcements\": [\n"
            "    { \"title\": \"title\", \"date\": \"YYYY-MM-DD\", \"is_new\": true/false }\n"
            "  ],\n"
            "  \"materials\": [\n"
            "    { \"title\": \"title\", \"week\": \"14 week\", \"summary\": \"brief summary\" }\n"
            "  ]\n"
            "}\n"
            "[CRITICAL RULES]\n"
            "1. **DATE INFERENCE**: \n"
            "   - If a specific date is given (e.g., '12/15'), use it -> `confidence: 'high'`.\n"
            "   - If relative (e.g., 'Next Week', 'Tomorrow'), calculate based on the **'posted_at'** field of that item, NOT Today.\n"
            "   - If ambiguous (e.g., 'Sometime later'), set `confidence: 'low'` and do not guess a date.\n"
            "2. **DEADLINES**: Identify assignments/exams. \n"
            "3. **FILTERING**: Exclude empty weeks and old data (>3 months) unless Unsubmitted/Critical.\n"
            "4. **LANGUAGE**: Korean.\n"
        )

        # 사용자 입력 데이터 구성
        user_content = f"Course: {course_name}\nData:\n"
        user_content += json.dumps(items, ensure_ascii=False, default=str)
        
        # 토큰 절약
        if len(user_content) > 15000:
            user_content = user_content[:15000] + "\n...(truncated)"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_ctx": 4096},
            "format": "json" # Ollama JSON mode
        }

        try:
             with httpx.Client(timeout=self.timeout) as client:
                try:
                    resp = client.post(f"{self.api_url}/api/chat", json=payload)
                    resp.raise_for_status()
                    result = resp.json()
                    content = result.get("message", {}).get("content", "{}")
                    
                    # Clean up JSON if LLM adds markdown
                    content = content.replace("```json", "").replace("```", "").strip()
                    parsed_json = json.loads(content)
                    
                    # Ensure minimal keys exist
                    if "summary" not in parsed_json: parsed_json["summary"] = "요약 실패"
                    if "deadlines" not in parsed_json: parsed_json["deadlines"] = []
                    
                    return parsed_json
                    
                except Exception as e:
                    logger.error(f"Generate failed: {e}")
                    # Fallback on failure
                    return {
                        "summary": f"AI 분석 실패: {e}",
                        "urgency_score": 0,
                        "deadlines": [],
                        "announcements": [],
                    }
        
        except Exception as e:
            return {
                "summary": f"연결 오류: {e}",
                "urgency_score": 0,
                "deadlines": [],
                "announcements": [],
                "materials": []
            }



    def refine_chunk(self, course_name: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        [RAG ETL] Raw Items -> Refined Items 변환
        - 날짜 정규화 (YYYY-MM-DD)
        - 중요도 평가 (1~5)
        - 요약 (One-line)
        """
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")

        system_prompt = (
            f"You are a Data Refinement Specialist. Today is {today_str}.\n"
            "Your task is to CLEAN and ENRICH the provided raw academic data.\n"
            "For each item, extract/infer the following fields:\n"
            "1. `real_date`: The most relevant date (Due Date or Event Date) in 'YYYY-MM-DD' format. "
            "If strictly relative (e.g. 'next week'), calculate based on `posted_at`. If unknown/permanent, use null.\n"
            "2. `importance`: Integer 1 (Trivial) to 5 (Critical Exam/Deadline).\n"
            "3. `category`: 'assignment', 'exam', 'announcement', 'material'.\n"
            "4. `summary`: A concise, action-oriented summary (Korean).\n"
            "5. `original_id`: Preserve the input ID (e.g., 'quiz_123').\n\n"
            "OUTPUT FORMAT: JSON List of Objects."
        )

        user_content = f"Context: Course '{course_name}'\nData:\n"
        user_content += json.dumps(items, ensure_ascii=False, default=str)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": 4096},
            "format": "json"
        }

        try:
             with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.api_url}/api/chat", json=payload)
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "[]")
                
                # Parsing
                if "```" in content:
                    content = content.replace("```json", "").replace("```", "").strip()
                
                refined_items = json.loads(content)
                if isinstance(refined_items, dict) and "items" in refined_items:
                    refined_items = refined_items["items"]
                
                return refined_items if isinstance(refined_items, list) else []

        except Exception as e:
            logger.error(f"Refinement failed for chunk in {course_name}: {e}")
            return []

    def normalize_items(self, course_name: str, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        [Robust ETL] 정형화된 데이터베이스 구축을 위한 Deep Analysis
        - Input: Enriched Chunk (Title, Body, Hints, Dates)
        - Output: Structured DB Elements (Week, DueDate, Category, ActionRequired)
        """
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")

        system_prompt = (
            f"You are a strict data normalizer. Today is {today_str}.\n"
            "Convert raw academic items into a standardized database schema.\n"
            "Analyze 'week_hint', 'body_text', and 'dates' to infer the correct metadata.\n\n"
            "[OUTPUT SCHEMA]\n"
            "[\n"
            "  {\n"
            "    \"original_id\": \"string (MUST match the input 'original_id' exactly)\",\n"
            "    \"category\": \"assignment|material|notice\",\n"
            "    \"week_index\": integer (e.g., 3) or 0 (if unknown/common),\n"
            "    \"title\": \"string\",\n"
            "    \"is_action_required\": boolean (true for assignments/exams),\n"
            "    \"due_date\": \"YYYY-MM-DD HH:MM\" or null,\n"
            "    \"inferred_date\": \"YYYY-MM-DD\" (if relative date in text, calc from posted_at),\n"
            "    \"content_clean\": \"Detailed summary of requirements including all dates and constraints (Korean)\"\n"
            "  }\n"
            "]\n\n"
            "[RULES]\n"
            "1. **Week Inference**: Trust 'week_hint' first. If 'week_hint' is empty, try to find 'N주차' provided in title/body.\n"
            "2. **Date Inference**: \n"
            "   - If 'due_at' exists, use it as 'due_date'.\n"
            "   - If body says 'Next Week' or 'Until Friday', calculate 'inferred_date' based on the item's 'posted_at' date. Do NOT use Today's date for relative calculation.\n"
            "3. **Category**: \n"
            "   - 'assignment': tasks to submit.\n"
            "   - 'material': lecture notes, pdfs, videos.\n"
            "   - 'notice': announcements.\n"
            "4. **Language**: Use Korean for 'content_clean'."
        )

        user_content = f"Context: Course '{course_name}'\nData:\n"
        user_content += json.dumps(items, ensure_ascii=False, default=str)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_ctx": 8192}, # Context 늘림
            "format": "json"
        }

        try:
             with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.api_url}/api/chat", json=payload)
                resp.raise_for_status()
                content = resp.json().get("message", {}).get("content", "[]")
                
                # Parsing fallback
                if "```" in content:
                    content = content.replace("```json", "").replace("```", "").strip()
                
                try:
                    result = json.loads(content)
                except json.JSONDecodeError:
                    # Regex fallback for list extraction
                    import re
                    m = re.search(r'\[.*\]', content, re.DOTALL)
                    if m:
                        try:
                            result = json.loads(m.group(0))
                        except:
                            logger.error(f"JSON Regex Parse Failed. Raw: {content[:200]}...")
                            return []
                    else:
                        logger.error(f"JSON Parse Failed. Raw: {content[:200]}...")
                        return []

                # Ollama가 가끔 {"items": [...]} 형태로 줄 때도 있고 [...]로 줄 때도 있음
                if isinstance(result, list):
                    return result
                elif isinstance(result, dict):
                    if "items" in result and isinstance(result["items"], list):
                        return result["items"]
                    # If dict but no items key, look for any list value
                    for v in result.values():
                         if isinstance(v, list):
                             return v
                    return []
                else:
                    return []

        except Exception as e:
            logger.error(f"Normalization failed for chunk in {course_name}: {e}")
            return []
