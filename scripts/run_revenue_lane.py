"""Revenue-only lane — engines + treasury + distribution; skips tool-improvement phase."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("FACTORY_RUNNER_LANE", "revenue")
os.environ.setdefault("FACTORY_RUN_CONTINUOUS", "true")
os.environ.setdefault("CYCLE_MODE", "revenue")
os.environ.setdefault("VERCEL_DEPLOY", "true")
os.environ.setdefault("REVENUE_PURSUIT", "true")
os.environ.setdefault("FACTORY_SKIP_TOOL_PHASE", "true")

from factory_core.autonomous_runner import run_autonomous

if __name__ == "__main__":
    run_autonomous(max_cycles=None, interval_minutes=5, mode="revenue")