import sys
from pathlib import Path


API_SERVER_DIR = Path(__file__).resolve().parents[1]
if str(API_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(API_SERVER_DIR))
