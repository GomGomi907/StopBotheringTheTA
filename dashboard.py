import streamlit as st
import asyncio
import sys

# [Fix] Windows에서 Playwright 사용 시 SelectorEventLoop 오류 해결을 위해 ProactorEventLoop 강제 설정
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import json
import logging
import time
from pathlib import Path
from datetime import datetime

from src.config.settings import Settings
from src.domains.canvas import CanvasCrawler
from src.records.writer import RecordWriter
from src.core.cookies import verify_login_status
from src.app import collect_cookies
from src.etl.structurer import DataStructurer
from src.ui.state import StateManager
from src.ui.views.home import render_home_view
from src.ui.views.timeline import render_timeline_view
from src.ui.views.chat import render_chat_view

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Smart Academic Dashboard 2.0",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Session State & Init ---
# 학기 설정 파일 경로
SEMESTER_CONFIG_PATH = Path("data/current_semester.txt")

def _load_saved_semester() -> str:
    """저장된 학기 로드 (파일 없으면 기본값)"""
    if SEMESTER_CONFIG_PATH.exists():
        try:
            return SEMESTER_CONFIG_PATH.read_text(encoding="utf-8").strip()
        except:
            pass
    return Settings.from_env().current_semester

def _save_semester(semester: str):
    """학기 설정 저장"""
    try:
        SEMESTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEMESTER_CONFIG_PATH.write_text(semester, encoding="utf-8")
    except:
        pass

if "structured_data" not in st.session_state:
    st.session_state["structured_data"] = []
if "last_updated" not in st.session_state:
    st.session_state["last_updated"] = None
if "current_semester" not in st.session_state:
    # 저장된 학기 로드 (또는 기본값)
    st.session_state["current_semester"] = _load_saved_semester()

# Initialize State Manager
state_manager = StateManager()

# --- Helpers ---
def get_current_settings() -> Settings:
    """현재 학기 설정을 반영한 Settings 반환"""
    base_settings = Settings.from_env()
    return base_settings.with_semester(st.session_state["current_semester"])

def load_db():
    """Load structured DB (학기별 경로)"""
    settings = get_current_settings()
    db_path = settings.structured_db_path
    
    if db_path.exists():
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                
            # [Fix] Robust Type Check
            if not isinstance(raw_data, list):
                raw_data = [] # Should be a list
                
            # Deduplicate by original_id (Keep last occurrence)
            clean_map = {}
            for item in raw_data:
                if not isinstance(item, dict): continue # Filter invalid items
                
                oid = item.get("original_id")
                if oid:
                    clean_map[oid] = item
                else:
                    import uuid
                    clean_map[str(uuid.uuid4())] = item
            
            data = list(clean_map.values())
            
            st.session_state["structured_data"] = data
            st.session_state["last_updated"] = datetime.fromtimestamp(db_path.stat().st_mtime)
        except Exception as e:
             logger.error(f"Error loading structured_db.json: {e}")
             st.session_state["structured_data"] = []
    else:
        st.session_state["structured_data"] = []

