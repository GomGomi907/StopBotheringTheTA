import streamlit as st
from datetime import datetime, timedelta
import pandas as pd

def render_home_view(data, state_manager):
    st.header("🏠 Dashboard Overview")
    
    # --- 1. Semester Progress ---
    today = datetime.now()
    # 학기 시작일(임의 설정 또는 설정 파일에서) - 2025-09-01 가정
    term_start = datetime(2025, 9, 1) 
    # 현재 몇 주차인지 계산
    days_passed = (today - term_start).days
    current_week = max(1, min(16, (days_passed // 7) + 1))
    
    col_prog, col_stat = st.columns([3, 1])
    with col_prog:
        st.subheader(f"⏳ Semester Progress: Week {current_week}/16")
        progress = current_week / 16.0
        st.progress(progress)
    
    with col_stat:
        total_items = len(data)
        done_count = sum(1 for item in data if state_manager.is_done(item.get("original_id")))
        st.metric("Total Items", f"{done_count}/{total_items}", delta="Completed")

    st.divider()

    # --- 2. Urgency Board (Due This Week) ---
    st.subheader("🔥 Urgent Tasks (This Week)")
    
    # 이번주 마감 + 미완료 항목 필터링
    # 날짜 파싱 필요. 'due_date' (YYYY-MM-DD HH:MM)
    urgent_items = []
    
    for item in data:
        if state_manager.is_done(item.get("original_id")):
            continue
            
        due = item.get("due_date")
        if not due: continue
        
        try:
            # due format: YYYY-MM-DD HH:MM
            # inferred format: YYYY-MM-DD
            due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
            delta = (due_dt - today).days
            
            # -1(어제) ~ 7(일주일 뒤)
            if -1 <= delta <= 7:
                item["delta_days"] = delta
                urgent_items.append(item)
        except:
             pass
             
    if urgent_items:
        # 급한 순 정렬
        urgent_items.sort(key=lambda x: x["delta_days"])
        
        for item in urgent_items[:5]: # Top 5
            d_day = item['delta_days']
            label = "Today!" if d_day == 0 else (f"D-{d_day}" if d_day > 0 else "Overdue")
            color = "red" if d_day <= 1 else "orange"
            
            with st.container():
                c1, c2 = st.columns([1, 5])
                with c1:
                    st.markdown(f":{color}[**{label}**]")
                with c2:
                    st.markdown(f"**{item['title']}** ({item['course_name']})")
                    st.caption(item.get('content_clean', ''))
    else:
        st.success("✨ 이번 주 마감인 급한 과제가 없습니다!")

    st.divider()
    
    # --- 3. Recent Notices ---
    st.subheader("📢 Recent Notices")
    # 공지사항 중 최신순 5개
    notices = [i for i in data if i.get("category") == "notice"]
    # original_id가 뒤에 생성된게 최신이라 가정하거나, inferred_date 역순
    # 여기선 리스트 뒤집어서 보여줌 (크롤링 역순 가정) -> 보통 최신이 위에 오므로 정방향 체크
    # 근데 records.jsonl은 append 방식이라 뒤가 최신일수도, API reverse일수도.
    # 일단 앞에서 5개 보여줌.
    
    for notice in notices[:5]:
        with st.expander(f"📢 {notice['title']} ({notice['course_name']})"):
             st.info(notice.get("content_clean"))
