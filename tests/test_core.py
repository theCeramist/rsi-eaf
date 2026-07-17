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


def test_ledger_verified_revenue_survives_cost_window(tmp_path):
    """Verified revenue must not disappear when recent rows are mostly costs."""
    ledger_path = tmp_path / "ledger.jsonl"
    led = EconomicLedger(ledger_path=str(ledger_path))
    led.log_verified_revenue(
        "xrpl_inbound_payment",
        2.0,
        cycle_id=1,
        xrpl_tx_hash="ABC123",
        verification_method="xrpl_treasury_flat_tip_default",
        metadata={"organic": True, "revenue_class": "organic"},
    )
    for i in range(1200):
        led.log_event("cost", "grok", 0.01, cycle_id=100 + i, anchor_to_xrpl=False)
    assert led.count_verified_revenue_events() == 1
    net = led.calculate_net()
    assert net["organic_revenue_usd_est"] == 2.0


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
    assert should_run_revenue_sprint(5.0, consecutive_zero=2) is True


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
    (tmp_path / "services-cycle-99-x.html").write_text("svc", encoding="utf-8")
    (tmp_path / "index.html").write_text("idx", encoding="utf-8")
    result = ph.prune_published_for_deploy(cycle_id=99, max_html=8)
    assert result["archived_count"] >= 1
    assert (tmp_path / "tip-cycle-99-new.html").exists()
    assert (tmp_path / "services-cycle-99-x.html").exists()
    assert not (tmp_path / "tip-cycle-1-old.html").exists()


def test_published_asset_gate_accepts_archive_and_live(tmp_path, monkeypatch):
    from gates.verifier import _published_assets_resolvable, run_cycle_gates

    monkeypatch.setenv("PUBLISHED_DIR", str(tmp_path))
    arch = tmp_path / "archive"
    arch.mkdir()
    name = "tip-cycle-50-x.html"
    (arch / name).write_text("tip", encoding="utf-8")
    ok, detail = _published_assets_resolvable(
        [str(tmp_path / name)],
        {},
    )
    assert ok, detail
    assert "archive" in detail or "resolved" in detail

    ok2, detail2 = _published_assets_resolvable(
        ["published/missing.html"],
        {"live_verified": True, "live_url": "https://example.com/tip"},
    )
    assert ok2, detail2

    # Stable surface after prune (tip-manifest / index still on disk)
    (tmp_path / "tip-manifest.json").write_text("{}", encoding="utf-8")
    ok3, detail3 = _published_assets_resolvable(
        ["published/missing-cycle.html"],
        {"live_verified": False},
    )
    assert ok3, detail3
    assert "stable_surface" in detail3

    # Full gate path with archived asset
    import gates.verifier as gv

    monkeypatch.setattr(gv, "PUBLISHED_DIR", str(tmp_path))
    result = run_cycle_gates(
        50,
        {
            "published_assets": [str(tmp_path / name)],
            "live_verified": False,
            "cycle_mode": "revenue",
        },
    )
    pub_gate = next(g for g in result["gates"] if g["gate"] == "published_asset_exists")
    assert pub_gate["passed"] is True


def test_pytest_cache_reuse_continuous(tmp_path, monkeypatch):
    from factory_core import pytest_cache as pc

    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    monkeypatch.setenv("TOOL_GATE_PYTEST_EVERY_N", "3")
    monkeypatch.setenv("FACTORY_PYTEST_CACHE_FILE", str(tmp_path / "pytest_gate_cache.json"))
    pc._cache.clear()
    pc.set_pytest_result(100, {"passed": True, "exit_code": 0, "duration_ms": 10, "output_tail": "ok"})
    reused = pc.get_reusable_pytest_result(101)
    assert reused is not None
    assert reused.get("reused_from_cycle") == 100
    assert pc.get_reusable_pytest_result(103) is None  # age 3 >= every_n
    assert pc.tool_gate_pytest_every_n() == 3


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
    assert "python3 scripts/aetherforge_deploy_gate.py" in _WORKFLOW
    assert "name: Nexus Portal CI/CD" in _WORKFLOW
    assert "${{ secrets.VERCEL_TOKEN }}" in _WORKFLOW
    assert "AETHERFORGE_DEPLOY_HOOK_URL" in _WORKFLOW
    assert "notify:" not in _WORKFLOW
    assert "${{{{" not in _WORKFLOW
    for line in _WORKFLOW.splitlines():
        if line.startswith("import ") or line.startswith("from "):
            raise AssertionError(f"unindented python in workflow YAML: {line!r}")


def test_aetherforge_publish_deploy_hook_when_stale(monkeypatch):
    from tools import aetherforge_publish as af

    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    monkeypatch.setenv("AETHERFORGE_DEPLOY_HOOK_URL", "https://api.vercel.com/v1/integrations/deploy/hook/test")
    monkeypatch.setattr(
        "httpx.post",
        lambda url, **kw: calls.append(url) or FakeResponse(),
    )
    monkeypatch.setattr(
        af,
        "verify_aetherforge_freshness",
        lambda *a, **k: {"fresh": False, "live_cycle_id": 1, "expected_cycle_id": 42},
    )
    monkeypatch.setattr(
        af,
        "trigger_vercel_git_deploy",
        lambda: {"success": False, "skipped": True, "reason": "test"},
    )
    monkeypatch.setenv("AETHERFORGE_VERIFY_DELAY_SEC", "0")
    result = af.publish_aetherforge(42, local_paths={}, git_push_ok=True)
    assert result["deploy"]["success"] is True
    assert calls


