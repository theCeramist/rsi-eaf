"""Start hybrid autonomous runner with revenue pursuit."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("CYCLE_MODE", "hybrid")
os.environ.setdefault("VERCEL_DEPLOY", "true")
os.environ.setdefault("REVENUE_PURSUIT", "true")

from factory_core.autonomous_runner import run_autonomous

if __name__ == "__main__":
    run_autonomous(max_cycles=3, interval_minutes=5, mode="hybrid")