"""One-shot metrics for autonomous runner evaluation."""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from observability.economic_ledger import ledger

AUTONOMOUS_START = 83
AUTONOMOUS_END = 88

events = ledger.get_recent_events(2000)
net = ledger.calculate_net()

def cycle_costs(cid):
    evs = [e for e in events if e.get("cycle_id") == cid and e.get("event_type") == "cost"]
    return sum(float(e.get("amount_usd_est", 0)) for e in evs)

def cycle_revenue(cid):
    evs = [
        e for e in events
        if e.get("cycle_id") == cid and e.get("event_type") == "revenue"
        and not e.get("metadata", {}).get("superseded")
    ]
    return sum(float(e.get("amount_usd_est", 0)) for e in evs)

verified = [
    e for e in events
    if e.get("event_type") == "revenue"
    and e.get("metadata", {}).get("verified")
    and not e.get("metadata", {}).get("superseded")
]

print("=== CUMULATIVE ===")
print(json.dumps(net, indent=2))
print(f"verified_inbound_payments: {len(verified)}")
for v in verified:
    print(f"  cycle {v.get('cycle_id')}: ${v.get('amount_usd_est')} tx={v.get('xrpl_tx_hash','')[:16]}...")

print(f"\n=== AUTONOMOUS SESSION CYCLES {AUTONOMOUS_START}-{AUTONOMOUS_END} ===")
total_cost = total_rev = 0
for cid in range(AUTONOMOUS_START, AUTONOMOUS_END + 1):
    c = cycle_costs(cid)
    r = cycle_revenue(cid)
    total_cost += c
    total_rev += r
    print(f"  cycle {cid}: cost=${c:.4f} revenue=${r:.4f} net=${r-c:.4f}")
print(f"  session totals: cost=${total_cost:.4f} revenue=${total_rev:.4f} net=${total_rev-total_cost:.4f}")

completions = [
    e for e in events
    if e.get("source") == "cycle_runner" and e.get("metadata", {}).get("phase") == "complete"
    and AUTONOMOUS_START <= (e.get("cycle_id") or 0) <= AUTONOMOUS_END
]
gate_pass = sum(1 for e in completions if e.get("metadata", {}).get("gates", {}).get("all_passed"))
print(f"gate_pass_rate: {gate_pass}/{len(completions)}")

xrpl_anchors = sum(
    1 for e in events
    if AUTONOMOUS_START <= (e.get("cycle_id") or 0) <= AUTONOMOUS_END
    and e.get("xrpl_tx_hash") and e.get("event_type") in {"asset_published", "tip_funnel_published", "briefing_published", "milestone"}
)
publish_types = {"asset_published", "tip_funnel_published", "briefing_published"}
pubs = [e for e in events if e.get("cycle_id") in range(AUTONOMOUS_START, AUTONOMOUS_END+1) and e.get("event_type") in publish_types]
print(f"publish_events_in_session: {len(pubs)} (3 engines x 6 cycles = 18 expected)")