def test_aetherforge_publish_skips_hook_when_fresh(monkeypatch):
    from tools import aetherforge_publish as af

    monkeypatch.setenv("AETHERFORGE_DEPLOY_HOOK_URL", "https://api.vercel.com/v1/integrations/deploy/hook/test")
    monkeypatch.setattr(
        af,
        "verify_aetherforge_freshness",
        lambda *a, **k: {"fresh": True, "live_cycle_id": 42, "expected_cycle_id": 42},
    )
    result = af.publish_aetherforge(42, local_paths={}, git_push_ok=True)
    assert result["deploy"]["reason"] == "already_fresh"


def test_aetherforge_publish_hooks_when_one_cycle_behind(monkeypatch):
    from tools import aetherforge_publish as af

    calls = []

    class FakeResponse:
        status_code = 200
        text = "ok"

    monkeypatch.setenv("AETHERFORGE_DEPLOY_HOOK_URL", "https://api.vercel.com/v1/integrations/deploy/hook/test")
    monkeypatch.setattr("httpx.post", lambda url, **kw: calls.append(url) or FakeResponse())
    def _freshness(cid, **k):
        if k.get("strict"):
            return {"fresh": False, "live_cycle_id": cid - 1, "expected_cycle_id": cid}
        return {"fresh": True, "live_cycle_id": cid, "expected_cycle_id": cid}

    monkeypatch.setattr(af, "verify_aetherforge_freshness", _freshness)
    monkeypatch.setattr(
        af,
        "trigger_vercel_git_deploy",
        lambda: {"success": False, "skipped": True, "reason": "test"},
    )
    monkeypatch.setenv("AETHERFORGE_VERIFY_DELAY_SEC", "0")
    result = af.publish_aetherforge(712, local_paths={}, git_push_ok=True)
    assert result["deploy"]["success"] is True
    assert calls


def test_nexus_ci_gate_disabled_by_default(monkeypatch):
    from tools.github_ci_gate import block_distribution_if_ci_red

    monkeypatch.delenv("NEXUS_CI_GATE_ENABLED", raising=False)
    monkeypatch.setenv("GITHUB_CI_GATE", "true")
    assert block_distribution_if_ci_red(owner="theCeramist", repo="jarvis-swarm") is None


def test_aetherforge_mirror_writes_files(tmp_path, monkeypatch):
    from tools import aetherforge_publish as af

    monkeypatch.setattr(af, "MIRROR_DIR", tmp_path)
    src = tmp_path / "src.json"
    src.write_text('{"cycle": 1}', encoding="utf-8")
    out = af.mirror_nexus_files({"control_state": str(src)})
    assert out["mirrored"] == 1
    assert (tmp_path / "control-state.json").exists()


def test_hygiene_never_started_detects_actions_infra():
    from tools.nexus_ci_runner_watch import hygiene_never_started

    assert hygiene_never_started(
        {"success": True, "conclusion": "failure", "step_count": 0, "runner_id": 0}
    )
    assert not hygiene_never_started(
        {"success": True, "conclusion": "success", "step_count": 3, "runner_id": 99}
    )


def test_payment_status_index_from_ledger(tmp_path, monkeypatch):
    from observability import payment_status_index as psi
    from observability.economic_ledger import EconomicLedger

    ledger_path = tmp_path / "ledger.jsonl"
    pub = tmp_path / "published"
    monkeypatch.setattr(psi, "PUBLISHED_DIR", pub)
    monkeypatch.setattr(psi, "PAYMENT_STATUS_FILE", pub / "payment-status.json")

    led = EconomicLedger(ledger_path=str(ledger_path))
    monkeypatch.setattr(psi, "ledger", led)
    led.log_verified_revenue(
        "xrpl_inbound_payment",
        1.0,
        cycle_id=9,
        xrpl_tx_hash="HASH9",
        verification_method="xrpl_treasury_flat_tip_default",
        metadata={"organic": True, "from_address": "rExt"},
    )
    path = psi.write_payment_status_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["summary"]["total_verified"] == 1
    assert data["payments"][0]["tx_hash"] == "HASH9"


def test_nexus_runner_blocked_reads_state(tmp_path, monkeypatch):
    from tools import nexus_ci_runner_watch as watch

    state_path = tmp_path / "nexus_ci_runner_state.json"
    monkeypatch.setattr(watch, "STATE_FILE", state_path)
    monkeypatch.setenv("NEXUS_RUNNER_WATCH_ENABLED", "true")
    assert not watch.nexus_runners_blocked()
    watch.save_runner_state({"runner_unavailable": True, "runner_available": False})
    assert watch.nexus_runners_blocked()


def test_nexus_ci_repair_gated_on_hygiene_only():
    from tools.jarvis_swarm_ci_repair import nexus_ci_needs_hygiene_repair

    assert not nexus_ci_needs_hygiene_repair(
        {"success": True, "conclusion": "failure", "hygiene_pass": True, "effective_conclusion": "success"}
    )
    assert nexus_ci_needs_hygiene_repair(
        {"success": True, "conclusion": "failure", "hygiene_pass": False, "effective_conclusion": "failure"}
    )
    assert not nexus_ci_needs_hygiene_repair(
        {"success": True, "conclusion": "success", "hygiene_pass": False, "effective_conclusion": "success"}
    )


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


def test_compute_cycle_focus_forced_rotation_every_third_cycle(monkeypatch):
    from factory_core.self_improver import compute_cycle_focus

    monkeypatch.setattr(
        "factory_core.fitness_evolution.fitness_is_failing",
        lambda report=None: False,
    )
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
        "stale_proposals": ["Execute top fitness recommendation"],
        "ledger_trends": {"revenue_gap_usd": 5.0},
        "gate_trends": {"pass_rate": 1.0, "top_failures": []},
        "avg_pytest_duration_ms": 4000,
    }
    proposals = self_improvement_proposals(meta, {"cycle_revenue_usd": 0}, cycle_id=79)
    sources = {p["source"] for p in proposals}
    assert "self_improvement" in sources
    assert any("stale" in p["title"].lower() for p in proposals)


