import sys
import os

os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key")
sys.path.insert(0, os.path.dirname(__file__))
