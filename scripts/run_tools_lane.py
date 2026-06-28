"""Tools-only lane — pytest + tool/RSI improvement; no revenue engines."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("FACTORY_RUNNER_LANE", "tools")
os.environ.setdefault("FACTORY_RUN_CONTINUOUS", "true")
os.environ.setdefault("CYCLE_MODE", "tool_improvement")
os.environ.setdefault("VERCEL_DEPLOY", "false")
os.environ.setdefault("REVENUE_ENGINES", "")
os.environ.setdefault("REVENUE_PURSUIT", "false")

from factory_core.autonomous_runner import run_autonomous

if __name__ == "__main__":
    run_autonomous(max_cycles=None, interval_minutes=30, mode="tool_improvement")