def test_self_improvement_skips_builtin_and_meta_stale():
    from factory_core.self_improver import self_improvement_proposals

    meta = {
        "focus": "rsi",
        "stale_proposals": ["Batch Vercel deploy once per cycle"],
        "ledger_trends": {"revenue_gap_usd": 0},
        "gate_trends": {"pass_rate": 1.0, "top_failures": []},
        "avg_pytest_duration_ms": 6000,
    }
    proposals = self_improvement_proposals(meta, {"cycle_revenue_usd": 0}, cycle_id=80)
    titles = [p["title"] for p in proposals]
    assert not any(t.startswith("Diversify beyond stale proposal:") for t in titles)
    assert "Optimize pytest suite duration" not in titles


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
    assert plan.reasoning.get("director_override") in {
        "fitness_revenue_capture",
        "revenue_gap_critical",
    }
    assert plan.focus == "revenue"
    assert plan.sleep_minutes == 5
    assert "fitness_revenue_capture" in plan.evolution_priorities or any(
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
        has_deterministic_resolver,
        is_meta_proposal_title,
        is_proposal_implemented,
        normalize_priority_list,
        translate_priority,
    )

    stale = list(BUILTIN_IMPLEMENTED) + ["Refresh live tip surfaces on Vercel"]
    filtered = filter_stale_proposals(stale)
    assert "Batch Vercel deploy once per cycle" not in filtered
    assert "Refresh live tip surfaces on Vercel" in filtered
    assert is_proposal_implemented("Batch Vercel deploy once per cycle")
    assert is_meta_proposal_title("Diversify beyond stale proposal: Throttle Grok spend")
    assert translate_priority("daily_review:Throttle Grok spend; prioritize zero-cost revenue surfaces") == (
        "throttle_grok_spend"
    )
    assert translate_priority("Execute top fitness recommendation") == "fitness_revenue_capture"
    assert normalize_priority_list(
        ["daily_review:Surgical gate remediation", "fitness_revenue_capture"]
    ) == ["surgical_gate_remediation", "fitness_revenue_capture"]
    assert has_deterministic_resolver("Throttle Grok spend; prioritize zero-cost revenue surfaces")
    assert has_deterministic_resolver("Optimize pytest suite duration")


def test_stale_evolution_throttle_and_optimize_resolvers():
    from factory_core.stale_evolution import (
        _resolve_optimize_pytest,
        _resolve_throttle_grok_spend,
    )

    throttle = _resolve_throttle_grok_spend(42)
    assert throttle["implemented"] is True
    assert throttle["action"] == "throttle_grok_spend"
    assert os.environ.get("DIRECTOR_ALLOW_GROK_EVOLUTION") == "false"

    optimize = _resolve_optimize_pytest(42)
    assert optimize["action"] == "optimize_pytest"
    assert optimize.get("marker_active") is True


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
    assert "tool_log_analytics" in result
    assert "pytest_duration_trend_ms" in result["tool_log_analytics"]


def test_compute_tool_log_analytics_duration_trend():
    """Drive shipped pure analytics: recent half slower → positive trend."""
    from factory_core.self_improver import compute_tool_log_analytics

    entries = [
        {"pytest": {"passed": True, "duration_ms": 100.0}},
        {"pytest": {"passed": True, "duration_ms": 200.0}},
        {"pytest": {"passed": True, "duration_ms": 300.0}},
        {"pytest": {"passed": True, "duration_ms": 400.0}},
        {"phase": "evolve_tools", "proposals_applied": 0},  # non-pytest row ignored
    ]
    analytics = compute_tool_log_analytics(entries)
    assert analytics["pytest_duration_samples"] == 4
    assert analytics["min_pytest_duration_ms"] == 100.0
    assert analytics["max_pytest_duration_ms"] == 400.0
    # older half avg=150, recent half avg=350 → trend +200
    assert analytics["pytest_duration_trend_ms"] == 200.0


