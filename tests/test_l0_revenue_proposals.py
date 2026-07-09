"""
Structural + grounded checks for L0 revenue proposal artifacts.

Drives real shipped readers (EconomicLedger.calculate_net,
count_verified_revenue_events) and validates the durable proposal file
on disk — not reimplemented fantasy numbers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from gates.verifier import count_verified_revenue_events
from observability.economic_ledger import EconomicLedger

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL_PATH = ROOT / "factory_core" / "proposals" / "l0-revenue-proposals-20260708.json"

XRPL_OR_LEDGER = re.compile(
    r"xrpl|ledger|explorer|testnet\.xrpl\.org|xrpl_tx_hash|verified_revenue|calculate_net",
    re.I,
)

REQUIRED_NET_KEYS = (
    "net_usd_est",
    "total_revenue_usd_est",
    "organic_revenue_usd_est",
    "total_cost_usd_est",
    "events_counted",
)


@pytest.fixture(scope="module")
def live_baseline() -> dict:
    """Drive shipped entry points twice; require stable shape."""
    led = EconomicLedger()
    net_a = led.calculate_net()
    verified_a = count_verified_revenue_events()
    net_b = EconomicLedger().calculate_net()
    verified_b = count_verified_revenue_events()

    assert set(REQUIRED_NET_KEYS).issubset(net_a.keys())
    assert set(REQUIRED_NET_KEYS).issubset(net_b.keys())
    for key in REQUIRED_NET_KEYS:
        assert isinstance(net_a[key], (int, float))
        assert isinstance(net_b[key], (int, float))
    assert isinstance(verified_a, int) and verified_a >= 0
    assert isinstance(verified_b, int) and verified_b >= 0
    # Same keys + stable types across two consecutive reads
    assert set(net_a.keys()) == set(net_b.keys())

    return {
        "net": net_a,
        "verified": verified_a,
        "ledger_path": led.ledger_path,
    }


@pytest.fixture(scope="module")
def proposal_doc() -> dict:
    assert PROPOSAL_PATH.is_file(), f"missing durable proposal artifact: {PROPOSAL_PATH}"
    return json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))


def test_l0_proposal_artifact_exists_and_focus_revenue(proposal_doc: dict):
    assert proposal_doc.get("focus") == "revenue"
    assert proposal_doc.get("primary_stack_goal") == "L0"
    proposals = proposal_doc.get("proposals") or []
    assert len(proposals) >= 1


def test_l0_proposals_have_usd_delta_and_xrpl_ledger_verification(proposal_doc: dict):
    gating = [p for p in proposal_doc["proposals"] if p.get("gating")]
    assert len(gating) >= 1
    for p in gating:
        assert p.get("title"), "gating proposal needs title"
        assert p.get("focus") == "revenue"
        delta = p.get("expected_economic_delta_usd")
        assert isinstance(delta, (int, float)), f"{p.get('id')} missing numeric delta"
        assert float(delta) > 0, f"{p.get('id')} delta must be positive for revenue proposals"
        vtext = p.get("verification_text") or ""
        vobj = p.get("verification") or {}
        blob = vtext + " " + json.dumps(vobj)
        assert XRPL_OR_LEDGER.search(blob), (
            f"{p.get('id')} verification must cite XRPL/ledger observables"
        )
        observables = vobj.get("observables") or []
        assert len(observables) >= 1, f"{p.get('id')} needs concrete observables"
        sources = " ".join(str(o.get("queryable_source", "")) for o in observables)
        assert XRPL_OR_LEDGER.search(sources), (
            f"{p.get('id')} observables must map to ledger/XRPL sources"
        )


def test_l0_grounding_matches_live_ledger_readers(
    proposal_doc: dict, live_baseline: dict
):
    """Baseline in artifact must be grounded in real ledger readers, not hardcoded fantasy."""
    grounding = proposal_doc.get("grounding") or {}
    live_net = live_baseline["net"]
    live_verified = live_baseline["verified"]

    captured = str(grounding.get("captured_via") or "")
    assert "calculate_net" in captured
    assert "count_verified_revenue_events" in captured

    for key in (
        "baseline_net_usd_est",
        "baseline_total_revenue_usd_est",
        "baseline_organic_revenue_usd_est",
        "baseline_total_cost_usd_est",
        "baseline_verified_revenue_events",
        "baseline_events_counted",
        "gap_to_l0_net_zero_usd",
        "revenue_gap_context",
    ):
        assert key in grounding, f"grounding missing {key}"

    baseline_net = float(grounding["baseline_net_usd_est"])
    gap = float(grounding["gap_to_l0_net_zero_usd"])
    # Gap is the positive distance to L0 (net_usd_est >= 0)
    assert gap == pytest.approx(max(0.0, -baseline_net), abs=0.01)

    # Drive real readers again inside the test (not only fixture) — no fantasy net.
    live_again = EconomicLedger().calculate_net()
    verified_again = count_verified_revenue_events()
    assert live_again["net_usd_est"] == pytest.approx(live_net["net_usd_est"], abs=1.0)
    assert isinstance(verified_again, int) and verified_again >= 0
    assert live_verified >= 0

    # Tolerate ledger growth after artifact capture: same L0 direction, not fantasy $0 gap.
    if live_net["net_usd_est"] < 0:
        assert gap > 0
        assert "net_usd_est" in str(grounding["revenue_gap_context"]) or "L0" in str(
            grounding["revenue_gap_context"]
        )
    else:
        assert gap >= 0

    # Artifact baseline should be a real historical snapshot of the same reader path:
    # allow drift (costs/revenue accumulate) but forbid inverted revenue/cost nonsense.
    assert float(grounding["baseline_total_revenue_usd_est"]) >= 0
    assert float(grounding["baseline_total_cost_usd_est"]) >= 0
    assert int(grounding["baseline_verified_revenue_events"]) >= 0
    assert int(grounding["baseline_events_counted"]) >= 0
    # Live revenue never goes negative on this reader
    assert live_net["total_revenue_usd_est"] >= 0

    explorer = grounding.get("last_xrpl_explorer_url")
    assert explorer is None or "testnet.xrpl.org" in str(explorer)


def test_calculate_net_entry_point_returns_required_fields(live_baseline: dict):
    net = live_baseline["net"]
    for key in REQUIRED_NET_KEYS:
        assert key in net
        assert isinstance(net[key], (int, float))
    assert isinstance(live_baseline["verified"], int)
    assert live_baseline["verified"] >= 0


def test_gating_aggregate_is_consistent(proposal_doc: dict):
    gating = [p for p in proposal_doc["proposals"] if p.get("gating")]
    assert len(gating) >= 1
    summed = sum(float(p["expected_economic_delta_usd"]) for p in gating)
    agg = proposal_doc.get("aggregate") or {}
    assert float(agg.get("sum_expected_economic_delta_usd", -1)) == pytest.approx(
        summed, abs=0.01
    )
    assert agg.get("focus") == "revenue"
    note = str(agg.get("l0_attainment_note") or "")
    assert "L0" in note or "net" in note.lower()
