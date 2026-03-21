#!/bin/bash
# Themis Dashboard — Real-time test visualization
cd "$(dirname "$0")"
source .venv/bin/activate 2>/dev/null || true
PYTHONPATH=src python3 -m uvicorn themis.dashboard.app:app --host 0.0.0.0 --port 8200 --reload
