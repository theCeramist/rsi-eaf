"""One-shot hybrid cycle with Vercel deploy enabled."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["CYCLE_MODE"] = "hybrid"
os.environ["VERCEL_DEPLOY"] = "true"

from factory_core.cycle_runner import CycleRunner

if __name__ == "__main__":
    result = CycleRunner().run_cycle()
    gates = result["gates"]
    print(
        f"Cycle {result['cycle_id']} gates={gates['passed_count']}/{gates['total_count']} "
        f"focus={result['analysis'].get('cycle_focus')} "
        f"live_verified={result['execution'].get('live_verified')}"
    )
    sys.exit(0 if gates.get("all_passed") else 1)