#!/usr/bin/env python3
"""Run the test suite without needing pytest installed.

    python tests/run.py

If you have pytest, `python -m pytest tests/ -q` works too and is preferred.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_pipeline                    # noqa: E402
from _mini import run_module            # noqa: E402

if __name__ == "__main__":
    raise SystemExit(1 if run_module(test_pipeline) else 0)