def test_x402_publish_well_known(tmp_path, monkeypatch):
    from observability import x402_publish as xp

    monkeypatch.setattr(xp, "PUBLISHED_DIR", tmp_path)
    monkeypatch.setattr(xp, "WELL_KNOWN_DIR", tmp_path / ".well-known")
    monkeypatch.setenv("FACTORY_PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.setenv("X402_PHASE", "1")
    manifest = {
        "cycle_id": 42,
        "factory": "RSI-EAF",
        "treasury_address": "rTreasury123",
        "discovery_urls": {"factory_index": "https://example.test"},
        "products": [
            {
                "id": "briefing_unlock",
                "destination_tag": 2,
                "credited_usd": 2.0,
                "product_id": "briefing-cycle-42",
                "description": "Briefing",
                "fulfillment_url": "https://example.test/deliverables/briefing-cycle-42.json",
            }
        ],
    }
    paths = xp.write_x402_surfaces(manifest)
    assert paths["well_known_x402"].exists()
    well = json.loads(paths["well_known_x402"].read_text(encoding="utf-8"))
    assert well["name"] == "RSI-EAF Factory"
    assert len(well["resources"]) == 1
    enriched = json.loads(paths["agent_pay"].read_text(encoding="utf-8"))
    assert enriched["products"][0]["x402"]["enabled"] is True


def test_maybe_register_xrpl_ai_hub_skips_same_cycle(monkeypatch, tmp_path):
    from tools import xrpl_ai_hub_register as reg

    monkeypatch.setattr(reg, "REGISTRATION_STATE", tmp_path / "reg.json")
    monkeypatch.setenv("XRPL_AI_REGISTER_ENABLED", "true")
    (tmp_path / "reg.json").write_text(
        json.dumps({"registered": True, "cycle_id": 99, "registered_count": 2}),
        encoding="utf-8",
    )
    result = reg.maybe_register_xrpl_ai_hub(99)
    assert result["skipped"] is True
    assert result["reason"] == "already_registered_this_cycle"


def test_maybe_register_xrpl_ai_hub_calls_register(monkeypatch, tmp_path):
    from tools import xrpl_ai_hub_register as reg

    monkeypatch.setattr(reg, "REGISTRATION_STATE", tmp_path / "reg.json")
    monkeypatch.setenv("XRPL_AI_REGISTER_ENABLED", "true")
    calls = []

    def fake_register(**kwargs):
        calls.append(kwargs)
        return {
            "registered": True,
            "registered_count": 2,
            "cycle_id": kwargs.get("cycle_id"),
            "hub_merchant_url": "https://xrpl-ai.org/address/rTest",
            "preflight": {"ok": True},
            "verify": {"success": True},
        }

    monkeypatch.setattr(reg, "register_rsi_eaf_on_xrpl_ai_hub", fake_register)
    result = reg.maybe_register_xrpl_ai_hub(100, execution={"vercel_deploy": {"success": True}})
    assert result["registered"] is True
    assert calls[0]["deploy"] is False


def test_run_platform_sync_includes_xrpl_ai(monkeypatch):
    from tools import nexus_bridge as nb

    monkeypatch.setattr(
        "tools.github_distribution.maybe_push_distribution",
        lambda **kwargs: {"pushed": False},
    )
    monkeypatch.setattr(nb, "maybe_emit_nexus", lambda *a, **k: {"emitted": False})
    monkeypatch.setattr(nb, "verify_external_surfaces", lambda: {"all_ok": True})
    monkeypatch.setattr(
        "tools.xrpl_ai_hub_register.maybe_register_xrpl_ai_hub",
        lambda *a, **k: {"registered": True, "registered_count": 2},
    )
    monkeypatch.setattr(
        "tools.product_surface_sync.verify_product_surfaces_live",
        lambda cycle_id: {"total": 2, "live_count": 2, "slo_met": True},
    )
    result = nb.run_platform_sync({"cycle_id": 50, "execution": {"featured_surfaces": {}}})
    assert result["xrpl_ai_hub"]["registered"] is True
    assert result["surface_slo"]["slo_met"] is True


def test_xrpl_ai_listing_alignment():
    from tools import product_surface_sync as pss
    from tools import xrpl_ai_hub_register as reg

    prior = reg.load_registration_state()
    cycle_id = int(prior.get("cycle_id") or 0)
    if not prior.get("registered") or not cycle_id:
        return
    listing = pss.verify_xrpl_ai_listing_alignment(cycle_id)
    assert listing["aligned"] is True


def test_xrpl_ai_hub_register_verify_mock(monkeypatch, tmp_path):
    from tools import xrpl_ai_hub_register as reg

    monkeypatch.setattr(reg, "REGISTRATION_STATE", tmp_path / "reg.json")

    class FakeResponse:
        status_code = 200

        @property
        def content(self):
            return b'{"success":true,"registeredCount":2}'

        def json(self):
            return {"success": True, "registeredCount": 2}

    monkeypatch.setattr("httpx.post", lambda *a, **k: FakeResponse())
    result = reg.verify_x402_origin("https://example.test", name="RSI-EAF")
    assert result["success"] is True
    assert result["response"]["registeredCount"] == 2


def test_xrpl_ai_hub_parse_stats_and_settlements():
    from tools.xrpl_ai_hub_ingest import parse_hub_stats, parse_live_settlements

    html = """
    <html><body>
    <h3>XRP settled</h3><div>XRP settled ▲ 95% 3107.38 XRP</div>
    <h3>RLUSD settled</h3><div>RLUSD settled ▼ 24% 1532.14 RLUSD</div>
    <a href="/transactions">Transactions ▲ 78% 1,064,240</a>
    <a href="/directory">140 live x402 services</a>
    <a href="/tx/AA4E69F123602D308B19F5299B7C56D63400B3A56E45B45D9EDA16C567AE703A">
      0.002 RLUSD Verified Verifiable Intent
    </a>
    <a href="/address/rMPwy3Ntx56Nyc2fKGNm7VRWdmpHSB92Z7">Heurist Mesh</a>
    </body></html>
    """
    stats = parse_hub_stats(html)
    assert stats["xrp_settled"] == 3107.38
    assert stats["rlusd_settled"] == 1532.14
    assert stats["transactions_indexed"] == 1064240
    assert stats["directory_services"] == 140
    txs = parse_live_settlements(html, limit=5)
    assert txs[0]["tx_hash"].startswith("AA4E69")
    assert txs[0]["verified_intent"] is True


def test_xrpl_ai_hub_ingest_persists(tmp_path, monkeypatch):
    from tools import xrpl_ai_hub_ingest as hub

    monkeypatch.setattr(hub, "HUB_INTEL_FILE", tmp_path / "hub.jsonl")
    monkeypatch.setattr(hub, "HUB_LATEST_FILE", tmp_path / "hub_latest.json")
    monkeypatch.setattr(hub, "HUB_PUBLISH_FILE", tmp_path / "publish.json")
    sample = "<html><body><h3>XRP settled</h3><div>100.5 XRP</div></body></html>"
    monkeypatch.setattr(hub, "_fetch", lambda path: sample)
    result = hub.ingest_xrpl_ai_hub(cycle_id=42)
    assert result["ok"] is True
    assert (tmp_path / "hub_latest.json").exists()
    assert hub.latest_hub_intel().get("cycle_id") == 42


def test_build_nexus_ui_heartbeat_cycle():
    from tools.aetherforge_nexus_ui import build_runner_heartbeat, build_landing
    from tools.nexus_bridge import assemble_factory_wave

    wave = assemble_factory_wave(
        {
            "cycle_id": 712,
            "success": True,
            "execution": {"treasury_address": "rTest", "featured_surfaces": {}},
            "analysis": {"cycle_focus": "revenue"},
            "gates": {"all_passed": True, "passed_count": 5, "total_count": 5},
            "ledger_net": {"net_usd_est": -10.0, "organic_revenue_usd_est": 2.0},
            "factory_state": {},
        }
    )
    hb = build_runner_heartbeat(wave)
    assert hb["factory_cycle_id"] == 712
    assert "712" in hb["wave"]
    landing = build_landing(wave)
    assert "712" in landing["status_line"]


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
    assert url == "https://example.com/tip-cycle-99-old.html"


def test_canonical_tip_falls_through_to_live_tip(tmp_path, monkeypatch):
    from tools import distribution_tools as dt

    monkeypatch.setattr(dt, "PUBLISHED_DIR", tmp_path)
    monkeypatch.setattr(dt, "FACTORY_PUBLIC_BASE_URL", "https://example.com")
    (tmp_path / "tip-cycle-50-dead.html").write_text("<html></html>")
    (tmp_path / "tip-cycle-99-live.html").write_text("<html></html>")

    def fake_verify(url):
        return "tip-cycle-99-live" in url

    monkeypatch.setattr("tools.publish_tools.verify_live_url", fake_verify)
    url = dt.canonical_tip_url(50)
    assert url == "https://example.com/tip-cycle-99-live.html"


def test_gates_evolution_allowed_on_live_url_only_fail():
    from gates.verifier import gates_evolution_allowed

    gate_result = {
        "gates": [
            {"gate": "tool_pytest_passed", "passed": True},
            {"gate": "live_url_reachable", "passed": False},
            {"gate": "verified_revenue_pipeline", "passed": False},
        ]
    }
    assert gates_evolution_allowed(gate_result) is True


def test_resolve_live_url_fallback_chain(monkeypatch):
    from gates import verifier as gv

    calls = []

    def fake_verify(url):
        calls.append(url)
        return url.endswith("/tip-manifest.json")

    monkeypatch.setattr("tools.publish_tools.verify_live_url", fake_verify)
    ok, detail = gv.resolve_live_url_reachable(
        {
            "live_url": "https://published-zeta.vercel.app/cycle-1.html",
            "featured_surfaces": {"tip_page": "https://published-zeta.vercel.app/tip-dead.html"},
            "live_urls": ["https://published-zeta.vercel.app/other.html"],
        }
    )
    assert ok is True
    assert "fallback" in detail or "tip-manifest" in detail


def test_format_agents_for_cli_map_shape():
    from factory_core.grok_cli import format_agents_for_cli

    payload = format_agents_for_cli(
        [{"name": "scout", "type": "explore", "prompt": "find revenue"}]
    )
    assert "scout" in payload
    assert payload["scout"]["type"] == "explore"
    assert isinstance(payload, dict)


def test_grok_budget_ok_respects_spend(monkeypatch):
    from observability import cost_tracker as ct

    monkeypatch.setenv("GROK_UNLIMITED_CAPACITY", "false")
    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "false")
    monkeypatch.setattr(ct, "grok_spend_usd_recent", lambda *a, **k: 0.5)
    assert ct.grok_budget_ok(0.75) is True
    monkeypatch.setattr(ct, "grok_spend_usd_recent", lambda *a, **k: 1.0)
    assert ct.grok_budget_ok(0.75) is False


