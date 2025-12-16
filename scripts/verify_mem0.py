from src.db.mem0_client import AcademicMemory
import logging

# Disable httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)

def verify():
    print("Checking Mem0...")
    try:
        mem = AcademicMemory()
        # Direct access to get_all if possible, or use search with empty query? 
        # Mem0 doesn't strictly support "get all" via memory object easily without user_id
        items = mem.get_all(user_id="global_student_agent")
        print(f"Memory Count: {len(items)}")
        if items:
            print(f"Sample: {items[0]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify()
