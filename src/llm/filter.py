import argparse
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Iterable

import httpx
import ollama

from src.records.models import Record

logger = logging.getLogger(__name__)


def read_records(path: Path) -> Iterable[Record]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            yield Record(**data)


def summarize_payload(payload: object, limit: int = 2000) -> str:
    """payload를 문자열로 요약(길이 제한)."""
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > limit:
        text = text[:limit] + "...(truncated)"
    return text


def build_prompt(rec: Record) -> str:
    payload_text = summarize_payload(rec.payload)
    tags = ", ".join(rec.tags)
    return (
        "다음 크롤링 데이터를 검토해 유용한 정보만 간략히 정리하세요. "
        "JSON 한 줄로 반환하며, 키는 "
        "`{category, title, course_or_board, summary, deadline, actions, urls}` 로 해주세요. "
        "정보가 없으면 null로 채우고, 목록은 배열로 하세요.\n\n"
        f"source: {rec.source}\n"
        f"category: {rec.category}\n"
        f"tags: {tags}\n"
        f"url: {rec.url}\n"
        f"title: {rec.title}\n"
        f"payload: {payload_text}\n"
    )


def call_ollama(model: str, prompt: str) -> str:
    resp = ollama.generate(
        model=model,
        prompt=prompt,
        system="너는 크롤링된 웹페이지 데이터를 JSON으로 깔끔하게 정리하는 어시스턴트다. "
        "필요 없는 부분들은 제거하고, 일반적인 사용자가 집중할 정보만 남겨야 한다.",
        stream=False,
        options={"temperature": 0},
    )
    if isinstance(resp, dict):
        return resp.get("response", "").strip()
    return str(resp).strip()


def is_service_up(host: str) -> bool:
    try:
        r = httpx.get(f"{host}/api/tags", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


def ensure_ollama(host: str) -> None:
    """로컬에 ollama가 설치되어 있으면 서버를 자동 기동."""
    if is_service_up(host):
        return
    binary = shutil.which("ollama")
    if not binary:
        raise RuntimeError("ollama 실행 파일을 찾을 수 없습니다. 설치 후 다시 시도하세요.")
    logging.info("ollama 서비스가 꺼져 있어 자동으로 기동합니다.")
    subprocess.Popen([binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if is_service_up(host):
            logging.info("ollama 서비스 기동 완료")
            return
        time.sleep(1)
    raise RuntimeError("ollama 서비스를 20초 내에 기동하지 못했습니다.")


def main() -> None:
    parser = argparse.ArgumentParser(description="records.jsonl → ollama 요약/필터")
    parser.add_argument("--input", type=Path, default=Path("data/raw/records.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/filtered.jsonl"))
    parser.add_argument("--model", required=True, help="ollama 모델 이름(예: gpt-oss:20b)")
    parser.add_argument("--host", default="http://localhost:11434", help="ollama 호스트 URL")
    parser.add_argument("--limit", type=int, default=0, help="처리할 레코드 수 제한(0이면 전체)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    try:
        ensure_ollama(args.host)
    except Exception as e:
        logger.error("ollama 준비 실패: %s", e)
        return

    count = 0
    with args.output.open("a", encoding="utf-8") as out:
        for rec in read_records(args.input):
            if args.limit and count >= args.limit:
                break
            prompt = build_prompt(rec)
            try:
                resp = call_ollama(args.model, prompt)
            except Exception as e:
                logger.error("LLM 호출 실패: %s", e)
                continue
            row: Dict[str, object] = {
                "record_id": rec.id,
                "source": rec.source,
                "category": rec.category,
                "tags": rec.tags,
                "url": rec.url,
                "llm": resp,
            }
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
            logger.info("처리 완료: %s (%s)", rec.id, rec.category)

    logger.info("총 %d 건 처리", count)


if __name__ == "__main__":
    main()
