"""Shared test setup."""

import os
import sys
from pathlib import Path

# Run from any folder: the project root (where config.py is) must be importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tests never touch the real database or the production knowledge base.
os.environ.setdefault("PINECONE_NAMESPACE", "test")
