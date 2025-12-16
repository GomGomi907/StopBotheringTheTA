import asyncio
import sys

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import json
from pathlib import Path
from typing import Optional, Dict, List

from playwright.async_api import async_playwright, Page

SECRETS_PATH = Path("data/secrets.json")


def load_secrets() -> Dict[str, str]:
    if not SECRETS_PATH.exists():
        return {}
    try:
        return json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_secrets(secrets: Dict[str, str]) -> None:
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_PATH.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")


async def try_auto_login(page: Page, secrets: Dict[str, str]) -> None:
    """저장된 ID/PW로 자동 입력을 시도한다."""
    username = secrets.get("username")
    password = secrets.get("password")
    
    if not username or not password:
        return

    print(">>> [자동 로그인] 로그인 폼을 찾는 중...")
    
    # 일반적인 ID/PW 입력 필드 선택자 후보
    id_selectors = [
        "#user_id", "input[name='user_id']", # 단국대 포털
        "input[name='id']", "input[name='userId']", "input[name='username']", 
        "#id", "#userId", "#username", 
        "input[placeholder*='아이디']", "input[placeholder*='ID']"
    ]
    pw_selectors = [
        "#user_password", "input[name='user_password']", # 단국대 포털
        "input[name='password']", "input[name='userPw']", "input[name='pw']",
        "#password", "#userPw", "#pw",
        "input[placeholder*='비밀번호']", "input[placeholder*='Password']"
    ]

    try:
        # ID 입력
        for sel in id_selectors:
            if await page.is_visible(sel):
                await page.fill(sel, username)
                print(f"  - ID 입력 완료 ({sel})")
                break
        
        # PW 입력
        for sel in pw_selectors:
            if await page.is_visible(sel):
                await page.fill(sel, password)
                print(f"  - PW 입력 완료 ({sel})")
                break
        
        # 로그인 버튼 클릭 시도
        submit_selectors = [".login_btn button", "#btnLogin", ".btn_login", "button[type='submit']", "input[type='submit']"]
        for sel in submit_selectors:
            if await page.is_visible(sel):
                await page.click(sel)
                print(f"  - 로그인 버튼 클릭 ({sel})")
                break

    except Exception as e:
        print(f"  - 자동 입력 중 오류 발생: {e}")


async def collect_cookies(
    name: str,
    url: str,
    out_path: Path,
    user_data_dir: Optional[Path],
    headless: bool = False,
    credentials: Optional[Dict[str, str]] = None,
) -> None:
    """브라우저를 띄워 로그인 후 쿠키를 덤프한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if user_data_dir:
        user_data_dir.mkdir(parents=True, exist_ok=True)

    # 자격 증명 우선순위: 인자 > 저장된 Secrets > 입력
    secrets = load_secrets()
    if credentials:
        secrets.update(credentials)
    
    # 헤드리스 모드인데 계정 정보가 없으면 진행 불가
    if headless and (not secrets.get("username") or not secrets.get("password")):
        print(f"[{name}] 헤드리스 모드: 자격 증명이 없어 중단합니다.")
        return

    # 수동 모드면 입력 요청
    if not headless and (not secrets.get("username") or not secrets.get("password")):
        print(f"\n[{name}] 자동 로그인을 위한 정보가 없습니다.")
        u = input("아이디(ID): ").strip()
        p = input("비밀번호(PW): ").strip()
        if u and p:
            secrets["username"] = u
            secrets["password"] = p
            save = input("이 정보를 저장하시겠습니까? (y/n): ").strip().lower()
            if save == "y":
                save_secrets(secrets)
                print("정보가 저장되었습니다.")

    # Settings의 UA와 일치시켜 세션 유효성 보장
    from src.config.settings import Settings
    ua = Settings.from_env().user_agent

    async with async_playwright() as p:
        if user_data_dir:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
                user_agent=ua,
            )
        else:
            _b = await p.chromium.launch(headless=headless)
            browser = await _b.new_context(user_agent=ua)
        
        page = await browser.new_page()
        try:
            await page.goto(url)
            
            # 자동 로그인 시도
            if secrets.get("username") and secrets.get("password"):
                await try_auto_login(page, secrets)

            if headless:
                # 헤드리스 모드에서는 로그인이 완료될 때까지 대기
                print(f"[{name}] 로그인 완료 대기 중... (최대 30초)")
                try:
                    # 로그인 성공 시 대시보드나 메인 화면으로 이동함
                    # URL이 'login'을 포함하지 않거나, 특정 요소가 뜰 때까지 대기
                    # 단국대 Canvas의 경우 로그인 성공 시 URL이 바뀜
                    await page.wait_for_function(
                        "() => !window.location.href.includes('login') && !window.location.href.includes('sso') && window.location.href.includes('canvas.dankook.ac.kr')",
                        timeout=30000
                    )
                    # 대시보드 로딩 확실히 대기 (전역 네비게이션 프로필 링크)
                    try:
                        await page.wait_for_selector("#global_nav_profile_link", timeout=10000)
                    except:
                        pass # 선택자가 다를 수 있으니 패스하지만, 위 URL 체크로 충분하길 기대
                    
                    # 쿠키 세팅 안정화 대기
                    await page.wait_for_timeout(5000)
                    print(f"[{name}] 로그인 성공! (URL: {page.url})")
                except Exception as e:
                    print(f"[{name}] 로그인 대기 시간 초과 또는 실패: {e}")
                    # 실패해도 쿠키는 저장해보지만 유효하지 않을 수 있음
            else:
                # 일반 모드: 사용자 확인 대기
                print(f"[{name}] 브라우저가 열렸습니다. 로그인 완료 후 터미널에서 Enter 키를 누르세요.")
                await asyncio.to_thread(input)
            
            cookies = await browser.cookies()
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"[{name}] 쿠키 저장 완료 → {out_path}")
            
        except Exception as e:
            print(f"[{name}] 오류 발생: {e}")
        finally:
            await browser.close()


async def run_choice(choice: str) -> None:
    if choice == "1":
        await collect_cookies(
            name="포털",
            url="https://portal.dankook.ac.kr/p/CTT006",
            out_path=Path("data/cookies_portal.json"),
            user_data_dir=Path("data/userdata_portal"),
        )
    elif choice == "2":
        await collect_cookies(
            name="캔버스",
            url="https://canvas.dankook.ac.kr/",
            out_path=Path("data/cookies_canvas.json"),
            user_data_dir=Path("data/userdata_canvas"),
        )
    elif choice == "3":
        await run_choice("1")
        await run_choice("2")
    else:
        print("유효하지 않은 선택입니다.")


def menu() -> Optional[str]:
    print("\n=== 크롤러 로그인 세션 수집기 ===")
    print("1) 포털(학사/학과 공지) 쿠키 수집")
    print("2) 캔버스 쿠키 수집")
    print("3) 둘 다")
    print("q) 종료")
    return input("선택: ").strip().lower()


def main() -> None:
    try:
        while True:
            choice = menu()
            if choice == "q":
                break
            asyncio.run(run_choice(choice))
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
