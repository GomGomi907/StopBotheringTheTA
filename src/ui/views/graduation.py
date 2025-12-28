"""
졸업요건 트래커 UI 뷰

Streamlit 컴포넌트로 졸업요건 진행 현황을 시각화합니다.
"""

import streamlit as st
from typing import Dict
from src.graduation.models import (
    GraduationArea, GraduationRequirement, StudentProgress,
    CompletedCourse, SAMPLE_REQUIREMENTS
)


def render_graduation_view():
    """졸업요건 트래커 메인 뷰"""
    st.header("🎓 졸업요건 트래커")
    st.caption("졸업에 필요한 학점과 현재 이수 현황을 확인하세요.")
    
    # 학과 선택 (현재는 샘플만)
    dept = st.selectbox(
        "학과 선택",
        options=list(SAMPLE_REQUIREMENTS.keys()),
        key="graduation_dept"
    )
    
    requirement = SAMPLE_REQUIREMENTS.get(dept)
    if not requirement:
        st.warning("해당 학과의 졸업요건 데이터가 없습니다.")
        return
    
    # 이수 현황 (세션 상태에서 가져오거나 샘플 데이터)
    if "student_progress" not in st.session_state:
        # 샘플 데이터 초기화
        st.session_state["student_progress"] = _create_sample_progress()
    
    progress = st.session_state["student_progress"]
    
    # 졸업 상태 계산
    status = progress.check_graduation_status(requirement)
    
    # --- UI 렌더링 ---
    
    # 1. 전체 진행률
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_pct = min(status["total_credits"]["current"] / status["total_credits"]["required"] * 100, 100)
        st.metric(
            "총 이수학점",
            f"{status['total_credits']['current']} / {status['total_credits']['required']}",
            delta=f"{status['total_credits']['current'] - status['total_credits']['required']}학점" 
                  if status["total_credits"]["satisfied"] else None
        )
    
    with col2:
        st.metric("평균 평점 (GPA)", f"{progress.calculate_gpa():.2f} / 4.5")
    
    with col3:
        if status["overall_satisfied"]:
            st.success("✅ 졸업요건 충족!")
        else:
            st.warning("⚠️ 추가 이수 필요")
    
    st.divider()
    
    # 2. 영역별 진행률
    st.subheader("📊 영역별 이수 현황")
    
    for area_name, area_status in status["areas"].items():
        col1, col2 = st.columns([3, 1])
        
        with col1:
            # 프로그레스 바
            progress_value = area_status["progress"] / 100
            st.progress(progress_value, text=f"{area_name}")
        
        with col2:
            # 학점 표시
            if area_status["satisfied"]:
                st.markdown(f"✅ **{area_status['current']}/{area_status['required']}**")
            else:
                remaining = area_status["required"] - area_status["current"]
                st.markdown(f"🔸 {area_status['current']}/{area_status['required']} (-{remaining})")
    
    st.divider()
    
    # 3. 추가 요건
    if requirement.additional_requirements:
        st.subheader("📋 추가 졸업요건")
        for req in requirement.additional_requirements:
            st.checkbox(req, key=f"addl_{req}")
    
    # 4. 이수 과목 목록
    with st.expander("📚 이수 과목 목록", expanded=False):
        if progress.completed_courses:
            # 테이블 형식
            course_data = [
                {
                    "학기": c.semester,
                    "과목명": c.course_name,
                    "학점": c.credits,
                    "성적": c.grade,
                    "영역": c.area.value
                }
                for c in progress.completed_courses
            ]
            st.dataframe(course_data, use_container_width=True)
        else:
            st.info("이수 과목이 없습니다.")


def _create_sample_progress() -> StudentProgress:
    """샘플 학생 진행 데이터 생성"""
    return StudentProgress(
        student_id="20210001",
        department="컴퓨터공학과",
        admission_year=2021,
        completed_courses=[
            CompletedCourse("CSE1001", "프로그래밍기초", 3, "A+", "2021-1", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE1002", "이산수학", 3, "A", "2021-1", GraduationArea.BASIC),
            CompletedCourse("CSE2001", "자료구조", 3, "A", "2021-2", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE2002", "컴퓨터구조", 3, "B+", "2021-2", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE2003", "알고리즘", 3, "A", "2022-1", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE3001", "운영체제", 3, "B+", "2022-2", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE3002", "데이터베이스", 3, "A", "2022-2", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE3003", "컴퓨터네트워크", 3, "B", "2023-1", GraduationArea.MAJOR_REQUIRED),
            CompletedCourse("CSE4001", "소프트웨어공학", 3, "A", "2023-2", GraduationArea.MAJOR_ELECTIVE),
            CompletedCourse("CSE4002", "인공지능", 3, "A+", "2024-1", GraduationArea.MAJOR_ELECTIVE),
            CompletedCourse("CSE4003", "딥러닝", 3, "A", "2024-2", GraduationArea.MAJOR_ELECTIVE),
            CompletedCourse("GEN1001", "글쓰기", 3, "B+", "2021-1", GraduationArea.GENERAL_REQUIRED),
            CompletedCourse("GEN1002", "영어1", 3, "A", "2021-1", GraduationArea.GENERAL_REQUIRED),
            CompletedCourse("GEN1003", "영어2", 3, "A", "2021-2", GraduationArea.GENERAL_REQUIRED),
            CompletedCourse("GEN2001", "철학개론", 3, "B", "2022-1", GraduationArea.GENERAL_ELECTIVE),
            CompletedCourse("MTH1001", "미적분학1", 3, "B+", "2021-1", GraduationArea.BASIC),
            CompletedCourse("MTH1002", "미적분학2", 3, "B", "2021-2", GraduationArea.BASIC),
            CompletedCourse("MTH2001", "선형대수학", 3, "A", "2022-1", GraduationArea.BASIC),
        ]
    )
