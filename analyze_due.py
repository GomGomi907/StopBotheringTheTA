import json
from collections import Counter, defaultdict

# Raw 데이터 로드
lines = open('data/semesters/2025-2/raw/records.jsonl', encoding='utf-8').readlines()
records = [json.loads(l) for l in lines]

print(f"=== 총 레코드 수: {len(records)} ===\n")

# 1. 카테고리별 분포
print("## 1. 카테고리 분포")
cats = Counter(r.get('category') for r in records)
for cat, count in cats.most_common():
    print(f"  {cat}: {count}")

# 2. 카테고리별 필드 분석
print("\n## 2. 카테고리별 payload 필드")
for cat in cats:
    items = [r for r in records if r.get('category') == cat]
    if items:
        payload = items[0].get('payload', {})
        fields = list(payload.keys())[:15]
        print(f"\n### {cat} ({len(items)}개)")
        print(f"  Fields: {fields}")

# 3. module_item 상세 분석
print("\n\n## 3. module_item 타입별 분석")
module_items = [r for r in records if r.get('category') == 'module_item']
types = Counter(r.get('payload', {}).get('type') for r in module_items)
for t, count in types.most_common():
    print(f"  {t}: {count}")
    # 샘플
    sample = next((r for r in module_items if r.get('payload', {}).get('type') == t), None)
    if sample:
        p = sample.get('payload', {})
        print(f"    title: {p.get('title', '')[:40]}")
        print(f"    due_at: {p.get('due_at')}")
        print(f"    content_details: {list(p.get('content_details', {}).keys())}")

# 4. 날짜 필드 분석
print("\n\n## 4. 날짜 필드 분석")
date_fields = ['due_at', 'lock_at', 'unlock_at', 'posted_at', 'created_at']
for field in date_fields:
    count = 0
    for r in records:
        p = r.get('payload', {})
        if p.get(field) or p.get('content_details', {}).get(field):
            count += 1
    print(f"  {field}: {count}개")

# 5. 주요 필드 존재 여부
print("\n\n## 5. 주요 필드 존재 분석")
fields_to_check = ['title', 'message', 'body', 'description', 'html_url', 'url']
for field in fields_to_check:
    count = sum(1 for r in records if r.get('payload', {}).get(field))
    print(f"  {field}: {count}개")