def test_grok_budget_ok_unlimited_when_zero_budget(monkeypatch):
    from observability import cost_tracker as ct

    monkeypatch.setenv("GROK_UNLIMITED_CAPACITY", "true")
    monkeypatch.setattr(ct, "grok_spend_usd_recent", lambda *a, **k: 99.0)
    assert ct.grok_budget_ok(0) is True


def test_grok_capacity_unlimited_in_continuous(monkeypatch):
    from factory_core import grok_capacity as gc

    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "true")
    monkeypatch.setenv("GROK_UNLIMITED_CAPACITY", "true")
    assert gc.grok_unlimited_capacity() is True
    assert gc.effective_max_tokens_per_cycle() == 0
    assert gc.effective_headless_bills_per_cycle() == 0
    assert len(gc.default_parallel_analysis_agents()) >= 2


def test_headless_billing_caps_per_cycle(monkeypatch):
    from factory_core import grok_cli

    monkeypatch.setenv("GROK_UNLIMITED_CAPACITY", "false")
    monkeypatch.setenv("FACTORY_RUN_CONTINUOUS", "false")
    monkeypatch.setenv("GROK_MAX_HEADLESS_BILLS_PER_CYCLE", "1")
    grok_cli.reset_headless_bill_counter(42)

    def fake_run(*args, **kwargs):
        grok_cli._record_headless_bill(kwargs.get("cycle_id"))
        return {"executed": True, "session_id": "s1"}

    monkeypatch.setattr(grok_cli, "_headless_bill_allowed", grok_cli._headless_bill_allowed)
    assert grok_cli._headless_bill_allowed(42) is True
    grok_cli._record_headless_bill(42)
    assert grok_cli._headless_bill_allowed(42) is False


