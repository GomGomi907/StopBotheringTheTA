"""
날짜 추론 유틸리티 (Rule-based + LLM Fallback)

한국어/영어 날짜 표현을 파싱하여 정규화된 날짜를 반환합니다.
LLM 호출 전에 전처리 레이어로 사용합니다.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _make_naive(dt: datetime) -> datetime:
    """timezone-aware datetime을 naive로 변환 (로컬 시간으로)"""
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


# --- 정규식 패턴 ---

# 절대 날짜 패턴
ABSOLUTE_DATE_PATTERNS = [
    # YYYY-MM-DD, YYYY/MM/DD
    (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    # MM/DD, MM-DD (올해로 추정)
    (r'(\d{1,2})[-/](\d{1,2})(?!\d)', lambda m: (None, int(m.group(1)), int(m.group(2)))),
    # 12월 25일, 12월25일
    (r'(\d{1,2})월\s*(\d{1,2})일', lambda m: (None, int(m.group(1)), int(m.group(2)))),
    # December 25, Dec 25
    (r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(\d{1,2})', 
     lambda m: (None, _month_name_to_num(m.group(1)), int(m.group(2)))),
]

# 상대 날짜 패턴 (posted_at 기준)
RELATIVE_DATE_PATTERNS = [
    # 다음 주, 다음주, next week
    (r'다음\s*주|next\s*week', lambda anchor: anchor + timedelta(days=7)),
    # 이번 주, 이번주, this week
    (r'이번\s*주|this\s*week', lambda anchor: anchor),
    # 내일, tomorrow
    (r'내일|tomorrow', lambda anchor: anchor + timedelta(days=1)),
    # 모레, day after tomorrow
    (r'모레|day\s+after\s+tomorrow', lambda anchor: anchor + timedelta(days=2)),
    # N일 후, N일후, in N days
    (r'(\d+)\s*일\s*후|in\s+(\d+)\s+days?', lambda anchor, m: anchor + timedelta(days=int(m.group(1) or m.group(2)))),
    # 금요일까지, by Friday
    (r'(월|화|수|목|금|토|일)요일(?:까지)?', lambda anchor, m: _next_weekday(anchor, _korean_weekday(m.group(1)))),
    (r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*', lambda anchor, m: _next_weekday(anchor, _english_weekday(m.group(1)))),
]

# 시간 패턴 (HH:MM)
TIME_PATTERN = r'(\d{1,2}):(\d{2})(?::(\d{2}))?'
# 23시 59분, 23시59분
TIME_KOREAN_PATTERN = r'(\d{1,2})시\s*(\d{1,2})분?'


def _month_name_to_num(name: str) -> int:
    """영문 월 이름을 숫자로 변환"""
    months = {'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
              'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12}
    return months.get(name.lower()[:3], 1)


def _korean_weekday(name: str) -> int:
    """한국어 요일을 weekday 숫자로 (월=0, 일=6)"""
    weekdays = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6}
    return weekdays.get(name, 0)


def _english_weekday(name: str) -> int:
    """영문 요일을 weekday 숫자로"""
    weekdays = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}
    return weekdays.get(name.lower()[:3], 0)


def _next_weekday(anchor: datetime, weekday: int) -> datetime:
    """anchor 이후 가장 가까운 특정 요일 반환"""
    days_ahead = weekday - anchor.weekday()
    if days_ahead <= 0:  # 이미 지났거나 오늘이면 다음 주
        days_ahead += 7
    return anchor + timedelta(days=days_ahead)


def parse_absolute_date(text: str, reference_year: Optional[int] = None) -> Optional[datetime]:
    """
    텍스트에서 절대 날짜를 추출합니다.
    
    Args:
        text: 파싱할 텍스트
        reference_year: 연도가 없을 때 사용할 기준 연도 (기본: 현재 연도)
    
    Returns:
        파싱된 datetime 또는 None
    """
    if reference_year is None:
        reference_year = datetime.now().year
    
    text_lower = text.lower()
    
    for pattern, extractor in ABSOLUTE_DATE_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            try:
                result = extractor(match)
                year, month, day = result
                
                if year is None:
                    year = reference_year
                    # 월이 현재보다 이전이면 다음 해로 추정
                    if month < datetime.now().month:
                        year += 1
                
                return datetime(year, month, day)
            except (ValueError, IndexError) as e:
                logger.debug(f"Date parse error: {e}")
                continue
    
    return None


def parse_relative_date(text: str, anchor: datetime) -> Optional[datetime]:
    """
    텍스트에서 상대 날짜를 추출합니다.
    
    Args:
        text: 파싱할 텍스트
        anchor: 기준 날짜 (보통 posted_at)
    
    Returns:
        계산된 datetime 또는 None
    """
    text_lower = text.lower()
    
    for pattern, calculator in RELATIVE_DATE_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            try:
                # 일부 패턴은 match 그룹이 필요
                if match.groups():
                    return calculator(anchor, match)
                else:
                    return calculator(anchor)
            except Exception as e:
                logger.debug(f"Relative date calc error: {e}")
                continue
    
    return None


def parse_time(text: str) -> Optional[Tuple[int, int]]:
    """텍스트에서 시간(HH:MM)을 추출합니다."""
    # HH:MM 형식
    match = re.search(TIME_PATTERN, text)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    # 한국어 형식
    match = re.search(TIME_KOREAN_PATTERN, text)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    return None


def extract_date(
    text: str, 
    posted_at: Optional[datetime] = None,
    reference_year: Optional[int] = None
) -> Tuple[Optional[datetime], str]:
    """
    텍스트에서 날짜를 추출합니다 (절대 → 상대 순서).
    
    Args:
        text: 파싱할 텍스트
        posted_at: 상대 날짜 계산을 위한 기준 날짜
        reference_year: 절대 날짜의 기준 연도
    
    Returns:
        (추출된 datetime, confidence) - confidence: 'high', 'medium', 'low', 'none'
    """
    if not text:
        return None, 'none'
    
    # 1. 절대 날짜 시도 (높은 신뢰도)
    abs_date = parse_absolute_date(text, reference_year)
    if abs_date:
        time_info = parse_time(text)
        if time_info:
            abs_date = abs_date.replace(hour=time_info[0], minute=time_info[1])
        return abs_date, 'high'
    
    # 2. 상대 날짜 시도 (중간 신뢰도, anchor 필요)
    if posted_at:
        rel_date = parse_relative_date(text, posted_at)
        if rel_date:
            return rel_date, 'medium'
    
    # 3. 파싱 실패
    return None, 'none'


def validate_date(date: datetime, context: str = "") -> bool:
    """
    추출된 날짜가 합리적인지 검증합니다.
    
    - 과거 1년 이상 전 날짜는 의심
    - 미래 1년 이상 후 날짜는 의심
    """
    now = datetime.now()
    # timezone 호환성: 둘 다 naive로 비교
    date = _make_naive(date)
    
    # 과거 1년 이전
    if date < now - timedelta(days=365):
        logger.warning(f"Date too old: {date} (context: {context[:50]})")
        return False
    
    # 미래 1년 이후
    if date > now + timedelta(days=365):
        logger.warning(f"Date too far: {date} (context: {context[:50]})")
        return False
    
    return True
