import asyncio
import json
import re
import urllib.parse
import cgi
from pathlib import Path
from typing import List, Optional, Set, Tuple

from playwright.async_api import async_playwright

from src.domains.learningx import load_cookies, format_cookies_for_playwright


def smart_decode_filename(filename: str) -> str:
    """
    파일명을 스마트하게 디코딩한다.
    1. URL 디코딩
    2. Latin-1으로 해석된 바이트를 UTF-8 -> CP949 순서로 복구 시도
    """
    if not filename:
        return ""
        
    # 1. URL unquote
    filename = urllib.parse.unquote(filename)
    
    # 2. 인코딩 복구 시도
    try:
        # Latin-1으로 다시 바이트 변환
        encoded_bytes = filename.encode("latin1")
    except (UnicodeEncodeError, UnicodeDecodeError):
        # 변환 실패(이미 Latin-1 범위를 벗어남) -> 원본 반환
        return filename

    # 3-1. UTF-8 시도 (가장 흔함)
    try:
        return encoded_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass
        
    # 3-2. CP949 (EUC-KR 확장) 시도
    try:
        return encoded_bytes.decode("cp949")
    except UnicodeDecodeError:
        pass

    # 4. 실패 시 원본 반환 (이미 올바른 경우 등)
    return filename


async def download_canvas_files(
    base_url: str,
    course_ids: List[int],
    cookies_path: Path,
    files_dir: Path,
    user_data_dir: Optional[Path] = None,
    raw_dir: Optional[Path] = None,
    headless: bool = True,
) -> None:
    """
    크롤링된 데이터(records.jsonl)에서 파일 링크를 추출하여 다운로드한다.
    1. 모듈 아이템(type='File') 명시적 파싱
    2. 본문(페이지, 공지 등) 내 임베디드 링크 정규식 추출
    """
    if not raw_dir:
        print("[WARN] [일반 파일] raw_dir이 지정되지 않아 파일 다운로드를 건너뜁니다.")
        return

    records_path = raw_dir / "records.jsonl"
    if not records_path.exists():
        print(f"[WARN] [일반 파일] {records_path}가 존재하지 않습니다.")
        return

    print(f"[INFO] [일반 파일] {records_path}에서 파일 링크 추출 중...")
    
    # (course_id, file_id) 튜플 저장
    # course_id가 명확하지 않으면 None
    unique_files = {}  # fid -> cid

    # 1. 정규식 패턴 (임베디드 링크용)
    pattern_course = re.compile(r'/courses/(\d+)/files/(\d+)')
    pattern_file = re.compile(r'/files/(\d+)')
    
    with open(records_path, encoding='utf-8') as f:
        for line in f:
            try:
                record = json.loads(line)
                category = record.get("category")
                payload = record.get("payload", {})
                
                # A. 모듈 아이템 명시적 파싱 (더 정확함)
                if category == "module":
                    # payload가 리스트일 수도 있고(페이지네이션 병합된 경우), 단일 객체일 수도 있음
                    # 현재 canvas.py 구조상 payload는 list[dict] 형태임 (modules 리스트)
                    modules = payload if isinstance(payload, list) else [payload]
                    for module in modules:
                        # 모듈 내 아이템 순회
                        for item in module.get("items", []) or []:
                            if item.get("type") == "File":
                                # API URL: .../api/v1/courses/:id/files/:fid
                                # item["url"] 필드 활용
                                url = item.get("url")  # API endpoint URL
                                if url:
                                    # URL에서 file_id 추출
                                    # 예: https://canvas.dankook.ac.kr/api/v1/courses/83491/files/4407865
                                    m = re.search(r'/files/(\d+)', url)
                                    if m:
                                        fid = m.group(1)
                                        # record["url"] 등에서 cid 추론 가능하나, 
                                        # module API 결과엔 course_id가 없을 수도 있음.
                                        # 하지만 context가 확실하므로 record의 url을 파싱하거나
                                        # 일단 None으로 두고 나중에 채움.
                                        # item["content_id"]가 file_id인 경우가 많음
                                        if fid not in unique_files:
                                            unique_files[fid] = None
                
                # B. 정규식 파싱 (공지사항, 페이지 본문 등)
                payload_str = json.dumps(payload, ensure_ascii=False)
                
                # /courses/:cid/files/:fid
                for m in pattern_course.findall(payload_str):
                    cid, fid = m
                    unique_files[fid] = cid
                
                # /files/:fid
                for m in pattern_file.findall(payload_str):
                    fid = m
                    if fid not in unique_files:
                        unique_files[fid] = None
                        
            except Exception:
                pass
                
    if not unique_files:
        print("[INFO] [일반 파일] 추출된 파일 링크가 없습니다.")
        return

    print(f"[INFO] [일반 파일] 총 {len(unique_files)}개의 고유 파일 ID 발견. 다운로드 시작...")

    cookies_raw = load_cookies(cookies_path)
    cookies_pw = format_cookies_for_playwright(cookies_raw)
    
    async with async_playwright() as p:
        context = None
        if user_data_dir:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
            )
            await context.add_cookies(cookies_pw)
        else:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            await context.add_cookies(cookies_pw)

        # 다운로드 진행
        for fid, cid_str in unique_files.items():
            # 안정성을 위해 3초 대기
            await asyncio.sleep(3)
            try:
                # 메타데이터 조회
                meta_url = f"{base_url}/api/v1/files/{fid}"
                filename = None
                download_url = None
                file_course_id = cid_str
                
                # 1. 메타데이터 요청
                try:
                    resp = await context.request.get(meta_url)
                    if resp.status == 200:
                        meta = await resp.json()
                        filename = meta.get("display_name") or meta.get("filename")
                        download_url = meta.get("url")
                        if meta.get("context_type") == "Course":
                            file_course_id = str(meta.get("context_id"))
                except Exception as e:
                    print(f"  [경고] 메타데이터 조회 실패(ID: {fid}): {e}")

                # 2. 다운로드 URL 폴백
                if not download_url:
                    if file_course_id:
                        download_url = f"{base_url}/courses/{file_course_id}/files/{fid}/download"
                    else:
                        download_url = f"{base_url}/files/{fid}/download"
                
                # 코스 ID 필터링 (사용자가 특정 코스만 원할 경우)
                if course_ids and file_course_id and int(file_course_id) not in course_ids:
                    continue
                
                target_dir = files_dir / str(file_course_id or "misc")
                target_dir.mkdir(parents=True, exist_ok=True)
                
                # 파일명 결정 (메타데이터가 없으면 임시 이름)
                if not filename:
                    filename = f"file_{fid}.bin"
                else:
                    # 메타데이터 파일명도 디코딩 처리
                    filename = smart_decode_filename(filename)

                # 파일 존재 여부 확인 (이름 기반)
                # 주의: safe_name 변환 전 로직이므로, 
                # 실제 저장된 파일명과 비교하려면 아래 로직에서 safe_name 처리 후 확인해야 함.
                
                print(f"  [다운로드 시도] {filename} (ID: {fid}) ...")
                file_resp = await context.request.get(download_url)
                
                if file_resp.status == 200:
                    # Content-Type 확인 (HTML 에러 페이지 방지)
                    content_type = file_resp.headers.get("content-type", "").lower()
                    if "text/html" in content_type:
                        print(f"  [에러] {filename} 다운로드 실패: 바이너리가 아닌 HTML 응답입니다. (로그인 만료 가능성)")
                        continue

                    # Content-Disposition 헤더 확인
                    content_disp = file_resp.headers.get("content-disposition")
                    if content_disp:
                        _, params = cgi.parse_header(content_disp)
                        if "filename*" in params:
                            fname = params["filename*"].split("''")[-1]
                            filename = smart_decode_filename(fname)
                        elif "filename" in params:
                            filename = smart_decode_filename(params["filename"])
                    
                    # 파일명 안전하게 처리
                    safe_name = "".join(c for c in filename if c.isalnum() or c in (' ', '.', '_', '-', '[', ']', '(', ')', '가-힣')).strip()
                    if not safe_name:
                        safe_name = f"file_{fid}.bin"
                        
                    dest_path = target_dir / safe_name
                    
                    if dest_path.exists():
                        print(f"  [스킵] 이미 존재함: {safe_name}")
                        continue
                        
                    body = await file_resp.body()
                    if len(body) < 1000 and b"<html" in body[:500].lower():
                         print(f"  [에러] {safe_name} 내용이 HTML로 의심됩니다. 저장을 건너뜁니다.")
                         continue

                    with open(dest_path, "wb") as f:
                        f.write(body)
                    print(f"  [완료] {safe_name}")
                else:
                    print(f"  [실패] {filename} status={file_resp.status}")
                    
            except Exception as e:
                print(f"  [에러] 파일(ID: {fid}) 처리 중 에러: {e}")

        print("[INFO] [일반 파일] 모든 작업 완료.")
        await context.close()

