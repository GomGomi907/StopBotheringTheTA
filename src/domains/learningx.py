import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from playwright.async_api import async_playwright, BrowserContext, Response

try:
    from .learningx_utils import _download_file_logic, _resolve_generic_download_url
except ImportError:
    # If utils not found, define dummy or fail
    pass

MODULE_PATTERN = re.compile(r"/learningx/lti/lecture_attendance/items/view/(\d+)")

async def _resolve_clms_viewer_url(context: BrowserContext, viewer_url: str) -> Optional[str]:
    """CLMS 뷰어 URL(예: .../em/...)에서 실제 파일 다운로드 URL을 추출"""
    try:
        # 1. 뷰어 페이지 HTML 가져오기
        resp = await context.request.get(viewer_url)
        if resp.status != 200:
            print(f"  [LX] CLMS 뷰어 접근 실패: {resp.status}")
            return None
            
        html = await resp.text()
        
        # 2. iframe src 추출 (JavaScript 내)
        # 예: download_iframe.attr('src', "https://clms.dankook.ac.kr/index.php?module=dispXn_media_content2013DownloadContent&content_id=68c760274dbdf")
        m = re.search(r"download_iframe\.attr\('src',\s*\"([^\"]+)\"\)", html)
        if m:
            real_url = m.group(1)
            # &amp; 디코딩 필요할 수 있음
            real_url = real_url.replace("&amp;", "&")
            print(f"  [LX] CLMS 실제 다운로드 링크 발견: {real_url}")
            return real_url
            
        return None
    except Exception as e:
        print(f"  [LX] CLMS 파싱 오류: {e}")
        return None


