"""Core factory tests."""

import json
import os
from pathlib import Path

import pytest

from gates.verifier import run_cycle_gates, verify_xrpl_transaction
from observability.economic_ledger import EconomicLedger
from observability.grok_usage import parse_session_usage
from observability.payment_intent import resolve_payment_intent
from observability.revenue_ingest import _extract_payment_fields
from tools.publish_tools import build_index_html
from revenue_engines.registry import enabled_engines
from revenue_engines.tipping_funnel import TippingFunnel
from tools.xrpl_research import format_briefing_teaser
from tools.xrpl_tools import parse_ws_payment_message


def test_ledger_net_excludes_superseded(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    led = EconomicLedger(ledger_path=str(ledger_path))
    led.log_event("revenue", "old", 0.5, cycle_id=1, metadata={"superseded": True}, anchor_to_xrpl=False)
    led.log_event("cost", "grok", 1.0, cycle_id=1, anchor_to_xrpl=False)
    net = led.calculate_net()
    assert net["total_revenue_usd_est"] == 0.0
    assert net["total_cost_usd_est"] == 1.0


def test_build_index_html(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    import tools.publish_tools as pt

    monkeypatch.setattr(pt, "PUBLISHED_DIR", tmp_path)
    (tmp_path / "a.html").write_text("<html></html>")
    index = build_index_html(treasury_address="rTest123")
    assert index.exists()
    content = index.read_text()
    assert "a.html" in content
    assert "rTest123" in content


def test_run_cycle_gates_published_missing():
    result = run_cycle_gates(
        cycle_id=99,
        execution_result={"published_asset": "missing/file.html", "xrpl_tx_hash": "ABC"},
    )
    assert result["all_passed"] is False
    names = [g["gate"] for g in result["gates"]]
    assert "published_asset_exists" in names


def test_parse_session_usage_empty(tmp_path):
    parsed = parse_session_usage(tmp_path)
    assert parsed["turns"] == []


def test_parse_ws_payment_message_tx_json():
    treasury = "rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN"
    msg = {
        "type": "transaction",
        "engine_result": "tesSUCCESS",
        "tx_hash": "ABC123",
        "tx_json": {
            "TransactionType": "Payment",
            "Account": "rExternal111",
            "Destination": treasury,
            "Amount": "1000000",
        },
    }
    payment = parse_ws_payment_message(msg, treasury, testnet=True)
    assert payment is not None
    assert payment["tx_hash"] == "ABC123"
    assert payment["from"] == "rExternal111"
    assert "testnet.xrpl.org" in payment["explorer_url"]


def test_parse_ws_payment_message_ignores_internal():
    treasury = "rTreasury"
    factory = "rFactory"
    msg = {
        "type": "transaction",
        "engine_result": "tesSUCCESS",
        "transaction": {
            "TransactionType": "Payment",
            "Account": factory,
            "Destination": treasury,
            "hash": "INTERNAL1",
        },
    }
    payment = parse_ws_payment_message(msg, treasury)
    assert payment is not None
    assert payment["from"] == factory


def test_enabled_revenue_engines_include_high_impact(monkeypatch):
    monkeypatch.setenv("REVENUE_TOP3_ENABLED", "true")
    names = enabled_engines()
    assert "tipping_funnel" in names
    assert "paid_briefing" in names
    assert "content_operator" in names
    assert "micro_saas" in names
    assert "mythos_commerce" in names
    assert "agent_marketplace" in names


def test_revenue_fitness_top3_order():
    from factory_core.revenue_fitness import evaluate_revenue_models

    result = evaluate_revenue_models()
    top3 = result["top3_ids"]
    assert top3[0] == "micro_saas"
    assert "mythos_commerce" in top3
    assert "agent_marketplace" in top3
    assert result["ranked"][0]["fitness"] >= result["ranked"][-1]["fitness"]


def test_payment_intent_mythos_and_service_tags():
    from observability.payment_intent import resolve_payment_intent

    mythos = resolve_payment_intent({"destination_tag": 5, "memos": [], "plain_memos": []}, cycle_id=9)
    assert mythos is not None
    assert mythos.product_id == "mythos-cycle-9"
    service = resolve_payment_intent({"destination_tag": 4, "memos": [], "plain_memos": []}, cycle_id=9)
    assert service is not None
    assert "service-bundle" in (service.product_id or "")


def test_treasury_daemon_dedupe_inbox(tmp_path, monkeypatch):
    from observability import treasury_daemon as td

    inbox = tmp_path / "inbox.jsonl"
    monkeypatch.setattr(td, "INBOX_FILE", inbox)
    td._seen_hashes.clear()
    pay = {"tx_hash": "DUP1", "from": "rExt"}
    td._append_inbox(pay)
    td._append_inbox(pay)
    assert len(inbox.read_text(encoding="utf-8").strip().splitlines()) == 1


def test_runner_preflight_structure(monkeypatch):
    from factory_core.runner_preflight import run_preflight

    monkeypatch.setenv("FACTORY_PREFLIGHT_PYTEST", "false")
    result = run_preflight()
    assert "ok" in result
    assert "top3_revenue" in result
    assert len(result["top3_revenue"]) == 3


def test_treasury_monitor_skips_inline_ws_when_daemon(monkeypatch):
    from observability import treasury_monitor as tm

    monkeypatch.setattr(tm, "_daemon_active", lambda: True)
    monkeypatch.setattr(tm, "SKIP_INLINE_WS", True)
    monkeypatch.setattr(
        "observability.treasury_daemon.drain_inbox",
        lambda limit=100: [],
    )
    monkeypatch.setattr(
        "observability.treasury_daemon.start_treasury_daemon",
        lambda address=None: {"started": True},
    )
    monkeypatch.setenv("TREASURY_DAEMON_ENABLED", "true")
    calls = []

    def fake_monitor(*args, **kwargs):
        calls.append(1)
        return 0

    monkeypatch.setattr("tools.xrpl_tools.monitor_incoming_payments", fake_monitor)
    monkeypatch.setattr(
        "observability.revenue_ingest.ingest_verified_xrpl_revenue",
        lambda **k: {"ingested": [], "unmatched": []},
    )
    result = tm.poll_treasury_payments(cycle_id=7)
    assert result["poll_mode"] == "daemon_inbox_only"
    assert calls == []


def test_monitor_incoming_payments_respects_timeout(monkeypatch):
    import time as time_mod
    from tools import xrpl_tools as xt

    def slow_poll():
        time_mod.sleep(30)

    monkeypatch.setattr(xt, "WebsocketClient", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip ws")))
    # Direct test: worker join returns even if thread would block
    start = time_mod.monotonic()
    monkeypatch.setattr(xt, "parse_ws_payment_message", lambda *a, **k: None)

    def fake_ws_ctx(*args, **kwargs):
        class FakeWS:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def send(self, *a, **k):
                pass

            def __iter__(self):
                while True:
                    time_mod.sleep(1)
                    yield {"type": "transaction"}

        return FakeWS()

    monkeypatch.setattr(xt, "WebsocketClient", fake_ws_ctx)
    observed = xt.monitor_incoming_payments("rTest", lambda p: None, timeout_seconds=1)
    elapsed = time_mod.monotonic() - start
    assert elapsed < 8
    assert observed == 0


def test_parallel_lanes_manifest():
    from config.integration import integration_manifest

    m = integration_manifest()
    lanes = m.get("parallel_lanes", {})
    assert "distribution" in lanes.get("daemons", [])
    assert "revenue_sprint" in lanes.get("async_grok", [])
    assert "revenue" in lanes.get("runner_lanes", [])


def test_revenue_sprint_should_run():
    from factory_core.revenue_sprint import should_run_revenue_sprint

    assert should_run_revenue_sprint(0.0, consecutive_zero=1) is True
    assert should_run_revenue_sprint(5.0, consecutive_zero=1) is False


def test_nexus_echo_drift_structure(monkeypatch):
    from observability import nexus_echo_daemon as ned

    monkeypatch.setattr(
        "factory_core.state.FactoryState",
        lambda: type("S", (), {"current_cycle": 20})(),
    )
    monkeypatch.setattr(
        "tools.github_client.fetch_repo_json",
        lambda *a, **k: {"rsi_eaf_runner": {"cycle_id": 10}},
    )
    monkeypatch.setattr("tools.nexus_bridge.verify_external_surfaces", lambda: {"all_ok": True})
    monkeypatch.setattr("tools.publish_tools.verify_live_url", lambda u: True)
    check = ned.check_nexus_drift()
    assert check["drift_cycles"] == 10
    assert check["needs_emit"] is True


def test_runner_lane_lock_paths():
    from factory_core import runner_lock

    assert runner_lock.runner_lane() in {"hybrid", "revenue", "tools", ""}


def test_micro_saas_scout_schedule():
    from factory_core.micro_saas_scout import should_run_scout

    assert should_run_scout(5) is True
    assert should_run_scout(3) is False


def test_distribution_daemon_tick_structure(monkeypatch, tmp_path):
    from observability import distribution_daemon as dd

    monkeypatch.setattr(dd, "INTEL_FILE", tmp_path / "dist.jsonl")
    monkeypatch.setattr("revenue_engines.base_engine.resolve_treasury", lambda: "rTest")
    monkeypatch.setattr(
        "tools.distribution_tools.featured_links_for_index",
        lambda c: {"tip_page": "https://example.com/tip"},
    )
    monkeypatch.setattr(
        "tools.revenue_acceleration.write_outreach_bundle",
        lambda cycle_id, treasury, featured=None: {
            "tip_url": "https://example.com/tip",
            "payload": {},
        },
    )
    monkeypatch.setattr("tools.publish_tools.verify_live_url", lambda u: True)
    monkeypatch.setattr(
        "tools.github_distribution.refresh_support_issue",
        lambda cycle_id, featured, treasury: {"issue_updated": True},
    )
    monkeypatch.setattr(
        "tools.github_distribution.maybe_push_distribution",
        lambda **kwargs: {"pushed": False, "skipped": True},
    )
    result = dd.run_distribution_tick(cycle_id=42)
    assert result["started"] is True
    assert result["tick"]["cycle_id"] == 42


def test_integration_manifest_compact():
    from config.integration import integration_manifest

    m = integration_manifest(cycle_id=42, featured={"tip_page": "https://example.com/tip"})
    assert m["schema"] == "rsi_eaf_integration_v1"
    assert "github" in m
    assert "jarvis-swarm" in m["github"]["nexus"]["repo"]
    assert m["revenue_engines"]["top3_enabled"] is True
    assert "deferred" in m["revenue_engines"]


def test_publish_hygiene_archives_stale_html(tmp_path, monkeypatch):
    from tools import publish_hygiene as ph

    monkeypatch.setattr(ph, "PUBLISHED_DIR", tmp_path)
    monkeypatch.setattr(ph, "ARCHIVE_DIR", tmp_path / "archive")
    (tmp_path / "tip-cycle-1-old.html").write_text("a", encoding="utf-8")
    (tmp_path / "tip-cycle-99-new.html").write_text("b", encoding="utf-8")
    (tmp_path / "index.html").write_text("idx", encoding="utf-8")
    result = ph.prune_published_for_deploy(cycle_id=99, max_html=8)
    assert result["archived_count"] >= 1
    assert (tmp_path / "tip-cycle-99-new.html").exists()
    assert not (tmp_path / "tip-cycle-1-old.html").exists()


def test_director_enables_top3_engines(monkeypatch):
    from factory_core.director import FactoryDirector, CyclePlan

    monkeypatch.delenv("REVENUE_ENGINES", raising=False)
    monkeypatch.setenv("REVENUE_TOP3_ENABLED", "true")
    director = FactoryDirector()
    plan = CyclePlan(cycle_id_next=1, mode="hybrid", focus="revenue", sleep_minutes=5)
    director.configure_autonomous_env(plan)
    engines = os.environ.get("REVENUE_ENGINES", "")
    assert "micro_saas" in engines
    assert "mythos_commerce" in engines
    assert "agent_marketplace" in engines


def test_factory_health_snapshot():
    from observability.factory_health import build_factory_health

    health = build_factory_health(cycle_id=1, featured={"tip_page": "https://x/tip"})
    assert "integration" in health
    assert "ledger_net" in health


def test_jarvis_ci_workflow_yaml_valid():
    """Workflow must not embed unindented heredocs (breaks GHA YAML parser)."""
    from tools.jarvis_swarm_ci_repair import _WORKFLOW

    assert "python3 scripts/jarvis_hygiene_scan.py" in _WORKFLOW
    assert "name: Nexus Portal CI/CD" in _WORKFLOW
    assert "${{ secrets.VERCEL_TOKEN }}" in _WORKFLOW
    assert "${{{{" not in _WORKFLOW
    for line in _WORKFLOW.splitlines():
        if line.startswith("import ") or line.startswith("from "):
            raise AssertionError(f"unindented python in workflow YAML: {line!r}")


def test_tipping_funnel_html_includes_treasury(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    import revenue_engines.tipping_funnel as tf

    monkeypatch.setattr(tf, "PUBLISHED_DIR", str(tmp_path))
    monkeypatch.setattr(tf, "resolve_treasury", lambda: "rTreasury123")
    monkeypatch.setattr(
        tf,
        "publish_and_anchor",
        lambda **kwargs: {
            "live_url": "https://example.com/tip.html",
            "xrpl_tx_hash": "HASH",
            "explorer_url": "https://testnet.xrpl.org/transactions/HASH",
        },
    )
    monkeypatch.setattr(tf, "write_tip_manifest", lambda **kwargs: tmp_path / "tip-manifest.json")

    result = TippingFunnel(published_dir=str(tmp_path)).run(cycle_id=42)
    html = (tmp_path / result["published_path"]).read_text() if "published_path" in result else ""
    if not html:
        html_files = list(tmp_path.glob("tip-cycle-42-*.html"))
        assert html_files
        html = html_files[0].read_text()
    assert "rTreasury123" in html
    assert "Destination Tag" in html


def test_format_briefing_teaser():
    text = format_briefing_teaser({"cycle_id": 5, "factory_balance_xrp": 90.0})
    assert "Cycle 5" in text
    assert "90" in text


def test_resolve_payment_intent_destination_tag():
    payment = {"destination_tag": 1, "memos": [], "plain_memos": []}
    intent = resolve_payment_intent(payment, cycle_id=11)
    assert intent is not None
    assert intent.method == "destination_tag"
    assert intent.amount_usd_est == 1.0


def test_resolve_payment_intent_plain_memo():
    payment = {"destination_tag": None, "memos": [], "plain_memos": ["tip"]}
    intent = resolve_payment_intent(payment, cycle_id=11)
    assert intent is not None
    assert intent.method == "plain_memo"


def test_resolve_payment_intent_flat_default():
    payment = {"destination_tag": None, "memos": [], "plain_memos": []}
    intent = resolve_payment_intent(payment, cycle_id=11)
    assert intent is not None
    assert intent.method == "flat_tip_default"


def test_unmatched_inflow_without_revenue_memo(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("ECONOMIC_LEDGER_FILE", str(ledger_path))
    import observability.economic_ledger as el
    import observability.revenue_ingest as ri

    monkeypatch.setattr(el, "LEDGER_FILE", str(ledger_path))
    monkeypatch.setattr(ri, "ledger", el.EconomicLedger(str(ledger_path)))
    monkeypatch.setenv("TREASURY_FLAT_TIP_IF_BLANK", "false")
    monkeypatch.setattr(
        ri,
        "query_recent_transactions",
        lambda address, limit=20: [
            {
                "validated": True,
                "tx": {
                    "TransactionType": "Payment",
                    "Account": "rExternal",
                    "Destination": "rTreasury",
                    "Amount": "5000000",
                    "hash": "UNMATCHED1",
                    "DestinationTag": 999,
                    "Memos": [],
                },
            }
        ],
    )
    monkeypatch.setenv("FACTORY_TREASURY_ADDRESS", "rTreasury")
    monkeypatch.setattr(ri, "reconcile_unmatched_treasury_payments", lambda cycle_id: [])

    result = ri.ingest_verified_xrpl_revenue(cycle_id=99, treasury_address="rTreasury")
    assert result["ingested"] == []
    assert len(result["unmatched"]) == 1
    assert result["unmatched"][0]["event_type"] == "treasury_inflow_unmatched"
    assert result["unmatched"][0]["metadata"]["xrp_received"] == 5.0


def test_ingest_flat_tip_without_tag_or_memo(tmp_path, monkeypatch):
    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("ECONOMIC_LEDGER_FILE", str(ledger_path))
    import observability.economic_ledger as el
    import observability.revenue_ingest as ri

    monkeypatch.setattr(el, "LEDGER_FILE", str(ledger_path))
    monkeypatch.setattr(ri, "ledger", el.EconomicLedger(str(ledger_path)))
    monkeypatch.setenv("TREASURY_FLAT_TIP_IF_BLANK", "true")
    monkeypatch.setattr(ri, "reconcile_unmatched_treasury_payments", lambda cycle_id: [])
    monkeypatch.setattr(
        ri,
        "query_recent_transactions",
        lambda address, limit=20: [
            {
                "validated": True,
                "tx": {
                    "TransactionType": "Payment",
                    "Account": "rExternal",
                    "Destination": "rTreasury",
                    "Amount": "5000000",
                    "hash": "FLAT1",
                    "Memos": [],
                },
            }
        ],
    )
    monkeypatch.setenv("FACTORY_TREASURY_ADDRESS", "rTreasury")

    result = ri.ingest_verified_xrpl_revenue(cycle_id=99, treasury_address="rTreasury")
    assert len(result["ingested"]) == 1
    assert result["ingested"][0]["event_type"] == "revenue"
    assert result["ingested"][0]["amount_usd_est"] == 1.0


def test_compute_cycle_focus_forced_rotation_every_third_cycle():
    from factory_core.self_improver import compute_cycle_focus

    meta = {"ledger_trends": {"revenue_gap_usd": 9.0}, "stale_proposals": []}
    analysis = {"cycle_revenue_usd": 0, "bottlenecks": ["no_verified_revenue"]}
    assert compute_cycle_focus(cycle_id=3, analysis=analysis, meta=meta) == "rsi"
    assert compute_cycle_focus(cycle_id=1, analysis=analysis, meta=meta) == "revenue"
    assert compute_cycle_focus(cycle_id=2, analysis=analysis, meta=meta) == "tools"


def test_compute_cycle_focus_capped_revenue_weight():
    from factory_core.self_improver import compute_cycle_focus

    meta = {"ledger_trends": {"revenue_gap_usd": 9.0}, "stale_proposals": ["x"] * 5}
    analysis = {"cycle_revenue_usd": 0, "bottlenecks": ["no_verified_revenue"]}
    focus = compute_cycle_focus(cycle_id=5, analysis=analysis, meta=meta)
    assert focus in {"revenue", "tools", "rsi"}


def test_self_improvement_proposals_detect_stale():
    from factory_core.self_improver import self_improvement_proposals

    meta = {
        "focus": "rsi",
        "stale_proposals": ["Batch Vercel deploy once per cycle"],
        "ledger_trends": {"revenue_gap_usd": 5.0},
        "gate_trends": {"pass_rate": 1.0, "top_failures": []},
        "avg_pytest_duration_ms": 4000,
    }
    proposals = self_improvement_proposals(meta, {"cycle_revenue_usd": 0}, cycle_id=79)
    sources = {p["source"] for p in proposals}
    assert "self_improvement" in sources
    assert any("stale" in p["title"].lower() for p in proposals)


def test_revenue_classification_factory_adjacent():
    from observability.revenue_classification import classify_inbound_payment, enrich_revenue_metadata

    assert classify_inbound_payment("rJ2TJZ1KCx6fsshHFVK8MrvNdD1rzyXugJ") == "factory_adjacent"
    assert classify_inbound_payment("rUnknownExternal111") == "organic"
    meta = enrich_revenue_metadata({}, "rUnknownExternal111")
    assert meta["revenue_class"] == "organic"
    assert meta["organic"] is True


def test_economic_guards_circuit_breaker_and_adaptive_sleep(monkeypatch):
    from factory_core.economic_guards import (
        compute_sleep_minutes,
        continuous_run_enabled,
        evaluate_circuit_breakers,
        evaluate_success_stop,
    )

    monkeypatch.delenv("MAX_CUMULATIVE_NET_LOSS_USD", raising=False)
    monkeypatch.delenv("FACTORY_RUN_CONTINUOUS", raising=False)
    monkeypatch.setenv("MAX_CUMULATIVE_NET_LOSS_USD", "60")
    net = {"net_usd_est": -61.0, "total_revenue_usd_est": 2.0, "total_cost_usd_est": 63.0}
    stop, throttle = evaluate_circuit_breakers(net, consecutive_zero_revenue=2)
    assert stop is not None
    assert "cumulative net" in stop

    net2 = {"net_usd_est": -50.0, "total_revenue_usd_est": 10.0, "total_cost_usd_est": 60.0}
    assert evaluate_success_stop(net2, consecutive_positive_net=3) is not None

    assert compute_sleep_minutes(5, cycle_revenue_usd=0, consecutive_zero_revenue=3) >= 30

    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    assert continuous_run_enabled()
    stop_cont, throttle_cont = evaluate_circuit_breakers(
        net, consecutive_zero_revenue=10, mode="hybrid"
    )
    assert stop_cont is None
    assert throttle_cont is None

    monkeypatch.setenv("CONTINUOUS_ADAPTIVE_MAX_MINUTES", "20")
    assert compute_sleep_minutes(5, 0, 10) <= 20


def test_accelerate_treasury_surfaces_writes_outreach(tmp_path, monkeypatch):
    from tools.revenue_acceleration import write_outreach_bundle

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FACTORY_PUBLIC_BASE_URL", "https://example.test")
    (tmp_path / "published").mkdir()
    result = write_outreach_bundle(99, "rTestTreasury123", {"tip_page": "https://example.test/tip.html"})
    assert Path(result["outreach_json"]).exists()
    assert Path(result["outreach_md"]).exists()
    assert "Destination Tag" in Path(result["outreach_md"]).read_text(encoding="utf-8")


def test_factory_director_revenue_sprint_sleep(monkeypatch):
    from factory_core.director import FactoryDirector

    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    d = FactoryDirector()
    plan = d.decide_after_cycle(
        {
            "cycle_id": 148,
            "ledger_net": {
                "net_usd_est": -66.0,
                "total_revenue_usd_est": 2.0,
                "organic_revenue_usd_est": 0.0,
                "total_cost_usd_est": 68.0,
            },
            "analysis": {
                "cycle_revenue_usd": 0,
                "bottlenecks": ["no_verified_revenue"],
            },
            "execution": {},
            "gates": {"all_passed": True},
            "current_xrp_balance": 50.0,
        },
        active_mode="hybrid",
        base_interval_minutes=5,
        consecutive_negative=1,
        consecutive_zero_revenue=10,
        consecutive_positive_net=0,
    )
    assert plan.reasoning.get("director_override") == "revenue_gap_critical"
    assert plan.sleep_minutes == 5
    assert any(
        p in plan.evolution_priorities
        for p in ("accelerate_treasury_surfaces", "treasury_ingest_github")
    )


def test_factory_director_decides_mode_and_sleep(tmp_path, monkeypatch):
    from factory_core.director import FactoryDirector

    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    monkeypatch.setenv("CONTINUOUS_ADAPTIVE_MAX_MINUTES", "20")
    d = FactoryDirector()
    plan = d.decide_after_cycle(
        {
            "cycle_id": 10,
            "ledger_net": {
                "net_usd_est": -74.0,
                "total_revenue_usd_est": 2.0,
                "organic_revenue_usd_est": 0.0,
                "total_cost_usd_est": 76.0,
            },
            "analysis": {
                "cycle_revenue_usd": 0,
                "cycle_focus": "revenue",
                "bottlenecks": ["no_verified_revenue"],
            },
            "execution": {"github_distribution": {"pushed": False}},
            "gates": {"all_passed": True},
            "current_xrp_balance": 50.0,
        },
        active_mode="hybrid",
        base_interval_minutes=5,
        consecutive_negative=3,
        consecutive_zero_revenue=4,
        consecutive_positive_net=0,
    )
    assert plan.stop_reason is None
    assert plan.mode == "hybrid"
    assert plan.cycle_id_next == 11
    assert plan.sleep_minutes <= 20
    assert "treasury_ingest_github" in plan.evolution_priorities or plan.focus == "revenue"


def test_grok_usage_factory_turn_filter():
    from observability.grok_usage import TurnUsage, is_billable_factory_turn

    assert is_billable_factory_turn(
        TurnUsage("task-completed-abc", 100, 100, "Checking in", True)
    )
    assert not is_billable_factory_turn(
        TurnUsage("user-1", 100, 100, "Checking in.", True)
    )
    assert is_billable_factory_turn(
        TurnUsage("evo-1", 100, 100, "RSI-EAF cycle 99 executable evolution", True)
    )


def test_stale_evolution_filters_builtin_implemented():
    from factory_core.stale_evolution import (
        BUILTIN_IMPLEMENTED,
        filter_stale_proposals,
        is_proposal_implemented,
    )

    stale = list(BUILTIN_IMPLEMENTED) + ["Refresh live tip surfaces on Vercel"]
    filtered = filter_stale_proposals(stale)
    assert "Batch Vercel deploy once per cycle" not in filtered
    assert "Refresh live tip surfaces on Vercel" in filtered
    assert is_proposal_implemented("Batch Vercel deploy once per cycle")


def test_runner_lock_prevents_duplicate_holder(tmp_path, monkeypatch):
    from factory_core import runner_lock

    lock_path = tmp_path / "runner.lock"
    monkeypatch.setattr(runner_lock, "LOCK_FILE", lock_path)
    lock_path.write_text("999999\n", encoding="utf-8")
    monkeypatch.setattr(runner_lock, "_pid_alive", lambda pid: pid == 999999)
    assert runner_lock.acquire_runner_lock() is False
    monkeypatch.setattr(runner_lock, "_pid_alive", lambda pid: False)
    assert runner_lock.acquire_runner_lock() is True


def test_pytest_env_isolation_from_runner_ceiling(monkeypatch):
    from factory_core.tool_improver import _isolated_pytest_env

    monkeypatch.setenv("MAX_CUMULATIVE_NET_LOSS_USD", "100")
    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    monkeypatch.setenv("CYCLE_MODE", "hybrid")
    monkeypatch.setenv("FACTORY_RUNNER_ACTIVE", "true")
    env = _isolated_pytest_env()
    assert "MAX_CUMULATIVE_NET_LOSS_USD" not in env
    assert "FACTORY_RUN_CONTINUOUS" not in env
    assert "CYCLE_MODE" not in env
    assert "FACTORY_RUNNER_ACTIVE" not in env


def test_backfill_revenue_classification(tmp_path, monkeypatch):
    from observability.ledger_hygiene import backfill_revenue_classification
    import observability.economic_ledger as el
    import observability.ledger_hygiene as lh

    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(el, "LEDGER_FILE", str(ledger_path))
    monkeypatch.setattr(lh, "ledger", el.EconomicLedger(str(ledger_path)))
    led = el.EconomicLedger(str(ledger_path))
    led.log_verified_revenue(
        "xrpl_inbound_payment",
        1.0,
        cycle_id=11,
        xrpl_tx_hash="BACKFILL1",
        verification_method="test",
        metadata={"from_address": "rJ2TJZ1KCx6fsshHFVK8MrvNdD1rzyXugJ", "verified": True},
    )
    updated = backfill_revenue_classification()
    assert len(updated) == 1
    assert updated[0]["revenue_class"] == "factory_adjacent"
    net = led.calculate_net()
    assert net["factory_adjacent_revenue_usd_est"] == 1.0


def test_raised_ceiling_requires_revenue_action(monkeypatch):
    from factory_core.economic_guards import evaluate_raised_ceiling_revenue_action

    monkeypatch.setenv("MAX_CUMULATIVE_NET_LOSS_USD", "100")
    net = {"net_usd_est": -65.0, "total_revenue_usd_est": 2.0}
    stop = evaluate_raised_ceiling_revenue_action(net, {"skipped": True})
    assert stop is not None
    assert "requires" in stop
    assert evaluate_raised_ceiling_revenue_action(net, {"pushed": True}) is None


def test_calculate_net_organic_split(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    led = EconomicLedger(ledger_path=str(ledger_path))
    led.log_verified_revenue(
        "xrpl_inbound_payment",
        1.0,
        cycle_id=1,
        xrpl_tx_hash="ORG1",
        verification_method="test",
        metadata={"revenue_class": "organic", "organic": True, "verified": True},
    )
    led.log_verified_revenue(
        "xrpl_inbound_payment",
        1.0,
        cycle_id=2,
        xrpl_tx_hash="ADJ1",
        verification_method="test",
        metadata={"revenue_class": "factory_adjacent", "verified": True},
    )
    led.log_event("cost", "grok", 5.0, cycle_id=1, anchor_to_xrpl=False)
    net = led.calculate_net()
    assert net["total_revenue_usd_est"] == 2.0
    assert net["organic_revenue_usd_est"] == 1.0
    assert net["factory_adjacent_revenue_usd_est"] == 1.0


def test_analyze_improvement_history_reads_tool_log(tmp_path, monkeypatch):
    from factory_core import self_improver as si

    log = tmp_path / "tool_improvements.jsonl"
    entry = {
        "timestamp": "2026-06-28T00:00:00+00:00",
        "cycle_id": 1,
        "pytest": {"passed": True, "duration_ms": 100},
        "xrpl": {"ok": True},
    }
    log.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    monkeypatch.setattr(si, "IMPROVEMENTS_LOG", log)

    result = si.analyze_improvement_history()
    assert "tool_cycles_logged" in result
    assert "ledger_trends" in result
    assert result["tool_cycles_logged"] >= 1


def test_assemble_factory_wave_structure():
    from tools.nexus_bridge import assemble_factory_wave, merge_nexus_data, merge_control_state

    cycle_result = {
        "cycle_id": 42,
        "success": True,
        "execution": {
            "cycle_mode": "hybrid",
            "treasury_address": "rTreasury",
            "featured_surfaces": {"tip_page": "https://example.com/tip"},
            "github_distribution": {"pushed": False},
            "live_url": "https://published-zeta.vercel.app/",
            "live_verified": True,
        },
        "analysis": {"cycle_focus": "revenue", "cycle_revenue_usd": 0, "bottlenecks": []},
        "gates": {"all_passed": True, "passed_count": 5, "total_count": 5},
        "ledger_net": {"net_usd_est": -10.0, "total_revenue_usd_est": 2.0, "organic_revenue_usd_est": 0},
        "proposals": [],
        "evolution": {},
        "factory_state": {"current_cycle": 42},
    }
    wave = assemble_factory_wave(cycle_result)
    assert wave["rsi_eaf_factory"]["cycle_id"] == 42
    assert "control_state_goals" in wave["rsi_eaf_factory"]
    merged = merge_nexus_data({"version": "nexus-template-v1.0"}, wave)
    assert merged["rsi_eaf_factory"]["cycle_id"] == 42
    assert "rsi_eaf_last_emit" in merged
    control = merge_control_state({"status": "running"}, wave)
    assert control["rsi_eaf_runner"]["cycle_id"] == 42
    assert control["rsi_eaf_runner"]["aetherforge_linked"] is True


def test_github_client_push_files_no_token(monkeypatch):
    from tools.github_client import push_files

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    result = push_files("theCeramist", "rsi-eaf", [{"path": "x", "content": "y"}], "test")
    assert result.get("skipped") is True


def test_merge_nexus_includes_gist_url():
    from tools.nexus_bridge import assemble_factory_wave, merge_nexus_data

    wave = assemble_factory_wave({
        "cycle_id": 1,
        "success": True,
        "execution": {
            "github_distribution": {
                "gist": {"gist_url": "https://gist.github.com/x"},
            },
        },
        "analysis": {},
        "gates": {"all_passed": True},
        "ledger_net": {},
        "factory_state": {},
    })
    merged = merge_nexus_data({}, wave)
    assert merged["rsi_eaf_factory"]["github"]["gist_url"] == "https://gist.github.com/x"


def test_canonical_tip_prefers_current_cycle(tmp_path, monkeypatch):
    from tools import distribution_tools as dt

    monkeypatch.setattr(dt, "PUBLISHED_DIR", tmp_path)
    monkeypatch.setattr(dt, "FACTORY_PUBLIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("FACTORY_PUBLIC_BASE_URL", "https://example.com")
    monkeypatch.setenv("PREFER_CURRENT_CYCLE_TIP", "true")
    (tmp_path / "tip-cycle-99-old.html").write_text("<html></html>")
    (tmp_path / "tip-cycle-200-new.html").write_text("<html></html>")

    def fake_verify(url):
        return "tip-cycle-99" in url

    monkeypatch.setattr("tools.publish_tools.verify_live_url", fake_verify)
    url = dt.canonical_tip_url(200)
    assert url == "https://example.com/tip-cycle-200-new.html"


def test_github_ci_gate_disabled(monkeypatch):
    from tools.github_ci_gate import block_distribution_if_ci_red

    monkeypatch.setenv("GITHUB_CI_GATE", "false")
    assert block_distribution_if_ci_red() is None


def test_treasury_daemon_drain_roundtrip(tmp_path, monkeypatch):
    from observability import treasury_daemon as td

    inbox = tmp_path / "inbox.jsonl"
    monkeypatch.setattr(td, "INBOX_FILE", inbox)
    td._append_inbox({"tx_hash": "ABC", "from": "rExt"})
    drained = td.drain_inbox()
    assert len(drained) == 1
    assert td.drain_inbox() == []


def test_init_runner_acp_disabled(monkeypatch):
    from factory_core import grok_acp

    monkeypatch.setenv("GROK_ORCHESTRATION", "subprocess")
    result = grok_acp.init_runner_acp()
    assert result.get("started") is False


def test_run_parallel_analysis_routes_acp(monkeypatch):
    from factory_core import grok_cli

    calls = []

    def fake_acp(cycle_id, prompt, factory_state=None):
        calls.append((cycle_id, prompt[:40]))
        return {"mode": "acp", "cycle_id": cycle_id}

    monkeypatch.setenv("GROK_ORCHESTRATION", "acp")
    monkeypatch.setenv("GROK_PARALLEL_ANALYSIS", "true")
    monkeypatch.setattr("factory_core.grok_acp.run_cycle_via_acp", fake_acp)
    grok_cli.run_parallel_analysis(7, {"cycle_revenue_usd": 0})
    assert calls and calls[0][0] == 7


def test_grok_evolution_best_of_n_flag(monkeypatch):
    from factory_core import grok_cli

    calls = []

    def fake_headless(*args, **kwargs):
        calls.append(kwargs.get("extra_args") or [])
        return {"executed": False, "skipped": True}

    monkeypatch.setenv("GROK_ORCHESTRATION", "subprocess")
    monkeypatch.setattr(grok_cli, "run_headless", fake_headless)
    grok_cli.run_evolution_task(1, "test task", best_of_n=3)
    assert any("--best-of-n" in str(c) for c in calls)


def test_nexus_ci_block(monkeypatch):
    import tools.github_ci_gate as ci_gate
    from tools import nexus_bridge as nb

    monkeypatch.setenv("NEXUS_EMIT_ENABLED", "true")
    monkeypatch.setattr(ci_gate, "block_distribution_if_ci_red", lambda **k: "CI failed")
    result = nb.maybe_emit_nexus({"cycle_id": 5, "execution": {}, "analysis": {}, "gates": {}})
    assert result.get("ci_blocked") is True


def test_triage_payment_friction_no_token(monkeypatch):
    from tools.github_semantic_triage import triage_payment_friction

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    result = triage_payment_friction()
    assert "searches" in result


def test_grok_cli_unavailable():
    from factory_core import grok_cli

    result = grok_cli.run_headless("test", mode="plan")
    if not grok_cli.GROK_BIN or not __import__("pathlib").Path(grok_cli.GROK_BIN).exists():
        assert result.get("skipped") or result.get("executed") is False


def test_maybe_emit_nexus_respects_disabled(monkeypatch):
    from tools.nexus_bridge import maybe_emit_nexus

    monkeypatch.setenv("NEXUS_EMIT_ENABLED", "false")
    result = maybe_emit_nexus({"cycle_id": 1, "execution": {}, "analysis": {}, "gates": {}})
    assert result["skipped"] is True
    assert result["reason"] == "NEXUS_EMIT_DISABLED"


def test_extract_payment_fields_revenue_memo():
    memo_json = '{"type":"revenue","amount_usd_est":2.5,"notes":"tip"}'
    entry = {
        "validated": True,
        "tx": {
            "TransactionType": "Payment",
            "Account": "rExternal",
            "Destination": "rTreasury",
            "Amount": "5000000",
            "hash": "REV123",
            "Memos": [{"Memo": {"MemoData": memo_json.encode("utf-8").hex().upper()}}],
        },
    }
    payment = _extract_payment_fields(entry)
    assert payment is not None
    assert payment["tx_hash"] == "REV123"
    assert payment["memos"][0]["amount_usd_est"] == 2.5