def run_crawler_full(download_files: bool = False):
    """Run Robust Crawler"""
    with st.spinner("🚀 데이터 수집 중... (모든 데이터를 긁어옵니다)"):
        try:
            settings = get_current_settings()
            # 학기별 디렉토리 생성
            settings.raw_records_dir.mkdir(parents=True, exist_ok=True)
            
            writer = RecordWriter(
                base_path=settings.raw_records_dir,
                semester=settings.current_semester
            )
            crawler = CanvasCrawler(settings=settings, writer=writer, download_files=download_files)
            courses = crawler.crawl()
            
            if download_files:
                st.info("📂 파일 다운로드를 시작합니다... (시간이 소요됩니다)")
                
                # 1. Canvas Standard Files
                from src.domains.downloader import download_canvas_files
                st.markdown("**(1/2) Canvas 일반 파일 다운로드 중...**")
                asyncio.run(download_canvas_files(
                    base_url=settings.canvas_base_url or "https://canvas.dankook.ac.kr",
                    course_ids=[], 
                    cookies_path=Path("data/cookies_canvas.json"),
                    files_dir=settings.files_dir,
                    raw_dir=settings.raw_records_dir,
                    user_data_dir=None,
                    headless=True
                ))
                
                # 2. LearningX Deep Crawling
                st.markdown("**(2/2) LearningX 강의자료 정밀 탐색 중... (LTI/Video)**")
                from src.domains.learningx import download_learningx_files
                cids = [int(c["id"]) for c in courses if "id" in c]
                asyncio.run(download_learningx_files(
                    base_url=settings.canvas_base_url or "https://canvas.dankook.ac.kr",
                    course_ids=cids,
                    cookies_path=Path("data/cookies_canvas.json"),
                    files_dir=settings.files_dir,
                    raw_dir=settings.raw_records_dir,
                    user_data_dir=None,
                    headless=True
                ))
                st.success("📂 모든 강의자료 다운로드 완료!")
            
            st.success("데이터 수집 완료!")
        except Exception as e:
            # AuthenticationError 감지
            from src.domains.canvas import AuthenticationError
            if isinstance(e, AuthenticationError) or "401" in str(e) or "403" in str(e):
                st.error("🔐 **인증 오류**: 로그인이 만료되었습니다.")
                st.warning("👉 왼쪽 사이드바에서 **로그아웃** 후 다시 **로그인**해주세요.")
                # 쿠키 삭제 제안
                if st.button("🔄 쿠키 삭제 및 재로그인"):
                    try:
                        Path("data/cookies_canvas.json").unlink()
                        st.session_state["is_logged_in"] = False
                        st.rerun()
                    except:
                        pass
            else:
                st.error(f"크롤링 실패: {e}")

def run_etl_pipeline():
    """Run Rule-based ETL (Fast, No LLM)"""
    status_container = st.empty()
    progress_bar = st.empty()
    
    status_container.info("⚡ 데이터 정제 중... (Rule-based)")
    
    def _on_progress(processed, total):
        pct = processed / total
        status_container.markdown(f"### ⚡ 처리 중: **{processed}/{total}**")
        progress_bar.progress(pct)

    try:
        from src.etl.simple_structurer import SimpleStructurer
        current_semester = st.session_state.get("current_semester")
        structurer = SimpleStructurer(semester=current_semester)
        data = structurer.run(progress_callback=_on_progress)
        
        status_container.success(f"✨ 데이터 정제 완료! ({len(data)}개 항목)")
        progress_bar.empty()
        
        st.session_state["structured_data"] = data
        st.session_state["last_updated"] = datetime.now()
    except Exception as e:
        status_container.error(f"ETL 실패: {e}")
        progress_bar.empty()

