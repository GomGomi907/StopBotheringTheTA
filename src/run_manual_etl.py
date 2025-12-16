import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.etl.structurer import DataStructurer

if __name__ == "__main__":
    print("Starting Manual ETL...")
    ds = DataStructurer()
    ds.run_normalization()
    print("Manual ETL Finished.")
