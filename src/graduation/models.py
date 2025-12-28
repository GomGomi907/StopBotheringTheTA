"""
졸업요건 데이터 모델 및 트래커 로직

학과별 졸업요건을 정의하고, 사용자의 이수 현황을 추적합니다.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class GraduationArea(Enum):
    """졸업요건 영역"""
    MAJOR_REQUIRED = "전공필수"
    MAJOR_ELECTIVE = "전공선택"
    GENERAL_REQUIRED = "교양필수"
    GENERAL_ELECTIVE = "교양선택"
    FREE_ELECTIVE = "자유선택"
    BASIC = "기초"
    OTHER = "기타"


@dataclass
class CourseRequirement:
    """과목 요건"""
    course_code: str  # 학수번호 (예: CSE1001)
    course_name: str
    credits: int
    area: GraduationArea
    is_required: bool = False  # 필수 과목 여부
    alternatives: List[str] = field(default_factory=list)  # 대체 가능한 과목 코드


@dataclass
class GraduationRequirement:
    """학과별 졸업요건"""
    department: str  # 학과명 (예: 컴퓨터공학과)
    admission_year: int  # 입학년도 (요건이 다를 수 있음)
    total_credits: int = 130  # 총 이수학점
    
    # 영역별 최소 학점
    area_requirements: Dict[GraduationArea, int] = field(default_factory=dict)
    
    # 필수 과목 목록
    required_courses: List[CourseRequirement] = field(default_factory=list)
    
    # 추가 요건 (예: 영어, 졸업논문)
    additional_requirements: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.area_requirements:
            # 기본값 (컴퓨터공학과 기준 예시)
            self.area_requirements = {
                GraduationArea.MAJOR_REQUIRED: 30,
                GraduationArea.MAJOR_ELECTIVE: 45,
                GraduationArea.GENERAL_REQUIRED: 21,
                GraduationArea.GENERAL_ELECTIVE: 9,
                GraduationArea.FREE_ELECTIVE: 25,
            }


@dataclass
class CompletedCourse:
    """이수 과목"""
    course_code: str
    course_name: str
    credits: int
    grade: str  # A+, A, B+, ...
    semester: str  # 2024-1
    area: GraduationArea


@dataclass
class StudentProgress:
    """학생 졸업요건 진행 상황"""
    student_id: str
    department: str
    admission_year: int
    
    # 이수 과목 목록
    completed_courses: List[CompletedCourse] = field(default_factory=list)
    
    def get_total_credits(self) -> int:
        """총 이수 학점"""
        return sum(c.credits for c in self.completed_courses)
    
    def get_credits_by_area(self) -> Dict[GraduationArea, int]:
        """영역별 이수 학점"""
        result = {area: 0 for area in GraduationArea}
        for course in self.completed_courses:
            result[course.area] += course.credits
        return result
    
    def calculate_gpa(self) -> float:
        """평균 평점 계산"""
        grade_points = {
            'A+': 4.5, 'A': 4.0, 'B+': 3.5, 'B': 3.0,
            'C+': 2.5, 'C': 2.0, 'D+': 1.5, 'D': 1.0, 'F': 0.0
        }
        
        total_points = 0
        total_credits = 0
        
        for course in self.completed_courses:
            if course.grade in grade_points:
                total_points += grade_points[course.grade] * course.credits
                total_credits += course.credits
        
        return round(total_points / total_credits, 2) if total_credits > 0 else 0.0
    
    def check_graduation_status(self, requirement: GraduationRequirement) -> Dict[str, any]:
        """졸업요건 충족 여부 확인"""
        credits_by_area = self.get_credits_by_area()
        total_credits = self.get_total_credits()
        
        status = {
            "total_credits": {
                "current": total_credits,
                "required": requirement.total_credits,
                "satisfied": total_credits >= requirement.total_credits
            },
            "areas": {},
            "overall_satisfied": True
        }
        
        for area, required in requirement.area_requirements.items():
            current = credits_by_area.get(area, 0)
            satisfied = current >= required
            status["areas"][area.value] = {
                "current": current,
                "required": required,
                "satisfied": satisfied,
                "progress": round(min(current / required * 100, 100), 1) if required > 0 else 100
            }
            if not satisfied:
                status["overall_satisfied"] = False
        
        return status


# 샘플 데이터 (하드코딩 - 추후 크롤링으로 대체)
SAMPLE_REQUIREMENTS = {
    "컴퓨터공학과": GraduationRequirement(
        department="컴퓨터공학과",
        admission_year=2021,
        total_credits=130,
        area_requirements={
            GraduationArea.MAJOR_REQUIRED: 30,
            GraduationArea.MAJOR_ELECTIVE: 45,
            GraduationArea.GENERAL_REQUIRED: 21,
            GraduationArea.GENERAL_ELECTIVE: 9,
            GraduationArea.BASIC: 15,
            GraduationArea.FREE_ELECTIVE: 10,
        },
        additional_requirements=[
            "영어인증 (TOEIC 700 이상)",
            "졸업논문 또는 캡스톤디자인",
        ]
    )
}