def test_failure_learning_gate_success_decays_stale_pattern(tmp_path, monkeypatch):
    import factory_core.failure_learning as fl

    log_path = tmp_path / "failure_lessons.jsonl"
    latest_path = tmp_path / "failure_learning_latest.json"
    monkeypatch.setattr(fl, "FAILURE_LOG", log_path)
    monkeypatch.setattr(fl, "FAILURE_LATEST", latest_path)

    gate_fail = {
        "all_passed": False,
        "gates": [{"gate": "verified_revenue_pipeline", "passed": False, "detail": "stale"}],
    }
    fl.record_cycle_failures(100, execution={}, gate_result=gate_fail, analysis={}, evolution={})
    assert fl.analyze_failure_patterns()["top_pattern"] == "gate:verified_revenue_pipeline"

    gate_ok = {
        "all_passed": True,
        "gates": [{"gate": "verified_revenue_pipeline", "passed": True, "detail": "ok"}],
    }
    fl.record_cycle_gate_success(115, gate_ok)
    summary = fl.analyze_failure_patterns()
    assert summary.get("top_pattern") != "gate:verified_revenue_pipeline"


def test_daemon_summary_reads_supervisor_shape():
    from factory_core.factory_dashboard import _daemon_summary

    assert _daemon_summary({"daemons": [{"name": "treasury_ws", "started": True}, {"name": "nexus_echo", "started": False}]}) == "1/2 running"


def test_failure_learning_records_and_prioritizes(tmp_path, monkeypatch):
    from factory_core import failure_learning as fl

    log_path = tmp_path / "failure_lessons.jsonl"
    latest_path = tmp_path / "failure_learning_latest.json"
    monkeypatch.setattr(fl, "FAILURE_LOG", log_path)
    monkeypatch.setattr(fl, "FAILURE_LATEST", latest_path)

    gate_result = {
        "all_passed": False,
        "gates": [
            {"gate": "live_url_reachable", "passed": False, "detail": "404"},
            {"gate": "verified_revenue_pipeline", "passed": True, "detail": "ok"},
        ],
    }
    execution = {"fail_fast": True, "fail_fast_reason": "pytest_failed", "pytest_passed": False}
    meta = fl.record_cycle_failures(
        10,
        execution=execution,
        gate_result=gate_result,
        analysis={},
        evolution={"executor": {"executed": False, "reason": "gates_failed"}},
    )
    assert meta["recorded"]
    fl.record_cycle_failures(
        11,
        execution=execution,
        gate_result=gate_result,
        analysis={},
        evolution={},
    )
    summary = fl.analyze_failure_patterns()
    assert summary["gate_failures"]
    assert "refresh_tip_surfaces" in summary["remediation_priorities"]
    proposals = fl.failure_learning_proposals(11, summary=summary)
    assert proposals and proposals[0]["source"] == "failure_learning"


def test_analyzer_includes_fail_fast_bottleneck():
    from factory_core.analyzer import analyze_cycle

    analysis = analyze_cycle(
        1,
        {"verified_revenue_events": 0, "fail_fast": True, "fail_fast_reason": "pytest_failed"},
        100.0,
        {"all_passed": False, "gates": [], "failed_gates": []},
    )
    assert "fail_fast:pytest_failed" in analysis["bottlenecks"]
    assert "pytest_failed" in analysis["bottlenecks"]


def test_factory_goal_injects_slash_goal(monkeypatch):
    from factory_core.factory_goal import inject_factory_goal, inject_subagent_goal

    monkeypatch.setenv("FACTORY_GOAL_ENABLED", "true")
    out = inject_factory_goal("Do analysis", cycle_id=5, task_kind="analyze")
    assert out.startswith("/goal ")
    assert "cycle 5" in out
    assert "Do analysis" in out

    agent_out = inject_subagent_goal(
        "Find bottlenecks",
        5,
        "analyze",
        agent_name="bottleneck_explorer",
    )
    assert agent_out.startswith("/goal ")
    assert "bottleneck_explorer" in agent_out


def test_format_agents_for_cli_includes_goal(monkeypatch):
    from factory_core.grok_cli import format_agents_for_cli

    monkeypatch.setenv("FACTORY_GOAL_ENABLED", "true")
    payload = format_agents_for_cli(
        [{"name": "scout", "type": "explore", "prompt": "find revenue"}],
        cycle_id=3,
        task_kind="analyze",
    )
    assert "scout" in payload
    assert payload["scout"]["prompt"].startswith("/goal ")


def test_factory_dashboard_render(monkeypatch):
    from factory_core.factory_dashboard import render_factory_dashboard

    monkeypatch.setenv("FACTORY_DASHBOARD_ENABLED", "true")
    text = render_factory_dashboard(cycle_id=1, mode="brief", factory_state={"current_cycle": 1})
    assert "RSI-EAF Factory Dashboard" in text
    assert "Economics" in text


def test_treasury_daemon_atomic_drain(tmp_path, monkeypatch):
    from observability import treasury_daemon as td

    inbox = tmp_path / "inbox.jsonl"
    monkeypatch.setattr(td, "INBOX_FILE", inbox)
    monkeypatch.setattr(td, "DEDUPE_FILE", tmp_path / "dedupe.json")
    td._append_inbox({"tx_hash": "A1", "from": "rExt"})
    td._append_inbox({"tx_hash": "A2", "from": "rExt"})
    drained = td.drain_inbox()
    assert len(drained) == 2
    assert td.drain_inbox() == []
    assert inbox.read_text(encoding="utf-8") == ""


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


@pytest.mark.orchestration
def test_init_runner_acp_disabled(monkeypatch):
    from factory_core import grok_acp

    monkeypatch.setenv("GROK_ORCHESTRATION", "subprocess")
    result = grok_acp.init_runner_acp()
    assert result.get("started") is False