def main():
    # --- Sidebar ---
    with st.sidebar:
        st.title("🎓 Control Center")
        
        # [Login UI]
        cookies_path = Path("data/cookies_canvas.json")
        is_logged_in = verify_login_status(cookies_path)
        
        if not is_logged_in:
            with st.expander("👤 로그인 (Login)", expanded=True):
                uid = st.text_input("ID", key="login_id")
                upw = st.text_input("PW", type="password", key="login_pw")
                if st.button("로그인"):
                    if uid and upw:
                        with st.spinner("로그인 중..."):
                            try:
                                asyncio.run(collect_cookies(
                                    name="Canvas",
                                    url="https://canvas.dankook.ac.kr",
                                    out_path=cookies_path,
                                    user_data_dir=None,
                                    credentials={"username": uid, "password": upw},
                                    headless=True
                                ))
                                st.success("성공! 새로고침.")
                                time.sleep(1)
                                st.rerun()
                            except Exception as e:
                                st.error(f"실패: {e}")
        else:
            st.success("✅ Logged In")
            if st.button("Logout"):
                try: cookies_path.unlink()
                except: pass
                st.rerun()

        st.divider()
        
        # [학기 선택 UI]
        st.subheader("📅 학기 설정")
        
        # 학기 옵션 생성 (미래 학기 제외, 내림차순)
        from datetime import datetime as dt
        now = dt.now()
        current_year = now.year
        current_month = now.month
        
        # 현재 시점까지의 학기만 포함
        def get_semester_order(sem: str) -> int:
            """학기 정렬을 위한 숫자 반환 (내림차순용)"""
            parts = sem.split("-")
            year = int(parts[0])
            period = parts[1] if len(parts) > 1 else "1"
            period_order = {"1": 1, "summer": 2, "2": 3, "winter": 4}
            return year * 10 + period_order.get(period, 0)
        
        def is_past_or_current_semester(sem: str) -> bool:
            """현재 또는 과거 학기인지 확인"""
            parts = sem.split("-")
            year = int(parts[0])
            period = parts[1] if len(parts) > 1 else "1"
            
            if year < current_year:
                return True
            elif year == current_year:
                # 현재 월 기준 판단
                if period == "1" and current_month >= 3:  # 1학기: 3-6월
                    return True
                elif period == "summer" and current_month >= 7:  # 여름: 7-8월
                    return True
                elif period == "2" and current_month >= 9:  # 2학기: 9-12월
                    return True
                elif period == "winter" and current_month >= 1:  # 겨울: 1-2월 (작년 winter도 해당)
                    return True
            return False
        
        semester_options = []
        for y in range(current_year - 3, current_year + 1):  # 과거 3년 ~ 현재
            for period in ["1", "summer", "2", "winter"]:
                sem = f"{y}-{period}"
                if is_past_or_current_semester(sem):
                    semester_options.append(sem)
        
        # 내림차순 정렬 (최신 학기가 위에)
        semester_options.sort(key=get_semester_order, reverse=True)
        
        # 현재 학기 인덱스 찾기
        current_sem = st.session_state["current_semester"]
        default_idx = semester_options.index(current_sem) if current_sem in semester_options else 0
        
        selected_semester = st.selectbox(
            "현재 학기",
            options=semester_options,
            index=default_idx,
            key="semester_select"
        )
        
        # 학기 변경 감지 및 데이터 유무 체크
        if selected_semester != st.session_state["current_semester"]:
            st.session_state["current_semester"] = selected_semester
            st.session_state["structured_data"] = []  # 데이터 초기화
            _save_semester(selected_semester)  # 파일에 저장 (새로고침 시에도 유지)
            st.rerun()
        
        # 해당 학기 데이터 유무 확인
        settings = get_current_settings()
        db_exists = settings.structured_db_path.exists()
        raw_exists = (settings.raw_records_dir / "records.jsonl").exists()
        
        if db_exists:
            st.success(f"✅ 데이터 있음")
            st.caption(f"경로: `{settings.semester_dir}`")
        elif raw_exists:
            st.warning("⚠️ Raw 데이터만 있음 (ETL 필요)")
            st.caption("'2. AI ETL' 버튼을 눌러 정제하세요.")
        else:
            st.error("❌ 데이터 없음")
            st.caption("'1. Crawl Data' 버튼을 눌러 수집하세요.")
        
        st.divider()
        dl_files = st.checkbox("Download Files (Slow)", value=False)
        if st.button("1. Crawl Data", type="primary"):
            if not is_logged_in: st.error("Login First!")
            else: run_crawler_full(download_files=dl_files)
            
        if st.button("2. AI ETL (Refine)"):
            run_etl_pipeline()
            
        st.divider()
        if st.button("🔄 Reload DB"):
            load_db()
            
        if st.session_state["last_updated"]:
            st.caption(f"Updated: {st.session_state['last_updated'].strftime('%m-%d %H:%M')}")

    # --- Main Navigation ---
    # Load data if empty
    if not st.session_state["structured_data"]:
        load_db()
    
    data = st.session_state["structured_data"]
    
    # Custom CSS for spacing
    # Custom CSS for spacing & Sticky Tabs
    st.markdown("""
        <style>
        /* Force Streamlit Header to lower Z-Index */
        header[data-testid="stHeader"] { z-index: 1 !important; }
        
        /* Ensure Main Container allows sticky elements */
        .block-container { 
            padding-top: 5rem; 
            padding-bottom: 2rem; 
            overflow: visible !important; 
        }
        
        /* Sticky Tabs - The "Always On Top" Fix */
        div[data-baseweb="tab-list"] {
            position: -webkit-sticky;
            position: sticky !important;
            top: 3.5rem !important; /* Fixed position below header */
            width: 100%;
            z-index: 999999 !important; /* Force visibility */
            background-color: var(--secondary-background-color, #0E1117); 
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); 
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 2rem;
            padding-right: 2rem;
            margin-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)

    # Tabs as Navigation
    tab_home, tab_timeline, tab_chat, tab_grad, tab_debug = st.tabs([
        "🏠 Home", "📅 Timeline", "🤖 AI Chat", "🎓 졸업요건", "🐞 Debug"
    ])
    
    # JS Enforcer for Fixed Tabs (The "Absolute" approach)
    import streamlit.components.v1 as components
    js_code = """
    <script>
    function forceFixed() {
        try {
            const tabs = window.parent.document.querySelector('div[data-baseweb="tab-list"]');
            const mainBlock = window.parent.document.querySelector('.block-container');
            
            if (tabs && mainBlock) {
                const rect = mainBlock.getBoundingClientRect();
                
                // Force Fixed Position matching the Main Block's geometry
                tabs.style.setProperty('position', 'fixed', 'important');
                tabs.style.setProperty('top', '3.75rem', 'important'); // Header height
                tabs.style.setProperty('left', rect.left + 'px', 'important'); // Sync Left
                tabs.style.setProperty('width', rect.width + 'px', 'important'); // Sync Width
                tabs.style.setProperty('z-index', '9999999', 'important');
                
                // Styling
                tabs.style.setProperty('background-color', 'var(--secondary-background-color, #0E1117)', 'important');
                tabs.style.setProperty('box-shadow', '0 4px 6px -1px rgba(0, 0, 0, 0.1)', 'important');
                tabs.style.setProperty('padding', '10px 20px', 'important');
                tabs.style.setProperty('border-radius', '0 0 8px 8px', 'important');
                
                // Adjust Main Container padding to prevent content hide
                mainBlock.style.setProperty('padding-top', '8rem', 'important'); 
            }
            
            // Lower Header Z-Index
            const header = window.parent.document.querySelector('header[data-testid="stHeader"]');
            if (header) {
                header.style.setProperty('z-index', '1', 'important');
            }
            
        } catch (e) {
            console.log("Fixed JS Error: " + e);
        }
    }
    // Run frequently (100ms) to handle resize/sidebar toggle smoothly
    setInterval(forceFixed, 100);
    </script>
    """
    components.html(js_code, height=0)

    with tab_home:
        if not data:
            st.info("데이터가 없습니다. 사이드바에서 수집/정제를 실행해주세요.")
        else:
            current_semester = st.session_state.get("current_semester")
            render_home_view(data, state_manager, semester=current_semester)
            
    with tab_timeline:
        if not data:
            st.info("데이터가 없습니다. 사이드바에서 수집/정제를 실행해주세요.")
        else:
            current_semester = st.session_state.get("current_semester")
            render_timeline_view(data, state_manager, semester=current_semester)
            
    with tab_chat:
        render_chat_view(data)
    
    with tab_grad:
        from src.ui.views.graduation import render_graduation_view
        render_graduation_view()
        
    with tab_debug:
        from src.ui.views.debug import render_debug_view
        render_debug_view()

if __name__ == "__main__":
    main()
