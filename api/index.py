import sys
import os

# Set working directory to repo root so app.py's __file__ resolves correctly
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(root)
sys.path.insert(0, root)

from app import app
