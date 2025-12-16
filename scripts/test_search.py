from src.db.mem0_client import AcademicMemory
import logging

logging.basicConfig(level=logging.INFO)

def test_search():
    print("Initializing Mem0...")
    mem = AcademicMemory()
    
    query = "과제"
    print(f"Searching for: {query}")
    
    results = mem.search(query, user_id="global_student_agent")
    
    print(f"Found {len(results)} results:")
    for r in results:
        print(f"- {r.get('memory')[:50]}... (Score: {r.get('score')})")

if __name__ == "__main__":
    test_search()
