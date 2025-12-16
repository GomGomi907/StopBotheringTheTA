from typing import List, Dict

class SimpleReportGenerator:
    """LLM 없이 규칙 기반으로 단순 요약 리포트를 생성하는 모듈"""

    @staticmethod
    def generate_html_table(course_name: str, items: List[Dict]) -> str:
        """코스별 아이템 목록을 마크다운 표 형식으로 변환"""
        if not items:
            return ""

        # 날짜 내림차순 정렬 (최신순)
        # items has keys: category, title, content_summary, date, link
        sorted_items = sorted(items, key=lambda x: str(x.get("date", "")), reverse=True)

        md = f"### {course_name}\n\n"
        md += "| 날짜 | 분류 | 제목 | 요약/링크 |\n"
        md += "|---|---|---|---|\n"

        for item in sorted_items:
            date = item.get("date", "-")
            cat = item.get("category", "기타").upper()
            title = item.get("title", "무제").replace("|", "\|")
            summary = item.get("content_summary", "")[:100].replace("\n", " ").replace("|", "\|")
            link = item.get("link") or item.get("url")
            
            # 링크가 있으면 제목에 걸기
            if link:
                title_cell = f"[{title}]({link})"
            else:
                title_cell = title

            # 요약이 너무 길면 자르기
            if len(summary) > 50:
                summary = summary[:50] + "..."
            
            row = f"| {date} | {cat} | {title_cell} | {summary} |\n"
            md += row
        
        md += "\n---\n"
        return md

    @staticmethod
    def format_full_report(courses_data: Dict[str, List[Dict]], course_names: Dict[str, str]) -> str:
        """전체 데이터를 받아서 마크다운 리포트로 통합"""
        full_report = "# 📊 단순 요약 리포트 (No AI)\n\n"
        full_report += "> AI 가공 없이 수집된 데이터를 최신순으로 나열한 리포트입니다.\n\n"

        sorted_cids = sorted(courses_data.keys())
        
        for cid in sorted_cids:
            c_name = course_names.get(cid, cid)
            if c_name == "common":
                c_name = "📢 일반 공지 / 기타"
            
            items = courses_data[cid]
            full_report += SimpleReportGenerator.generate_html_table(c_name, items)
            
        return full_report
