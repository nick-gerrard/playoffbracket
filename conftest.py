import sys
import os

os.environ.setdefault("SESSION_SECRET_KEY", "test-secret-key")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
sys.path.insert(0, os.path.dirname(__file__))
