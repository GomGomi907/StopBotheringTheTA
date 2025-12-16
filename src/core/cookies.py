import json
from pathlib import Path
from typing import Dict, List


def load_cookies(path: Path) -> Dict[str, str]:
    """Playwright가 덤프한 cookies.json을 httpx용 쿠키 dict로 변환."""
    if not path.exists():
        raise FileNotFoundError(f"쿠키 파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as f:
        cookies: List[dict] = json.load(f)
    return {c["name"]: c["value"] for c in cookies}

def verify_login_status(path: Path) -> bool:
    """쿠키 파일이 존재하고 유효한 포맷인지 확인합니다."""
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return isinstance(data, list) and len(data) > 0
    except:
        return False
