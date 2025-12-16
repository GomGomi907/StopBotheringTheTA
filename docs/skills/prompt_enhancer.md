# Prompt Enhancer (Customized for Academic Crawler)

## Overview
Projects contextを 분석하여 단순한 요구사항을 **구조화된 구현 명세(Context, Patterns, Constraints)**로 변환하는 기법입니다.

## Methodology
Agent에게 지시할 때 다음 4단계를 거쳐 프롬프트를 구성합니다.

### 1. Context Analysis (맥락 분석)
현재 작업하려는 파일의 구조와 역할을 먼저 파악합니다.
- **Target**: `dashboard.py` (UI), `src/etl/` (Logic), `src/domains/` (Data)
- **Goal**: 사용자의 불명확한 요청("이거 고쳐줘")을 구체적 기술 부채 해결로 정의.

### 2. Pattern Recognition (패턴 인식)
기존 코드베이스의 스타일을 준수합니다.
- **Error Handling**: `try-except` 블록과 `logger.error` 사용 필수.
- **Type Hinting**: 모든 함수에 `Type Hint`와 `Docstring` 추가.
- **Async/Sync**: `asyncio` 사용 여부 명확화.

### 3. Structured Requirements (구조화된 요구사항)
단순 지시를 상세 명세로 변환합니다.

**Before:**
> "날짜가 이상하게 나오는데 고쳐줘."

**After (Enhanced):**
> **Goal**: Fix Date Inference Logic
> **Context**: `LMSCrawler` fetches relative dates like "Next Monday".
> **Constraint**: DO NOT use `datetime.now()` for relative calculation. Use `posted_at` from metadata as the anchor.
> **Output**: Update `src/etl/structurer.py` to parse "다음 주" as `posted_at + 7 days`.

## Meta Prompt Template
```markdown
# Role
You are a Senior Python Engineer specializing in Data Pipelines.

# Context
We are building a Robust ETL System for Academic Data (Canvas LMS).
Current Phase: [Phase Name]

# Task
[Description of the specific task]

# Requirements
1. [Requirement 1]
2. [Requirement 2]

# Constraints
- Strict Type Checking.
- No external API calls without permission.
- Use existing `LLMClient` for AI tasks.
```