@pytest.mark.orchestration
def test_run_parallel_analysis_routes_acp(monkeypatch):
    from factory_core import grok_cli

    calls = []

    def fake_acp(cycle_id, prompt, factory_state=None, task_kind="acp"):
        calls.append((cycle_id, prompt[:40], task_kind))
        return {"mode": "acp", "cycle_id": cycle_id}

    monkeypatch.setenv("GROK_ORCHESTRATION", "acp")
    monkeypatch.setenv("GROK_HEADLESS_ORCHESTRATION", "acp")
    monkeypatch.setenv("GROK_PARALLEL_ANALYSIS", "true")
    monkeypatch.setattr("factory_core.grok_acp.run_cycle_via_acp", fake_acp)
    grok_cli.run_parallel_analysis(7, {"cycle_revenue_usd": 0})
    assert calls and calls[0][0] == 7
    assert calls[0][2] == "analyze"


@pytest.mark.orchestration
def test_run_parallel_analysis_prefers_headless_subprocess(monkeypatch):
    from factory_core import grok_cli

    acp_calls = []
    headless_calls = []

    def fake_acp(cycle_id, prompt, factory_state=None, task_kind="acp"):
        acp_calls.append(cycle_id)
        return {"mode": "acp"}

    def fake_headless(*args, **kwargs):
        headless_calls.append(kwargs.get("agents"))
        return {"mode": "subprocess", "agents": kwargs.get("agents")}

    monkeypatch.setenv("GROK_ORCHESTRATION", "acp")
    monkeypatch.setenv("GROK_HEADLESS_ORCHESTRATION", "subprocess")
    monkeypatch.setenv("GROK_PARALLEL_ANALYSIS", "true")
    monkeypatch.setattr("factory_core.grok_acp.run_cycle_via_acp", fake_acp)
    monkeypatch.setattr(grok_cli, "run_headless", fake_headless)
    result = grok_cli.run_parallel_analysis(8, {"cycle_revenue_usd": 0})
    assert not acp_calls
    assert headless_calls
    assert result.get("mode") == "subprocess"


def test_failure_learning_persists_factory_state(tmp_path, monkeypatch):
    from factory_core import failure_learning as fl
    from factory_core.state import FactoryState

    log_path = tmp_path / "failure_lessons.jsonl"
    latest_path = tmp_path / "failure_learning_latest.json"
    state_path = tmp_path / "factory_state.json"
    monkeypatch.setattr(fl, "FAILURE_LOG", log_path)
    monkeypatch.setattr(fl, "FAILURE_LATEST", latest_path)

    state = FactoryState(state_path=str(state_path))
    gate_result = {
        "all_passed": False,
        "gates": [{"gate": "verified_revenue_pipeline", "passed": False, "detail": "no payers"}],
    }
    fl.record_cycle_failures(
        20,
        execution={},
        gate_result=gate_result,
        factory_state=state,
    )
    stored = state.get_failure_learning()
    assert stored.get("top_pattern") == "gate:verified_revenue_pipeline"
    assert stored.get("last_cycle_id") == 20


def test_factory_dashboard_shows_failure_learning_empty(monkeypatch):
    from factory_core import failure_learning as fl
    from factory_core.factory_dashboard import render_factory_dashboard

    monkeypatch.setattr(fl, "FAILURE_LATEST", Path("/nonexistent/failure_learning_latest.json"))
    monkeypatch.setattr(fl, "FAILURE_LOG", Path("/nonexistent/failure_lessons.jsonl"))
    text = render_factory_dashboard(cycle_id=1, mode="brief", factory_state={"current_cycle": 1})
    assert "Failure learning" in text
    assert "samples=0" in text


@pytest.mark.orchestration
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
    from tools import nexus_ci_runner_watch as runner_watch

    monkeypatch.setenv("NEXUS_EMIT_ENABLED", "true")
    monkeypatch.setattr(runner_watch, "nexus_runners_blocked", lambda: False)
    monkeypatch.setattr(ci_gate, "block_distribution_if_ci_red", lambda **k: "CI failed")
    result = nb.maybe_emit_nexus({"cycle_id": 5, "execution": {}, "analysis": {}, "gates": {}})
    assert result.get("ci_blocked") is True


def test_nexus_emit_blocked_when_runners_unavailable(monkeypatch, tmp_path):
    from tools import nexus_bridge as nb
    from tools import nexus_ci_runner_watch as runner_watch

    state_path = tmp_path / "nexus_ci_runner_state.json"
    monkeypatch.setattr(runner_watch, "STATE_FILE", state_path)
    monkeypatch.setenv("NEXUS_EMIT_ENABLED", "true")
    monkeypatch.setenv("NEXUS_RUNNER_WATCH_ENABLED", "true")
    runner_watch.save_runner_state({"runner_unavailable": True, "runner_available": False})
    result = nb.maybe_emit_nexus({"cycle_id": 5, "execution": {}, "analysis": {}, "gates": {}})
    assert result.get("runner_blocked") is True


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


def test_agent_pay_manifest_structure():
    from observability.agent_payment import build_agent_pay_manifest

    m = build_agent_pay_manifest(42, "rTreasury", {"tip_page": "https://x/tip.html"})
    assert m["schema"] == "rsi_eaf_agent_pay_v1"
    assert m["easiest_payment"]["destination_tag"] == 1
    assert m["treasury_address"] == "rTreasury"
    assert len(m["products"]) >= 5


def test_mainnet_readiness_blocks_without_revenue(monkeypatch, tmp_path):
    from factory_core.mainnet_readiness import evaluate_mainnet_readiness
    from observability import economic_ledger as el

    ledger_path = tmp_path / "empty_ledger.jsonl"
    ledger_path.write_text("", encoding="utf-8")
    isolated = el.EconomicLedger(ledger_path=str(ledger_path))
    monkeypatch.setattr(el, "ledger", isolated)
    monkeypatch.setattr("gates.verifier.ledger", isolated)

    r = evaluate_mainnet_readiness()
    assert r["ready_for_mainnet"] is False
    assert any("verified" in b.lower() or "organic" in b.lower() for b in r["blockers"])


