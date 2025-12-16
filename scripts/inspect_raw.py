import json

def inspect():
    with open('data/raw/records.jsonl', 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if i >= 20: break
            try:
                data = json.loads(line)
                print(f"{i}: [{data.get('category')}] {data.get('title')} (ID: {data.get('payload', {}).get('id')})")
            except: pass

if __name__ == "__main__":
    inspect()
