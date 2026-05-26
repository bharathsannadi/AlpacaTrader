"""pytest configuration — adds scripts/ to sys.path so tests can import the
modules under test without an editable install.

Run from the repo root with:
    PYTHONPATH=venv/lib/python3.11/site-packages \\
      /usr/local/Cellar/python@3.11/3.11.15_1/Frameworks/Python.framework/Versions/3.11/bin/python3.11 \\
      -m pytest tests/ -v
"""
import os
import sys
from pathlib import Path

# Add scripts/ to sys.path so `import security`, `import screener_executor`, etc. work
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

# Prevent the rotating log handlers in spy_auto_trader from creating real
# log files in the test working directory.
os.environ.setdefault("PYTEST_RUNNING", "1")