def test_fitness_evolution_priorities_revenue_first():
    from factory_core.fitness_evolution import fitness_evolution_priorities

    report = {
        "composite_score": 8.4,
        "economics": {"verified_revenue_events": 0, "organic_revenue_usd_est": 0},
        "actions": {
            "evolution": {
                "top_gate_failures": [["verified_revenue_pipeline", 10], ["live_url_reachable", 3]],
            }
        },
    }
    priorities = fitness_evolution_priorities(report=report, execution={}, gates={"all_passed": True})
    assert priorities[0] == "fitness_revenue_capture"
    assert "treasury_ingest_github" in priorities
    assert "refresh_tip_surfaces" in priorities or "batch_vercel_deploy" in priorities


def test_fitness_is_failing_and_env(monkeypatch):
    from factory_core.fitness_evolution import (
        apply_fitness_env,
        fitness_focus,
        fitness_is_failing,
    )

    failing = {"composite_score": 8.0, "verdict": "failing"}
    passing = {"composite_score": 75.0, "verdict": "passing"}
    assert fitness_is_failing(failing) is True
    assert fitness_is_failing(passing) is False
    assert fitness_focus(failing, "rsi") == "revenue"
    assert fitness_focus(passing, "rsi") == "rsi"
    monkeypatch.delenv("DIRECTOR_FITNESS_MODE", raising=False)
    env = apply_fitness_env(failing)
    assert env["fitness_mode"] is True
    assert os.environ.get("DIRECTOR_FITNESS_MODE") == "true"
    assert os.environ.get("CYCLE_FOCUS") == "revenue"


def test_compute_cycle_focus_fitness_override(monkeypatch):
    from factory_core.self_improver import compute_cycle_focus

    monkeypatch.setattr(
        "factory_core.fitness_evolution.fitness_is_failing",
        lambda report=None: True,
    )
    focus = compute_cycle_focus(3, {"cycle_revenue_usd": 0, "bottlenecks": []}, {})
    assert focus == "revenue"


def test_factory_operational_status_closure(tmp_path, monkeypatch):
    from factory_core.state import FactoryState

    # Pass path explicitly — default STATE_FILE is bound at import; env alone is not enough.
    state_path = str(tmp_path / "state.json")
    monkeypatch.setenv("FACTORY_STATE_FILE", state_path)
    state = FactoryState(state_path=state_path)
    state.set_operational_status({"state": "closed_indefinitely", "reason": "funds"})
    assert state.get_operational_status()["state"] == "closed_indefinitely"
    assert state.state_path == state_path


def test_service_catalog_v2_has_fulfillment_urls(tmp_path, monkeypatch):
    from observability.service_fulfillment import build_service_catalog

    monkeypatch.chdir(tmp_path)
    catalog = build_service_catalog(42, "rTreasury123")
    assert catalog["schema"] == "rsi_eaf_service_catalog_v2"
    assert len(catalog["services"]) >= 4
    assert all(s.get("fulfillment_url") for s in catalog["services"])
    assert catalog["how_to_pay"]["agent"]


def test_factory_fitness_report(tmp_path, monkeypatch):
    from observability import factory_fitness_report as ffr

    out = tmp_path / "fitness.json"
    report = ffr.generate_factory_fitness_report(cycle_id=10, persist_path=str(out))
    assert report["schema"] == "rsi_eaf_factory_fitness_v1"
    assert out.exists()
    assert "economics" in report


def test_jarvis_memory_archive_specs():
    from tools.jarvis_memory_archive import archive_workflow_specs

    specs = archive_workflow_specs()
    assert len(specs) == 3
    assert "workflow_dispatch" in specs[0]["content"]
    assert "schedule" not in specs[0]["content"] or "ARCHIVED" in specs[0]["content"]


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


def test_fitness_revenue_capture_honest_implemented(monkeypatch):
    """Stale CDN liveness alone must not mark fitness_revenue_capture implemented."""
    from tools import fitness_revenue_capture as frc

    monkeypatch.setattr(
        frc,
        "ingest_verified_xrpl_revenue",
        lambda **_kw: {"ingested": [], "unmatched": [], "reconciled": []},
    )
    monkeypatch.setattr(
        "tools.publish_tools.deploy_to_vercel",
        lambda **_kw: {"success": False, "skipped": True, "reason": "test cooldown"},
    )
    monkeypatch.setattr("tools.publish_tools.verify_live_url", lambda _url: True)
    monkeypatch.setattr(
        "observability.service_fulfillment.fulfill_paid_services",
        lambda *_a, **_k: {
            "paid_product_ids": [],
            "newly_fulfilled": [],
            "pending_unknown": [],
        },
    )
    monkeypatch.setattr(
        "observability.agent_payment.write_agent_pay_manifest",
        lambda *_a, **_k: Path("published/agent-pay.json"),
    )
    monkeypatch.setattr(
        "observability.payer_funnel.refresh_payer_funnel",
        lambda *_a, **_k: {"cycle_id": 42, "conversion_score": 0},
    )

    result = frc.run_fitness_revenue_capture(
        cycle_id=42,
        treasury_address="rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN",
        featured={
            "tip_page": "https://example.test/tip",
            "agent_pay": "https://example.test/agent-pay.json",
            "service_catalog": "https://example.test/service-catalog.json",
            "payment_status": "https://example.test/payment-status.json",
        },
    )
    assert result["action"] == "fitness_revenue_capture"
    assert result["ingested_count"] == 0
    assert result["reconciled_count"] == 0
    assert result["agent_pay_live"] is True
    assert result["capture_progress"] is False
    assert result["deploy_succeeded"] is False
    assert result["implemented"] is False