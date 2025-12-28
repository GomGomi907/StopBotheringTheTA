"""
Home View - 오늘의 대시보드
목적: 지금 당장 확인해야 할 것들
"""

import streamlit as st
from datetime import datetime, timedelta
from typing import List, Dict, Optional


def render_home_view(data: List[Dict], state_manager, semester: str = None):
    """Home 뷰 렌더링"""
    # 학기 헤더
    semester_label = _format_semester(semester) if semester else ""
    st.header(f"🏠 오늘의 대시보드")
    if semester_label:
        st.caption(f"📅 {semester_label}")
    
    if not data:
        st.warning("📭 데이터가 없습니다. 사이드바에서 크롤링을 실행하세요.")
        return
    
    today = datetime.now()
    
    # === 상단: 학기 진행률 + 완료 현황 ===
    _render_progress_section(data, state_manager, today)
    
    st.divider()
    
    # === 핵심: 마감 임박 섹션 ===
    _render_urgent_section(data, state_manager, today)
    
    st.divider()
    
    # === 최근 공지 ===
    _render_notices_section(data)


def _format_semester(semester: str) -> str:
    """학기 문자열을 친화적인 형식으로 변환"""
    if not semester:
        return ""
    parts = semester.split("-")
    if len(parts) != 2:
        return semester
    year, period = parts
    period_names = {
        "1": "1학기",
        "2": "2학기", 
        "summer": "여름계절학기",
        "winter": "겨울계절학기"
    }
    return f"{year}년 {period_names.get(period, period)}"


def _render_progress_section(data: List[Dict], state_manager, today: datetime):
    """학기 진행률 및 완료 현황"""
    # 학기 시작일 자동 계산
    year = today.year
    month = today.month
    if 3 <= month <= 8:  # 1학기 (3월~8월)
        term_start = datetime(year, 3, 2)
    else:  # 2학기 (9월~2월)
        term_start = datetime(year if month >= 9 else year - 1, 9, 2)
    
    days_passed = (today - term_start).days
    current_week = max(1, min(16, (days_passed // 7) + 1))
    progress = current_week / 16.0
    
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.markdown(f"### ⏳ Week {current_week}/16")
        st.progress(progress, text=f"{int(progress * 100)}% 진행")
    
    with col2:
        total = len(data)
        done = sum(1 for item in data if state_manager.is_done(item.get("original_id")))
        st.metric("완료", f"{done}/{total}", delta=f"{int(done/total*100) if total else 0}%")
    
    with col3:
        # 마감 임박 카운트
        urgent_count = _count_urgent(data, state_manager, today)
        color = "🔴" if urgent_count > 3 else ("🟡" if urgent_count > 0 else "🟢")
        st.metric("마감 임박", f"{color} {urgent_count}개")


def _count_urgent(data: List[Dict], state_manager, today: datetime) -> int:
    """D-3 이내 미완료 항목 수"""
    count = 0
    for item in data:
        if state_manager.is_done(item.get("original_id")):
            continue
        due = item.get("due_date")
        if not due:
            continue
        try:
            due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
            delta = (due_dt - today).days
            if -1 <= delta <= 3:
                count += 1
        except:
            pass
    return count


def _render_urgent_section(data: List[Dict], state_manager, today: datetime):
    """🔥 마감 임박 섹션 (핵심)"""
    st.subheader("🔥 마감 임박")
    
    urgent_items = []
    for item in data:
        due = item.get("due_date")
        if not due:
            continue
        try:
            due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
            delta = (due_dt - today).days
            if -1 <= delta <= 7:
                item_copy = item.copy()
                item_copy["_delta"] = delta
                item_copy["_is_done"] = state_manager.is_done(item.get("original_id"))
                urgent_items.append(item_copy)
        except:
            pass
    
    if not urgent_items:
        st.success("✨ 일주일 내 마감인 항목이 없습니다!")
        return
    
    # 급한 순 정렬 (완료 항목은 뒤로)
    urgent_items.sort(key=lambda x: (x["_is_done"], x["_delta"]))
    
    for item in urgent_items[:8]:
        _render_urgent_card(item, state_manager)


def _render_urgent_card(item: Dict, state_manager):
    """마감 임박 카드 (체크박스 포함)"""
    delta = item["_delta"]
    is_done = item["_is_done"]
    original_id = item.get("original_id", "")
    
    # D-Day 라벨
    if delta < 0:
        label = "⚠️ 지남"
        bg_color = "#ff6b6b"
    elif delta == 0:
        label = "🔥 오늘"
        bg_color = "#ff8787"
    elif delta == 1:
        label = "D-1"
        bg_color = "#ffa94d"
    elif delta <= 3:
        label = f"D-{delta}"
        bg_color = "#ffd43b"
    else:
        label = f"D-{delta}"
        bg_color = "#69db7c"
    
    # 완료 시 스타일 변경
    if is_done:
        bg_color = "#868e96"
        label = "✅ 완료"
    
    with st.container(border=True):
        col_check, col_label, col_content = st.columns([0.5, 1, 6])
        
        with col_check:
            # 완료 체크박스
            new_state = st.checkbox(
                "✓",
                value=is_done,
                key=f"done_{original_id}",
                label_visibility="collapsed"
            )
            if new_state != is_done:
                state_manager.set_done(original_id, new_state)
                st.rerun()
        
        with col_label:
            st.markdown(
                f"<div style='background:{bg_color}; padding:4px 8px; border-radius:4px; "
                f"text-align:center; font-weight:bold; font-size:0.85em;'>{label}</div>",
                unsafe_allow_html=True
            )
        
        with col_content:
            title = item.get("title", "제목 없음")
            course = item.get("course_name", "")
            
            if is_done:
                st.markdown(f"~~**{title}**~~ <span style='color:gray'>({course})</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**{title}** <span style='color:gray'>({course})</span>", unsafe_allow_html=True)


def _render_notices_section(data: List[Dict]):
    """📢 최근 공지 섹션"""
    st.subheader("📢 최근 공지")
    
    notices = [i for i in data if i.get("category") in ["notice", "announcement"]]
    
    if not notices:
        st.info("최근 공지가 없습니다.")
        return
    
    # 최신순 정렬 (posted_at 또는 created_at 기준)
    def get_date(item):
        d = item.get("posted_at") or item.get("created_at") or ""
        return d[:10] if d else ""
    
    notices.sort(key=get_date, reverse=True)
    
    for notice in notices[:5]:
        course = notice.get("course_name", "")
        title = notice.get("title", "")
        content = notice.get("content_clean", notice.get("body_text", ""))[:200]
        
        with st.expander(f"📢 **{title}** ({course})"):
            st.markdown(content)
            if notice.get("url"):
                st.link_button("원본 보기", notice["url"])
