import re
from pathlib import Path
from typing import Optional
from playwright.async_api import BrowserContext

async def _resolve_viewer_pdf(context: BrowserContext, viewer_url: str) -> Optional[str]:
    """
    LearningX PDF 뷰어 페이지에서 실제 PDF 파일(original.pdf) URL을 추출한다.
    og:image 메타 태그의 경로를 기반으로 추론한다.
    """
    try:
        resp = await context.request.get(viewer_url)
        if resp.status != 200:
            return None
        html = await resp.text()
        
        match = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if match:
            og_image = match.group(1)
            if "/web_files/" in og_image:
                base = og_image.split("/web_files/")[0]
                return f"{base}/web_files/original.pdf"
    except Exception as e:
        print(f"  [Warn] 뷰어 PDF 추출 실패: {e}")
    return None

async def _resolve_generic_download_url(context: BrowserContext, viewer_url: str) -> Optional[str]:
    """
    HTML 뷰어 페이지에서 일반 파일(docx, pptx 등)의 다운로드 링크를 찾는다.
    """
    try:
        page = await context.new_page()
        await page.goto(viewer_url)
        content = await page.content()
        
        # 1. 'download_url' 변수 찾기 (JS)
        # 예: var download_url = "https://...";
        m = re.search(r'download_url\s*[:=]\s*["\']([^"\']+)["\']', content)
        if m:
            url = m.group(1)
            if not url.startswith("http"):
                # 상대 경로 처리 (필요시 base_url 결합)
                pass 
            await page.close()
            return url.replace("\\/", "/")

        # 2. 'file_url' 변수 찾기
        m = re.search(r'file_url\s*[:=]\s*["\']([^"\']+)["\']', content)
        if m:
            url = m.group(1)
            await page.close()
            return url.replace("\\/", "/")

        # 3. iframe의 src가 파일 다운로드인지 확인
        frames = page.frames
        for frame in frames:
            if "download" in frame.url:
                await page.close()
                return frame.url

        await page.close()
    except Exception as e:
        print(f"  [Warn] 일반 파일 링크 추출 실패: {e}")
    return None

async def _download_file_logic(context: BrowserContext, course_dir: Path, file_name: str, target_url: str) -> Optional[str]:
    """공통 파일 다운로드 로직 (HTML 뷰어 리졸브 포함)"""
    try:
        if not target_url: return None
        
        # PDF Viewer Resolve
        if "/em/" in target_url:
            real = await _resolve_viewer_pdf(context, target_url)
            if real: target_url = real

        resp = await context.request.get(target_url)
        if resp.status != 200: return None
        
        body = await resp.body()
        
        # HTML Check
        ctype = resp.headers.get("content-type", "").lower()
        is_html = "text/html" in ctype or (len(body) < 2000 and b"<html" in body[:500].lower())
        
        if is_html:
            print(f"  [Resolve] HTML 뷰어 감지. 링크 추출 시도: {target_url}")
            link = await _resolve_generic_download_url(context, target_url)
            if link:
                print(f"  [Resolve] 링크 발견: {link}")
                resp = await context.request.get(link)
                if resp.status == 200: body = await resp.body()
                else: return None
            else:
                return None
                
        # Save
        dest = course_dir / file_name
        # 이름 중복 처리
        if dest.exists():
            stem = dest.stem
            ext = dest.suffix
            dest = course_dir / f"{stem}_new{ext}"
            
        with open(dest, "wb") as f:
            f.write(body)
        print(f"  [다운로드 완료] {dest.name}")
        return str(dest)
    except Exception as e:
        print(f"  [다운로드 에러] {e}")
        return None