async def _find_hidden_file_in_frames(page) -> Optional[str]:
    """[Deep Crawling] 모든 프레임을 순회하며 본문(Smart Editor 등) 내 숨겨진 파일 링크를 찾는다."""
    for frame in page.frames:
        try:
            # 1. 'file/down' 패턴 (LearningX 공통)
            # <a href=".../file/down/..." ...>
            # 정규식으로 href 추출
            content = await frame.content()
            # href="..." 패턴 찾기 (단순화)
            # 좀 더 정교하게: a 태그 내의 href
            links = re.findall(r'href=["\']([^"\']+)["\']', content)
            for link in links:
                # LearningX 파일 다운로드 패턴
                if "/file/down/" in link:
                     # 절대 경로 변환 필요하면? 보통 http 포함됨.
                     return link.replace("&amp;", "&")
                
                # 일반 파일 확장자
                lower = link.lower()
                if any(lower.endswith(ext) for ext in [".pdf", ".zip", ".hwp", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"]):
                    # javascript: 나 # 제외
                    if "javascript" not in lower and "#" not in lower:
                         return link
        except:
            pass
    return None


def load_cookies(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return json.load(path.open("r", encoding="utf-8"))


def format_cookies_for_playwright(cookies_raw: List[dict]) -> List[dict]:
    return [
        {
            "name": c["name"],
            "value": c["value"],
            "domain": c["domain"].lstrip("."),
            "path": c.get("path", "/"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", False),
        }
        for c in cookies_raw
    ]


async def fetch_module_items(context: BrowserContext, base_url: str, cid: int) -> List[Dict]:
    """Canvas Modules API로부터 learningx external_url과 item_id를 찾는다 (Playwright APIRequestContext 사용)."""
    items: List[Dict] = []
    url = f"{base_url}/api/v1/courses/{cid}/modules"
    params = {"include[]": "items", "per_page": "50"}
    
    # 1. Modules 순회
    while url:
        try:
            resp = await context.request.get(url, params=params)
            if resp.status != 200:
                print(f"[WARN] modules 요청 실패: {url} status={resp.status}")
                break
                
            text = await resp.text()
            text = text.lstrip()
            if text.startswith("while(1);"):
                text = text[len("while(1);") :]
            
            data = json.loads(text)
        except Exception as e:
            print(f"[WARN] modules 파싱/요청 실패: {url} error={e}")
            break

        for module in data:
            for item in module.get("items", []) or []:
                external = item.get("external_url") or ""
                i_type = item.get("type")
                
                # 1. LearningX View
                m_lx = re.search(r"/learningx/lti/lecture_attendance/items/view/(\d+)", external)
                # 2. Generic External Tool (Commons, Viewer, etc)
                m_tool = re.search(r"/external_tools/(\d+)", external)
                
                if m_lx:
                    items.append({
                        "type": "learningx",
                        "url": external,
                        "id": int(m_lx.group(1)),
                        "module_item_id": item.get("id"),
                        "title": item.get("title")
                    })
                elif m_tool or i_type == "ExternalTool":
                    # ID 추출 실패 시, 아이템 ID 사용
                    tool_id = int(m_tool.group(1)) if m_tool else item.get("id")
                    
                    # URL이 비어있으면(ExternalTool인데 null) 모듈 아이템 URL 사용 -> 나중에 클릭 시 redirect 됨
                    target_url = external if external else f"{base_url}/courses/{cid}/modules/items/{item.get('id')}"

                    items.append({
                        "type": "generic_lti",
                        "url": target_url,
                        "id": tool_id,
                        "module_item_id": item.get("id"),
                        "title": item.get("title")
                    })
        
        link = resp.headers.get("link")
        next_url = None
        if link:
            parts = link.split(",")
            for p in parts:
                seg = p.split(";")
                if len(seg) < 2:
                    continue
                if 'rel="next"' in seg[1]:
                    next_url = seg[0].strip(" <>")
        
        if not next_url:
            break
            
        url = next_url
        params = None

    # 2. Tabs(사이드바) 순회 - Modules에 없는 외부 도구(강의자료실 등) 탐색
    try:
        tab_url = f"{base_url}/api/v1/courses/{cid}/tabs"
        t_resp = await context.request.get(tab_url, params={"per_page": "50"})
        if t_resp.status == 200:
            t_text = await t_resp.text()
            if t_text.strip().startswith("while(1);"): t_text = t_text.strip()[9:]
            tabs_data = json.loads(t_text)
            
            for tab in tabs_data:
                tid = tab.get("id")
                t_label = tab.get("label")
                # Skip standard tabs
                if tid in ["home", "announcements", "assignments", "modules", "files", "grades", "people", "pages", "discussions", "quizzes", "syllabus", "outcomes", "conferences", "collaborations", "settings"]:
                    continue
                
                t_url = tab.get("html_url", "")
                is_ext = (tab.get("type") == "external") or ("external_tools" in t_url)
                
                if is_ext and t_url:
                    # 중복 방지 (이미 Modules에서 수집된 URL인지 확인)
                    # 완벽하진 않지만 URL 포함 여부로 체크
                    if not any(it["url"] == t_url for it in items):
                         # ID 추출
                        m_tid = re.search(r"/external_tools/(\d+)", t_url)
                        real_id = int(m_tid.group(1)) if m_tid else 999999
                        
                        items.append({
                            "type": "generic_lti",
                            "url": t_url, # 탭 클릭 시 이동할 URL
                            "id": real_id,
                            "module_item_id": f"tab_{tid}", # 가상 모듈 ID
                            "title": t_label
                        })
                        print(f"  [Tab] 외부 도구 탭 추가: {t_label}")
    except Exception as e:
        print(f"  [Warn] 탭 목록 추가 수집 실패: {e}")

    # 3. LearningX Native API (Hidden Items)
    lx_items = await fetch_learningx_native_modules(context, base_url, cid)
    
    # 중복 제거 후 합치기
    existing_ids = {str(i["id"]) for i in items} # mix of int/str
    count_new = 0
    for lxi in lx_items:
        # LearningX ID 기준 중복 체크 (Canvas 모듈에서 이미 수집된 LearningX 아이템과 겹칠 수 있음)
        if str(lxi["id"]) not in existing_ids:
            items.append(lxi)
            existing_ids.add(str(lxi["id"]))
            count_new += 1
            
    if count_new > 0:
        print(f"  [LX-Native] Canvas에 없는 히든 아이템 {count_new}개 Merged")

    return items

async def fetch_learningx_native_modules(context: BrowserContext, base_url: str, cid: int) -> List[Dict]:
    """LearningX 자체 API를 통해 Canvas API보다 더 정확한 파일/아이템 정보를 가져옵니다."""
    items = []
    # LearningX Main API Endpoint
    # 보통 /learningx/api/v1/courses/{course_id}/modules 혹은 /learningx/api/v1/courses/{course_id}/all_components_db 사용
    api_url = f"{base_url}/learningx/api/v1/courses/{cid}/modules"
    
    print(f"  [LX-Native] API 요청 시도: {api_url}")
    
    try:
        # 1. 기본 요청 (쿠키 사용)
        resp = await context.request.get(api_url)
        
        if resp.status != 200:
            print(f"  [LX-Native] 1차 요청 실패: Status {resp.status}")
            # 2. Authorization 헤더 추가 시도 (xn_api_token)
            cookies = await context.cookies()
            token = next((c["value"] for c in cookies if c["name"] == "xn_api_token"), None)
            if token:
                print(f"  [LX-Native] xn_api_token 발견, Bearer 인증 시도")
                resp = await context.request.get(api_url, headers={"Authorization": f"Bearer {token}"})
        
        if resp.status == 200:
            data = await resp.json()
            # 구조: [ { "module_id": ..., "items": [ { "item_id": ..., "title": ..., "item_type": ... } ] } ]
            # 또는 바로 리스트일 수 있음. LearningX 버전마다 다름.
            
            # 만약 data가 dict라면 (오류 메시지 등)
            if isinstance(data, dict) and "items" not in data and "module_id" not in data:
                 # maybe wrapped in "data"?
                 pass

            # 리스트라고 가정하고 순회
            if isinstance(data, list):
                for mod in data:
                    # 'items' 대신 'module_items'가 올바른 키일 확률 높음 (디버깅 결과)
                    raw_items = mod.get("module_items", []) or mod.get("items", [])
                    
                    for item in raw_items:
                        title = item.get("title", "Unknown")
                        item_id = item.get("module_item_id") or item.get("item_id")
                        
                        # 1. View URL 추출 (여기에 진짜 LX ID가 있음)
                        view_url = item.get("view_url")
                        if not view_url:
                            # content_data 내부에 있을 수 있음
                             cdata = item.get("content_data", {})
                             if isinstance(cdata, dict):
                                 view_url = cdata.get("view_url")
                        
                        # 아이디 추출
                        lx_id = None
                        if view_url:
                            # .../view/12345 형태에서 12345 추출
                            m_id = re.search(r"view/(\d+)", view_url)
                            if m_id:
                                lx_id = int(m_id.group(1))
                        
                        # view_url이 없으면 module_item_id라도 사용 (불완전할 수 있음)
                        if not lx_id and item_id:
                            lx_id = item_id
                            # 가상 URL 생성
                            view_url = f"{base_url}/learningx/lti/lecture_attendance/items/view/{lx_id}"

                        if lx_id:
                            # 기존 로직과 호환되도록 구성
                            items.append({
                                "type": "learningx",
                                "url": view_url,
                                "id": lx_id,
                                "module_item_id": f"lx_{lx_id}", 
                                "title": title
                            })
                            
                print(f"  [LX-Native] LearningX API에서 {len(items)}개 아이템 성공적으로 로드 완료")
            else:
                print(f"  [LX-Native] 응답 포맷 불일치: {str(data)[:200]}")
        else:
            print(f"  [LX-Native] 요청 최종 실패: Status {resp.status}, Body={await resp.text()}")

    except Exception as e:
        print(f"  [LX-Native] 치명적 오류: {e}")
        
    return items

async def capture_attendance_data(context: BrowserContext, target_url: str, learningx_item_id: int, timeout: float = 15000) -> Dict:
    """Canvas 모듈 아이템 페이지로 이동하여 LTI 로딩 후 attendance_items 응답을 캡처."""
    page = await context.new_page()
    captured_data = {}

    def predicate(response: Response):
        # 디버깅: 모든 attendance_items 관련 응답 로깅
        if "/attendance_items/" in response.url:
            print(f"  [LX-Capture] 감지된 URL: {response.url} (Method: {response.request.method}, Status: {response.status})")
        
        # LearningX API 응답 확인 (GET/POST 모두 허용, ID 체크 완화)
        # ID가 URL에 포함되지 않을 수도 있으므로, attendance_items 경로와 200 OK만 확인
        return (
            "/attendance_items/" in response.url 
            and response.status == 200
        )

    try:
        # expect_response는 컨텍스트 매니저로 사용하여, 내부 블록(goto) 실행 중에 발생하는 요청을 기다려야 함
        async with page.expect_response(predicate, timeout=timeout) as response_info:
            await page.goto(target_url)
        
        response = await response_info.value
        try:
            captured_data = await response.json()
            print(f"  [LX-Capture] Data Captured! Keys: {list(captured_data.keys())}")
            icd = captured_data.get("item_content_data")
            if icd:
                # print(f"  [LX-Capture] item_content_data: {json.dumps(icd, ensure_ascii=False)[:300]}...")
                pass
            else:
                print(f"  [LX-Capture] items_content_data MISSING in {captured_data.keys()}")
        except Exception as json_err:
            print(f"[WARN] JSON 파싱 실패: {target_url} error={json_err}")
            try:
                 text = await response.text()
                 print(f"  [LX-Capture] Response Text: {text[:500]}")
            except: pass
            raise json_err

    except Exception as e:
        if "Timeout" in str(e):
            print(f"  [LX-Capture] Timeout ({timeout}ms) exceeded for {target_url}")
            raise TimeoutError("LTI Capture Timeout")
        print(f"[WARN] attendance_data 캡처 실패: {target_url} error={e}")
    finally:
        await page.close()

    return captured_data


async def download_learningx_files(
    base_url: str,
    course_ids: List[int],
    cookies_path: Path,
    files_dir: Path,
    raw_dir: Path,
    user_data_dir: Optional[Path] = None,
    headless: bool = True,
) -> None:
    cookies_raw = load_cookies(cookies_path)
    cookies_pw = format_cookies_for_playwright(cookies_raw)
    
    async with async_playwright() as p:
        browser = None
        context = None
        
        if user_data_dir:
            print(f"[INFO] 브라우저를 실행합니다. 로그인이 필요하면 로그인해주세요.")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
            )
            await context.add_cookies(cookies_pw)
        else:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            await context.add_cookies(cookies_pw)

        for cid in course_ids:
            timeout_ms = 15000 # 코스별 초기 타임아웃 15초
            consecutive_timeouts = 0 # 연속 타임아웃 카운터
            print(f"[INFO] 코스 {cid} 처리 중...")
            items = await fetch_module_items(context, base_url, cid)
            if not items:
                print(f"[INFO] 코스 {cid}: 다운로드할 LearningX 항목 없음")
                continue
            
            print(f"[INFO] 코스 {cid}: {len(items)}개 항목 발견")
            
            course_dir = files_dir / str(cid)
            course_dir.mkdir(parents=True, exist_ok=True)
            summary_path = raw_dir / f"learningx_{cid}.jsonl"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            
            with summary_path.open("a", encoding="utf-8") as summary:
                for item_info in items:
                    item_type = item_info["type"]
                    external_url = item_info["url"]
                    module_item_id = item_info["module_item_id"]
                    
                    # Canvas 모듈 아이템 URL 구성
                    target_url = f"{base_url}/courses/{cid}/modules/items/{module_item_id}"
                    
                    local_path = None
                    file_data = None
                    
                    # === Case A: Standard LearningX (Attendance/Viewer) ===
                    if item_type == "learningx":
                        lx_id = item_info["id"]
                        await asyncio.sleep(1) # 부하 조절
                        
                        try:
                            data = await capture_attendance_data(context, target_url, lx_id, timeout=timeout_ms)
                            consecutive_timeouts = 0 # 성공 시 카운터 리셋
                        except TimeoutError:
                             consecutive_timeouts += 1
                             print(f"  [LX] Timeout 발생! (연속 {consecutive_timeouts}회) -> Fast Mode(2000ms)")
                             timeout_ms = 2000
                             if consecutive_timeouts >= 2:
                                 print(f"  [LX] 연속 2회 타임아웃으로 해당 과목({cid}) 처리를 중단합니다.")
                                 break
                             continue
                        except Exception:
                             continue

                        if not data: continue

                        item_content = (data or {}).get("item_content_data") or {}
                        view_url = item_content.get("view_url")
                        download_url = item_content.get("download_url") or item_content.get("file_url")
                        file_name = item_content.get("file_name")
                        content_type = item_content.get("content_type", "").lower()

                        if "mp4" in content_type or "video" in content_type:
                            print(f"  [Info] 비디오 파일 발견: {item_content.get('title')} (다운로드 시도 중...)")
                            target_download_url = download_url if download_url else view_url
                        else:
                            target_download_url = download_url if download_url else view_url

                        # [Fix] CLMS Viewer URL 처리 (/em/ 패턴)
                        if target_download_url and "/em/" in target_download_url and "clms.dankook.ac.kr" in target_download_url:
                            resolved = await _resolve_clms_viewer_url(context, target_download_url)
                            if resolved:
                                target_download_url = resolved
                        
                        # (기존 LearningX 다운로드 로직 수행)
                        if target_download_url and file_name:
                             local_path = await _download_file_logic(context, course_dir, file_name, target_download_url)
                        
                        file_data = data
                    
                    # === Case B: Generic LTI (Commons, External Tool) ===
                    elif item_type == "generic_lti":
                        print(f"  [LTI] 외부 도구 다운로드 시도: {item_info['title']}")
                        page = await context.new_page()
                        try:
                            # 1. 페이지 이동
                            await page.goto(target_url)
                            await page.wait_for_load_state("networkidle", timeout=15000)
                            
                            # [NEW] LearningX 프레임 감지 (숨겨진 LearningX 아이템)
                            lx_hidden_id = None
                            lx_hidden_url = None
                            
                            for frame in page.frames:
                                m_hidden = re.search(r"/learningx/lti/lecture_attendance/items/view/(\d+)", frame.url)
                                if m_hidden:
                                    lx_hidden_id = int(m_hidden.group(1))
                                    lx_hidden_url = frame.url
                                    break
                            
                            # LearningX 프레임이 발견되면 -> Case A 로직으로 전환
                            if lx_hidden_id:
                                print(f"  [LTI] 숨겨진 LearningX 뷰어 감지! (ID: {lx_hidden_id}) -> API 캡처 모드 전환")
                                # 현재 페이지 닫고, 해당 프레임 URL로 직접 접근하거나 캡처 수행
                                # capture_attendance_data는 새 페이지를 여는 함수이므로 현재 페이지 닫기 전엔 호출 X or 새 컨텍스트?
                                # capture_attendance_data가 context.new_page()를 하므로 안전함.
                                await page.close() # 기존 탐색 페이지 닫기
                                
                                try:
                                    data = await capture_attendance_data(context, lx_hidden_url, lx_hidden_id, timeout=timeout_ms)
                                    consecutive_timeouts = 0 # 성공 시 초기화
                                except TimeoutError:
                                    consecutive_timeouts += 1
                                    print(f"  [LX] Timeout 발생! (연속 {consecutive_timeouts}회) -> Fast Mode(2000ms)")
                                    timeout_ms = 2000
                                    if consecutive_timeouts >= 2:
                                        print(f"  [LX] 연속 2회 타임아웃으로 해당 과목({cid}) 처리를 중단합니다.")
                                        break
                                    continue
                                except Exception:
                                    continue
                                if data:
                                    item_content = (data or {}).get("item_content_data") or {}
                                    view_url = item_content.get("view_url")
                                    download_url = item_content.get("download_url") or item_content.get("file_url")
                                    file_name = item_content.get("file_name")
                                    
                                    # 비디오 스킵 등 동일 로직
                                    # ... (Case A와 코드 중복이지만 인라인 처리)
                                    target_download_url = download_url if download_url else view_url
                                    if target_download_url and file_name:
                                         local_path = await _download_file_logic(context, course_dir, file_name, target_download_url)
                                    file_data = data
                                else:
                                    print("  [LTI-LX] API 캡처 실패")
                                    # 실패 시 다시 page 열고 버튼 클릭 시도? 아니면 그냥 실패 처리.
                                    # LearningX 뷰어라면 버튼이 없을 확률 99%
                                
                                # 루프의 나머지(버튼 클릭) 건너뛰기
                                # summary 저장은 공통이므로 continue하면 안됨. summary 블록으로 점프 필요.
                                # 그러나 구조상 if/else가 나을 듯.
                            
                            else:
                                # 기존 Generic LTI 로직 (버튼 클릭)
                                try:
                                    async with page.expect_download(timeout=5000) as download_info:
                                        found_btn = False
                                        
                                        # iframe 내부도 검색
                                        frames = page.frames
                                        for frame in frames:
                                            # 버튼 찾기
                                            for sel in ["text=다운로드", "text=Download", "button.btn-download", "a[class*='download']", "a[href*='download']"]:
                                                if await frame.is_visible(sel):
                                                    await frame.click(sel)
                                                    found_btn = True
                                                    break
                                            if found_btn: break
                                        
                                        if not found_btn:
                                            # 메인 프레임 검색
                                            for sel in ["text=다운로드", "text=Download", "button.btn-download", "a[class*='download']", "a[href*='download']"]:
                                                if await page.is_visible(sel):
                                                    await page.click(sel)
                                                    found_btn = True
                                                    break
                                    
                                    if found_btn:
                                        download = await download_info.value
                                        fname = download.suggested_filename
                                        dest = course_dir / fname
                                        await download.save_as(dest)
                                        local_path = str(dest)
                                        print(f"  [LTI] 버튼 클릭 다운로드 성공: {fname}")
                                except:
                                    # 버튼 클릭 실패 시, 링크 추출 시도
                                    pass

                                if not local_path:
                                    # [Deep Crawling] 2. Smart Editor 숨겨진 파일 링크 탐색
                                    print("  [LTI] 버튼 미발견 -> 숨겨진 파일 링크 탐색 시도")
                                    hidden_link = await _find_hidden_file_in_frames(page)
                                    if hidden_link:
                                        print(f"  [Deep] 숨겨진 파일 링크 발견: {hidden_link}")
                                        # 다운로드 시도
                                        local_path = await _download_file_logic(context, course_dir, f"smart_file_{item_info['id']}.dat", hidden_link)

                                if not local_path:
                                    # 3. 링크 URL 추출 시도 (기존 로직 재활용)
                                    # 현재 페이지 URL이 곧 뷰어일 수 있음
                                    current_url = page.url
                                    real_link = await _resolve_generic_download_url(context, current_url)
            
                                    # iframe 내 URL도 체크
                                    if not real_link:
                                        for frame in page.frames:
                                             try:
                                                real_link = await _resolve_generic_download_url(context, frame.url)
                                                if real_link: break
                                             except: pass

                                    if real_link:
                                        print(f"  [LTI] 링크 추출 성공: {real_link}")
                                        local_path = await _download_file_logic(context, course_dir, f"download_{item_info['id']}.dat", real_link) # 이름 모름
                                
                                await page.close()
                                
                        except Exception as e:
                            print(f"  [LTI] 처리 실패: {e}")
                            try: await page.close()
                            except: pass

                    # Summary 기록
                    summary.write(
                        json.dumps(
                            {
                                "course_id": cid,
                                "external_url": external_url,
                                "module_item_id": module_item_id,
                                "title": item_info.get("title"),
                                "local_path": local_path,
                                "data": file_data,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
        
        print("[INFO] 모든 작업 완료. 브라우저를 종료합니다.")
        await context.close()
        if browser:
            await browser.close()



