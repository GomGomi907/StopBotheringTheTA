import argparse
import logging
import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from pathlib import Path

from src.config.settings import Settings
from src.domains.canvas import CanvasCrawler
from src.domains.learningx import download_learningx_files
from src.domains.notices import NoticesCrawler, load_board_configs
from src.records.writer import RecordWriter
from src.app import collect_cookies


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="학교/캔버스 크롤러")
    sub = parser.add_subparsers(dest="target", required=True)

    canvas = sub.add_parser("canvas", help="캔버스 전체/특정 과목 크롤링")
    canvas.add_argument(
        "--course-id",
        action="append",
        help="특정 코스 ID만 크롤링(여러 번 지정 가능). 없으면 활성 과목 전체.",
    )
    canvas.add_argument(
        "--download-files",
        action="store_true",
        help="캔버스 파일 메타 외 실제 파일도 다운로드",
    )

    notices = sub.add_parser("notices", help="학교/학과 공지 크롤링")
    notices.add_argument(
        "--config",
        type=Path,
        default=Path("boards.dankook.json"),
        help="게시판 설정 JSON 경로 (기본: boards.dankook.json)",
    )
    notices.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="게시판별 최대 페이지 수집 범위(기본 1)",
    )

    summarize = sub.add_parser("summarize", help="수집된 데이터를 요약하여 리포트 생성")
    summarize.add_argument(
        "--days",
        type=int,
        default=7,
        help="최근 N일 데이터만 요약 (NotImplemented)",
    )

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args()

    settings = Settings.from_env()
    writer = RecordWriter(base_path=settings.raw_records_dir)

    if args.target == "canvas":
        # 파일 다운로드 모드일 경우, 먼저 브라우저를 띄워 로그인 세션을 갱신한다.
        if args.download_files:
            print(">>> [안내] 파일 다운로드를 위해 브라우저 로그인을 진행합니다.")
            asyncio.run(
                collect_cookies(
                    name="캔버스",
                    url=settings.canvas_base_url or "https://canvas.dankook.ac.kr",
                    out_path=Path("data/cookies_canvas.json"),
                    user_data_dir=None,  # 자동 로그인 사용하므로 영구 프로필 불필요 & 충돌 방지
                )
            )

        crawler = CanvasCrawler(
            settings=settings,
            writer=writer,
            download_files=args.download_files,
        )
        courses = crawler.crawl(course_ids=args.course_id)
        
        if args.download_files and courses:
            # learningx 파일 다운로드 (Playwright 사용)
            course_ids = [c["id"] for c in courses]
            
            from src.domains.downloader import download_canvas_files
            
            asyncio.run(
                download_learningx_files(
                    base_url=settings.canvas_base_url or "https://canvas.dankook.ac.kr",
                    course_ids=course_ids,
                    cookies_path=Path("data/cookies_canvas.json"),
                    files_dir=settings.files_dir,
                    raw_dir=settings.raw_records_dir,
                    user_data_dir=None,
                )
            )
            
            # 일반 파일 다운로드 추가
            asyncio.run(
                download_canvas_files(
                    base_url=settings.canvas_base_url or "https://canvas.dankook.ac.kr",
                    course_ids=course_ids,
                    cookies_path=Path("data/cookies_canvas.json"),
                    files_dir=settings.files_dir,
                    user_data_dir=None,
                    raw_dir=settings.raw_records_dir,
                )
            )
            
    elif args.target == "notices":
        boards = load_board_configs(args.config, settings.notices_base_url)
        crawler = NoticesCrawler(settings=settings, writer=writer)
        crawler.crawl(boards=boards, max_pages=args.max_pages)

    elif args.target == "summarize":
        from src.processing.metadata import MetadataExtractor
        from src.llm.client import LLMClient
        import json
        import os
        from collections import defaultdict

        print(">>> [요약] 데이터를 분석하고 리포트를 생성합니다 (Local Ollama)...")
        
        # 1. 레코드 로드
        records = []
        records_path = settings.raw_records_dir / "records.jsonl"
        if records_path.exists():
            with open(records_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        records.append(json.loads(line))
                    except:
                        pass
        
        extractor = MetadataExtractor()
        
        # 데이터 그룹화 (Course ID 기준)
        courses_data = defaultdict(list)
        course_names = {}

        # 2. 레코드 처리 및 분류
        for rec in records:
            # 코스 정보 추출 (Record 태그나 페이로드 활용)
            cid = rec.get("payload", {}).get("course_id")
            if not cid:
                # 태그에서 추론 (canvas, COURSE_CODE)
                tags = rec.get("tags", [])
                if len(tags) >= 2 and tags[0] == "canvas":
                    # tags[1]이 보통 코스 코드. ID는 아님. 하지만 그룹핑 키로 사용 가능.
                    cid = tags[1]
            
            if not cid:
                cid = "common" # 공통/기타

            # 코스 이름 저장 (Category가 course인 경우)
            if rec.get("category") == "course":
                course_names[str(rec.get("payload", {}).get("id"))] = rec.get("title")
                course_names[cid] = rec.get("title") # 코드 매핑 시도

            meta = extractor.summarize_record(rec)
            if meta["title"] and meta["title"] != "No Title":
                courses_data[cid].append(meta)

        # 3. 파일 처리
        files_root = settings.files_dir
        if files_root.exists():
            # files_dir 구조: data/files/{course_id}/...
            for course_dir in files_root.iterdir():
                if course_dir.is_dir():
                    cid = course_dir.name
                    for fpath in course_dir.rglob("*"):
                        if fpath.is_file() and fpath.suffix.lower() in [".pdf", ".pptx", ".docx"]:
                            text = extractor.extract_text_from_file(fpath)
                            if text:
                                courses_data[cid].append({
                                    "category": "file",
                                    "title": fpath.name,
                                    "content_summary": text[:500], # 로컬 모델 토큰 절약
                                    "path": str(fpath),
                                    "date": "File Found"
                                })

        # 4. LLM 호출 (과목별 순차 실행)
        client = LLMClient(model="gpt-oss") # 사용자 지정 모델
        full_report = "# 🎓 학사 요약 리포트 (by Ollama)\n\n"
        
        sorted_courses = sorted(courses_data.keys())
        total_courses = len(sorted_courses)
        
        for idx, cid in enumerate(sorted_courses, 1):
            items = courses_data[cid]
            if not items:
                continue
                
            c_name = course_names.get(cid, cid)
            if c_name == "common": c_name = "📢 일반 공지 / 기타"
            
            print(f"[{idx}/{total_courses}] '{c_name}' 요약 생성 중... ({len(items)} 항목)")
            
            result = client.generate_course_report(str(c_name), items)
            
            # JSON 결과에서 요약본만 추출하여 출력
            summary_text = result.get("summary", "요약 없음")
            dt_stats = f"Deadlines: {len(result.get('deadlines', []))}, Notices: {len(result.get('announcements', []))}"
            
            full_report += f"## {c_name}\n\n{summary_text}\n\n*({dt_stats})*\n\n---\n\n"

        out_file = "report.md"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(full_report)
        
        print(f"\n✅ 리포트 생성 완료: {out_file}")

    else:
        parser.error("알 수 없는 대상입니다.")


if __name__ == "__main__":
    main()
