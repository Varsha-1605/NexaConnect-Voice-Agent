import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# tests use the test namespace and database
os.environ.setdefault("PINECONE_NAMESPACE", "test")
