"""
RSI-EAF Cycle Runner
Execute → Instrument → Analyze → Propose → Verify → Evolve
"""

import argparse
import os
import sys
import time
from typing import Dict, Any, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from factory_core.analyzer import analyze_cycle
from factory_core.evolver import evolve_cycle
from factory_core.proposer import propose_improvements
from factory_core.state import FactoryState
from gates.verifier import run_cycle_gates
from observability.cost_tracker import auto_log_grok_session_costs, log_cycle_costs
from observability.economic_ledger import ledger
from observability.ledger_hygiene import supersede_unverified_revenue
from observability.trace_logger import trace_logger
from observability.treasury_monitor import poll_treasury_payments
from revenue_engines.registry import run_revenue_engines
from tools.distribution_tools import featured_links_for_index, write_sitemap
from tools.publish_tools import build_index_html
from revenue_engines.base_engine import resolve_treasury
from tools.xrpl_tools import load_factory_wallet, get_account_xrp_balance

REQUIRE_LIVE_URL = os.getenv("REQUIRE_LIVE_URL", "false").lower() in {"1", "true", "yes"}


class CycleRunner:
    def __init__(self, factory_name: str = "RSI-EAF-v0"):
        self.factory_name = factory_name
        self.state = FactoryState()
        self.wallet = None

        if self.state.current_cycle == 0:
            events = ledger.get_recent_events(limit=1000)
            max_cycle = max((e.get("cycle_id") or 0) for e in events) if events else 0
            self.state.bootstrap_from_ledger(max_cycle)

    def _get_wallet(self):
        if self.wallet is None:
            self.wallet = load_factory_wallet(testnet=True)
        return self.wallet

    def run_cycle(
        self,
        manual: bool = True,
        session_cost_usd: Optional[float] = None,
        grok_tokens_used: Optional[int] = None,
    ) -> Dict[str, Any]:
        cycle_id = self.state.advance_cycle()
        print(f"\n{'='*60}")
        print(f"[{self.factory_name}] Starting Cycle {cycle_id}")
        print(f"{'='*60}")

        start_time = time.time()
        supersede_unverified_revenue()

        # === 1. EXECUTE ===
        print("[Cycle] Phase 1: Execute revenue engines + maintenance...")
        t0 = time.time()
        engine_bundle = run_revenue_engines(cycle_id=cycle_id)
        if engine_bundle.get("errors"):
            print(f"[Cycle] Engine errors: {engine_bundle['errors']}")
        treasury = resolve_treasury()
        featured = featured_links_for_index(cycle_id)
        build_index_html(treasury_address=treasury, featured=featured)
        write_sitemap(live_urls=engine_bundle.get("live_urls"))
        engine_result = engine_bundle.get("primary") or {}
        trace_logger.log_cycle_trace(
            cycle_id,
            "execute",
            {**engine_bundle, "featured": featured},
            (time.time() - t0) * 1000,
        )

        print("[Cycle] Phase 1b: Treasury monitor + verified revenue ingest...")
        treasury_result = poll_treasury_payments(cycle_id=cycle_id, factory_state=self.state)
        verified_revenue = treasury_result.get("ingested", [])

        execution_result = {
            "revenue_engines_run": engine_bundle.get("engines_run", []),
            "xrpl_payments_made": engine_bundle.get("xrpl_payments_made", 0),
            "published_asset": engine_bundle.get("published_asset"),
            "published_assets": engine_bundle.get("published_assets", []),
            "live_url": engine_bundle.get("live_url"),
            "live_urls": engine_bundle.get("live_urls", []),
            "live_verified": engine_bundle.get("live_verified", False),
            "xrpl_tx_hash": engine_bundle.get("xrpl_tx_hash"),
            "explorer_url": engine_bundle.get("explorer_url"),
            "revenue_usd_est": sum(e.get("amount_usd_est", 0) for e in verified_revenue),
            "verified_revenue_events": len(verified_revenue),
            "treasury_ws_observed": treasury_result.get("ws_observed", 0),
            "treasury_address": treasury_result.get("treasury_address"),
            "engine_errors": engine_bundle.get("errors", []),
            "featured_surfaces": featured,
        }

        # === 2. INSTRUMENT ===
        print("[Cycle] Phase 2: Instrument traces, economic ledger, XRPL state...")
        wallet = self._get_wallet()
        current_balance = get_account_xrp_balance(wallet.classic_address)

        if session_cost_usd is not None or grok_tokens_used is not None:
            cost_events = log_cycle_costs(
                cycle_id=cycle_id,
                session_cost_usd=session_cost_usd,
                grok_tokens_used=grok_tokens_used,
            )
        else:
            cost_events = auto_log_grok_session_costs(
                cycle_id=cycle_id,
                factory_state=self.state,
            )

        ledger.log_event(
            event_type="milestone",
            source="cycle_runner",
            amount_usd_est=0.0,
            cycle_id=cycle_id,
            metadata={
                "phase": "instrument",
                "xrpl_balance_xrp": float(current_balance),
                "execution_summary": execution_result,
                "cost_events_logged": len(cost_events),
            },
            anchor_to_xrpl=False,
        )
        trace_logger.log_cycle_trace(cycle_id, "instrument", {"costs": len(cost_events)})

        # === 3. ANALYZE ===
        print("[Cycle] Phase 5 prep: Run verification gates...")
        gate_result = run_cycle_gates(
            cycle_id=cycle_id,
            execution_result=execution_result,
            require_live_url=REQUIRE_LIVE_URL,
        )
        trace_logger.log_cycle_trace(cycle_id, "gates", gate_result)

        print("[Cycle] Phase 3: Analyze performance, on-chain data, opportunities...")
        analysis = analyze_cycle(cycle_id, execution_result, float(current_balance), gate_result)
        trace_logger.log_cycle_trace(cycle_id, "analyze", analysis)

        # === 4. PROPOSE ===
        print("[Cycle] Phase 4: Generate improvement proposals (Plan Mode)...")
        proposals = propose_improvements(analysis, cycle_id=cycle_id)
        trace_logger.log_cycle_trace(cycle_id, "propose", {"proposals": proposals})

        # === 5. VERIFY ===
        print("[Cycle] Phase 5: Verify proposals against gates...")
        if not gate_result.get("all_passed"):
            failed = [g["gate"] for g in gate_result.get("gates", []) if not g["passed"]]
            print(f"[Cycle] GATE FAILURE: {failed}")

        # === 6. EVOLVE ===
        print("[Cycle] Phase 6: Evolve (surgical merge of validated changes)...")
        evolution = evolve_cycle(cycle_id, gate_result, analysis, proposals)
        trace_logger.log_cycle_trace(cycle_id, "evolve", evolution)

        ledger.log_event(
            event_type="milestone",
            source="cycle_runner",
            amount_usd_est=0.0,
            cycle_id=cycle_id,
            metadata={
                "phase": "complete",
                "duration_seconds": round(time.time() - start_time, 2),
                "analysis": analysis,
                "proposals_generated": len(proposals),
                "gates": gate_result,
                "evolution": evolution,
            },
            anchor_to_xrpl=False,
        )

        result = {
            "cycle_id": cycle_id,
            "success": gate_result.get("all_passed", False),
            "execution": execution_result,
            "analysis": analysis,
            "proposals": proposals,
            "gates": gate_result,
            "evolution": evolution,
            "xrpl_factory_address": wallet.classic_address,
            "current_xrp_balance": float(current_balance),
            "ledger_net": ledger.calculate_net(),
            "factory_state": self.state.snapshot(),
        }

        print(f"[Cycle {cycle_id}] Complete. Gates: {gate_result.get('passed_count')}/{gate_result.get('total_count')}")
        print(f"[Cycle {cycle_id}] Net so far: {result['ledger_net']}")
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one RSI-EAF factory cycle")
    parser.add_argument("--session-cost-usd", type=float, default=None)
    parser.add_argument("--grok-tokens", type=int, default=None)
    args = parser.parse_args()

    runner = CycleRunner()
    result = runner.run_cycle(
        manual=True,
        session_cost_usd=args.session_cost_usd,
        grok_tokens_used=args.grok_tokens,
    )
    print("\nCycle Result Summary:")
    print(result)