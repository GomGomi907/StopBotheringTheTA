"""
Timeline View - 전체 일정
목적: 학기 전체 일정을 한눈에 (주차별/과목별/유형별)
"""

import streamlit as st
from collections import defaultdict
from datetime import datetime
from typing import List, Dict
import hashlib


def render_timeline_view(data: List[Dict], state_manager, semester: str = None):
    """Timeline 뷰 렌더링"""
    st.header("📅 학기 일정")
    if semester:
        st.caption(f"📅 {_format_semester(semester)}")
    
    if not data:
        st.warning("📭 데이터가 없습니다.")
        return
    
    # === 필터 UI ===
    filtered = _render_filters(data, state_manager)
    
    if not filtered:
        st.info("필터 조건에 맞는 항목이 없습니다.")
        return
    
    st.divider()
    
    # === 뷰 모드 선택 ===
    view_mode = st.radio(
        "보기 모드",
        ["📅 주차별", "📚 과목별", "📋 유형별"],
        horizontal=True,
        label_visibility="collapsed"
    )
    
    if "주차별" in view_mode:
        _render_by_week(filtered, state_manager)
    elif "과목별" in view_mode:
        _render_by_course(filtered, state_manager)
    else:
        _render_by_type(filtered, state_manager)


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


def _render_filters(data: List[Dict], state_manager) -> List[Dict]:
    """필터 UI"""
    col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
    
    with col1:
        search = st.text_input("🔍 검색", placeholder="제목, 과목명...")
    
    with col2:
        # 과목 목록 추출
        courses = sorted(set(d.get("course_name", "") for d in data if d.get("course_name")))
        selected_course = st.selectbox("과목", ["전체"] + courses)
    
    with col3:
        types = st.multiselect(
            "유형",
            ["assignment", "notice", "material", "quiz"],
            default=[]
        )
    
    with col4:
        hide_done = st.checkbox("완료 숨김", value=False)
    
    # 필터 적용
    filtered = data
    
    if search:
        k = search.lower()
        filtered = [x for x in filtered 
                   if k in (x.get("title") or "").lower() 
                   or k in (x.get("course_name") or "").lower()]
    
    if selected_course != "전체":
        filtered = [x for x in filtered if x.get("course_name") == selected_course]
    
    if types:
        filtered = [x for x in filtered if x.get("category") in types]
    
    if hide_done:
        filtered = [x for x in filtered if not state_manager.is_done(x.get("original_id"))]
    
    st.caption(f"총 {len(filtered)}개 항목")
    
    return filtered


def _render_by_week(data: List[Dict], state_manager):
    """주차별 뷰"""
    weeks = defaultdict(list)
    unknown = []
    
    for item in data:
        w = item.get("week_index")
        if w and isinstance(w, int) and 1 <= w <= 16:
            weeks[w].append(item)
        else:
            unknown.append(item)
    
    sorted_weeks = sorted(weeks.keys())
    
    # 2열 레이아웃
    for i in range(0, len(sorted_weeks), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            idx = i + j
            if idx < len(sorted_weeks):
                w = sorted_weeks[idx]
                with col:
                    _render_week_block(w, weeks[w], state_manager)
    
    if unknown:
        with st.expander(f"📌 기타 ({len(unknown)}개)"):
            for i, item in enumerate(unknown):
                _render_item_row(item, state_manager, i)


def _render_by_course(data: List[Dict], state_manager):
    """과목별 뷰"""
    courses = defaultdict(list)
    for item in data:
        c = item.get("course_name") or "기타"
        courses[c].append(item)
    
    for course, items in sorted(courses.items()):
        with st.expander(f"📚 {course} ({len(items)}개)"):
            for i, item in enumerate(items):
                _render_item_row(item, state_manager, i)


def _render_by_type(data: List[Dict], state_manager):
    """유형별 뷰"""
    type_icons = {
        "assignment": ("📝", "과제"),
        "notice": ("📢", "공지"),
        "announcement": ("📢", "공지"),
        "material": ("📄", "자료"),
        "quiz": ("❓", "퀴즈"),
    }
    
    types = defaultdict(list)
    for item in data:
        cat = item.get("category") or "other"
        types[cat].append(item)
    
    for cat, items in types.items():
        icon, name = type_icons.get(cat, ("🔹", cat))
        with st.expander(f"{icon} {name} ({len(items)}개)"):
            for i, item in enumerate(items):
                _render_item_row(item, state_manager, i)


def _render_week_block(week: int, items: List[Dict], state_manager):
    """주차 블록"""
    st.markdown(f"#### 🗓️ {week}주차")
    
    # 날짜순 정렬
    items.sort(key=lambda x: x.get("due_date") or x.get("inferred_date") or "9999")
    
    for i, item in enumerate(items):
        _render_item_row(item, state_manager, i)


def _render_item_row(item: Dict, state_manager, idx: int = 0):
    """항목 행 (간략)"""
    oid = item.get("original_id")
    if not oid:
        # ID 없으면 생성
        unique_str = f"{item.get('title', '')}_{item.get('course_name', '')}_{idx}"
        oid = hashlib.md5(unique_str.encode()).hexdigest()
    
    is_done = state_manager.is_done(oid)
    
    cat = item.get("category", "other")
    icons = {"assignment": "📝", "notice": "📢", "announcement": "📢", "material": "📄", "quiz": "❓"}
    icon = icons.get(cat, "🔹")
    
    title = item.get("title", "제목 없음")
    course = item.get("course_name", "")
    due = item.get("due_date", "")[:10] if item.get("due_date") else ""
    
    col1, col2, col3, col4 = st.columns([0.5, 0.5, 5, 2])
    
    with col1:
        # 고유 키 생성 (idx 포함)
        new_done = st.checkbox("", value=is_done, key=f"tl_{oid}_{idx}", label_visibility="collapsed")
        if new_done != is_done:
            state_manager.set_done(oid, new_done)
            st.rerun()
    
    with col2:
        st.write(icon)
    
    with col3:
        if is_done:
            st.markdown(f"~~{title}~~", help=item.get("content_clean", "")[:200])
        else:
            st.markdown(f"**{title}**", help=item.get("content_clean", "")[:200])
    
    with col4:
        if due:
            st.caption(due)
