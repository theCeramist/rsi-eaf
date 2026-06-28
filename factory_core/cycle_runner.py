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
from factory_core.evolution_executor import execute_evolution
from factory_core.self_improver import evolve_self, run_self_improvement_meta
from factory_core.tool_improver import evolve_tools, run_tool_improvement_cycle
from factory_core.state import FactoryState
from gates.verifier import run_cycle_gates
from observability.cost_tracker import auto_log_grok_session_costs, log_cycle_costs
from observability.economic_ledger import ledger
from factory_core.economic_guards import loss_ceiling_raised, requires_revenue_action
from observability.ledger_hygiene import backfill_revenue_classification, supersede_unverified_revenue
from observability.trace_logger import trace_logger
from observability.treasury_monitor import poll_treasury_payments
from revenue_engines.registry import run_revenue_engines
from tools.distribution_tools import featured_links_for_index, write_sitemap
from tools.github_distribution import write_local_distribution_artifacts
from tools.nexus_bridge import run_platform_sync
from tools.publish_tools import build_index_html, deploy_cooldown_status, reset_cycle_deploy_flag
from revenue_engines.base_engine import resolve_treasury
from tools.xrpl_tools import load_factory_wallet, get_account_xrp_balance

REQUIRE_LIVE_URL = os.getenv("REQUIRE_LIVE_URL", "false").lower() in {"1", "true", "yes"}
CYCLE_MODE = os.getenv("CYCLE_MODE", "revenue").strip()  # revenue | tool_improvement | hybrid


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

    def _poll_treasury(self, cycle_id: int) -> Dict[str, Any]:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        hard_timeout = float(os.getenv("TREASURY_POLL_HARD_TIMEOUT_SEC", "20"))
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    poll_treasury_payments,
                    cycle_id=cycle_id,
                    factory_state=self.state,
                )
                return future.result(timeout=hard_timeout)
        except FuturesTimeout:
            print(f"[Cycle] Treasury poll hard-timeout ({hard_timeout:.0f}s) — continuing cycle")
            return {
                "ws_observed": 0,
                "ingested": [],
                "unmatched": [],
                "treasury_address": os.getenv("FACTORY_TREASURY_ADDRESS"),
                "error": "poll_hard_timeout",
                "poll_mode": "timeout",
            }
        except Exception as exc:
            print(f"[Cycle] Treasury poll failed (non-fatal): {exc}")
            return {
                "ws_observed": 0,
                "ingested": [],
                "unmatched": [],
                "treasury_address": None,
                "error": str(exc),
            }

    def _run_revenue_phase(
        self,
        cycle_id: int,
        cooldown: Dict[str, Any],
        tool_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        print("[Cycle] Phase 1: Execute revenue engines...")
        engine_bundle = run_revenue_engines(cycle_id=cycle_id)
        if engine_bundle.get("errors"):
            print(f"[Cycle] Engine errors: {engine_bundle['errors']}")
        treasury = resolve_treasury()
        featured = featured_links_for_index(cycle_id)
        build_index_html(treasury_address=treasury, featured=featured)
        write_sitemap(live_urls=engine_bundle.get("live_urls"))
        write_local_distribution_artifacts(cycle_id, featured, treasury)
        force_distribution = requires_revenue_action(ledger.calculate_net())
        if force_distribution and loss_ceiling_raised():
            print("[Cycle] Raised loss ceiling — will force platform sync distribution")
        print("[Cycle] Phase 1b: Treasury monitor + revenue ingest...")
        treasury_result = self._poll_treasury(cycle_id)
        verified_revenue = treasury_result.get("ingested", [])
        unmatched_inflows = treasury_result.get("unmatched", [])
        mode = os.getenv("CYCLE_MODE", CYCLE_MODE).strip()
        execution_result = {
            "cycle_mode": mode,
            "vercel_cooldown": cooldown,
            "vercel_deploy": engine_bundle.get("vercel_deploy"),
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
            "treasury_unmatched_inflows": len(unmatched_inflows),
            "treasury_unmatched": unmatched_inflows,
            "treasury_address": treasury_result.get("treasury_address"),
            "engine_errors": engine_bundle.get("errors", []),
            "featured_surfaces": featured,
            "force_distribution": force_distribution,
        }
        if tool_result:
            execution_result.update({
                "pytest_passed": tool_result.get("pytest_passed"),
                "xrpl_ok": tool_result.get("xrpl_ok"),
                "tool_improvements_log": tool_result.get("tool_improvements_log"),
                "opportunities": tool_result.get("opportunities"),
            })
        return execution_result, engine_bundle, featured

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
        backfill_revenue_classification()
        reset_cycle_deploy_flag()
        mode = os.getenv("CYCLE_MODE", CYCLE_MODE).strip()
        cooldown = deploy_cooldown_status()
        if cooldown.get("active"):
            print(f"[Cycle] Vercel deploy skipped: {cooldown.get('reason')}")

        # === 1. EXECUTE ===
        t0 = time.time()
        if mode == "tool_improvement":
            print("[Cycle] Phase 1: Tool improvement (no revenue engines / no Vercel)...")
            tool_result = run_tool_improvement_cycle(cycle_id=cycle_id)
            treasury_result = self._poll_treasury(cycle_id)
            verified_revenue = treasury_result.get("ingested", [])
            execution_result = {
                **tool_result,
                "cycle_mode": mode,
                "vercel_cooldown": cooldown,
                "revenue_usd_est": sum(e.get("amount_usd_est", 0) for e in verified_revenue),
                "verified_revenue_events": len(verified_revenue),
                "treasury_ws_observed": treasury_result.get("ws_observed", 0),
                "treasury_address": treasury_result.get("treasury_address"),
            }
            trace_logger.log_cycle_trace(cycle_id, "execute", execution_result, (time.time() - t0) * 1000)
        elif mode == "hybrid":
            skip_tool = os.getenv("FACTORY_SKIP_TOOL_PHASE", "").lower() in {"1", "true", "yes"}
            revenue_on_fail = os.getenv("FACTORY_REVENUE_ON_PYTEST_FAIL", "true").lower() in {
                "1",
                "true",
                "yes",
            }
            engine_bundle: Dict[str, Any] = {}
            featured: Dict[str, str] = {}
            if skip_tool:
                print("[Cycle] Phase 0: Skipped (FACTORY_SKIP_TOOL_PHASE) — revenue lane")
                execution_result, engine_bundle, featured = self._run_revenue_phase(cycle_id, cooldown)
            else:
                print("[Cycle] Phase 0: Tool health check...")
                tool_result = run_tool_improvement_cycle(cycle_id=cycle_id)
                tool_ok = tool_result.get("pytest_passed") and tool_result.get("xrpl_ok")
                if tool_ok:
                    execution_result, engine_bundle, featured = self._run_revenue_phase(
                        cycle_id, cooldown, tool_result=tool_result
                    )
                else:
                    reason = "pytest_failed" if not tool_result.get("pytest_passed") else "xrpl_failed"
                    if revenue_on_fail:
                        print(f"[Cycle] Phase 0 FAIL ({reason}) — running revenue engines anyway")
                        execution_result, engine_bundle, featured = self._run_revenue_phase(
                            cycle_id, cooldown, tool_result=tool_result
                        )
                        execution_result["fail_fast"] = True
                        execution_result["fail_fast_reason"] = reason
                    else:
                        print(f"[Cycle] Phase 0 FAIL ({reason}) — skipping revenue engines (fail-fast)")
                        treasury_result = self._poll_treasury(cycle_id)
                        verified_revenue = treasury_result.get("ingested", [])
                        execution_result = {
                            **tool_result,
                            "cycle_mode": mode,
                            "fail_fast": True,
                            "fail_fast_reason": reason,
                            "vercel_cooldown": cooldown,
                            "revenue_usd_est": sum(e.get("amount_usd_est", 0) for e in verified_revenue),
                            "verified_revenue_events": len(verified_revenue),
                            "treasury_ws_observed": treasury_result.get("ws_observed", 0),
                            "treasury_address": treasury_result.get("treasury_address"),
                            "treasury_unmatched_inflows": len(treasury_result.get("unmatched", [])),
                            "revenue_engines_run": [],
                            "xrpl_payments_made": 0,
                            "published_assets": [],
                            "force_distribution": False,
                        }
            trace_logger.log_cycle_trace(
                cycle_id,
                "execute",
                {**execution_result, "engine_bundle": engine_bundle, "featured": featured},
                (time.time() - t0) * 1000,
            )
        else:
            execution_result, engine_bundle, featured = self._run_revenue_phase(cycle_id, cooldown)
            trace_logger.log_cycle_trace(
                cycle_id,
                "execute",
                {**execution_result, "engine_bundle": engine_bundle, "featured": featured},
                (time.time() - t0) * 1000,
            )

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
        if not cost_events and mode in ("tool_improvement", "hybrid"):
            cost_events = log_cycle_costs(
                cycle_id=cycle_id,
                session_cost_usd=0.0,
                metadata={"tool_maintenance": True, "basis": "tool_improvement_maintenance"},
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
        if os.getenv("GROK_PARALLEL_ANALYSIS", "true").lower() in {"1", "true", "yes"}:
            try:
                from factory_core.grok_cli import run_parallel_analysis

                grok_insights = run_parallel_analysis(cycle_id, analysis)
                analysis["grok_insights"] = grok_insights
                trace_logger.log_cycle_trace(cycle_id, "grok_analyze", grok_insights)
            except Exception as exc:
                analysis["grok_insights"] = {"error": str(exc)}
        trace_logger.log_cycle_trace(cycle_id, "analyze", analysis)

        try:
            from factory_core.parallel_lanes import run_post_analyze_lanes

            zero_streak = int(os.getenv("FACTORY_CONSECUTIVE_ZERO_REVENUE", "0"))
            analyze_lanes = run_post_analyze_lanes(
                cycle_id,
                analysis,
                execution_result.get("featured_surfaces"),
                consecutive_zero_revenue=zero_streak,
            )
            if analyze_lanes:
                analysis["parallel_lanes"] = analyze_lanes
                trace_logger.log_cycle_trace(cycle_id, "parallel_analyze", analyze_lanes)
        except Exception as exc:
            analysis["parallel_lanes"] = {"error": str(exc)}

        print("[Cycle] Phase 3b: RSI meta-analysis (balanced self-improvement)...")
        rsi_meta = run_self_improvement_meta(cycle_id, analysis, gate_result)
        analysis["rsi_meta"] = rsi_meta
        analysis["cycle_focus"] = rsi_meta.get("focus")
        os.environ["CYCLE_FOCUS"] = rsi_meta.get("focus", "revenue")
        trace_logger.log_cycle_trace(cycle_id, "rsi_meta", rsi_meta)

        # === 4. PROPOSE ===
        print(f"[Cycle] Phase 4: Generate improvement proposals (focus={rsi_meta.get('focus')})...")
        proposals = propose_improvements(analysis, cycle_id=cycle_id, rsi_meta=rsi_meta)
        trace_logger.log_cycle_trace(cycle_id, "propose", {"proposals": proposals})

        # === 5. VERIFY ===
        print("[Cycle] Phase 5: Verify proposals against gates...")
        if not gate_result.get("all_passed"):
            failed = [g["gate"] for g in gate_result.get("gates", []) if not g["passed"]]
            print(f"[Cycle] GATE FAILURE: {failed}")

        # === 6. EVOLVE ===
        print("[Cycle] Phase 6: Evolve (surgical merge of validated changes)...")
        treasury_addr = execution_result.get("treasury_address") or ""
        executor_result = execute_evolution(
            cycle_id,
            proposals,
            gate_result,
            rsi_meta,
            execution_result,
            featured=execution_result.get("featured_surfaces"),
            treasury_address=treasury_addr,
            factory_state=self.state,
        )
        if mode in ("tool_improvement", "hybrid"):
            tool_evolution = evolve_tools(cycle_id, proposals, gate_result)
            rsi_evolution = evolve_self(cycle_id, proposals, gate_result, rsi_meta)
            evolution = {
                "evolved": tool_evolution.get("evolved") and rsi_evolution.get("rsi_evolved"),
                "tool": tool_evolution,
                "rsi": rsi_evolution,
                "executor": executor_result,
                "cycle_focus": rsi_meta.get("focus"),
            }
            evolution["ledger_event"] = ledger.log_event(
                event_type="milestone",
                source="evolver",
                amount_usd_est=0.0,
                cycle_id=cycle_id,
                metadata={"phase": "evolve", "cycle_id": cycle_id, "mode": mode, **evolution},
                anchor_to_xrpl=False,
            )
        else:
            rsi_evolution = evolve_self(cycle_id, proposals, gate_result, rsi_meta)
            evolution = evolve_cycle(cycle_id, gate_result, analysis, proposals)
            evolution["rsi"] = rsi_evolution
            evolution["executor"] = executor_result
            evolution["cycle_focus"] = rsi_meta.get("focus")
        trace_logger.log_cycle_trace(cycle_id, "evolve", evolution)

        try:
            from factory_core.parallel_lanes import run_post_evolve_lanes

            allow_grok_evo = os.getenv("GROK_EVOLUTION_ENABLED", "false").lower() in {"1", "true", "yes"}
            evolve_lanes = run_post_evolve_lanes(
                cycle_id,
                evolution,
                gate_result,
                execution_result.get("featured_surfaces"),
                allow_code_evolution=allow_grok_evo,
            )
            evolution["parallel_lanes"] = evolve_lanes
            evolution["worktree_verifier"] = evolve_lanes.get("worktree_verifier")
            trace_logger.log_cycle_trace(cycle_id, "parallel_evolve", evolve_lanes)
        except Exception as exc:
            evolution["parallel_lanes"] = {"error": str(exc)}

        if gate_result.get("all_passed"):
            try:
                from factory_core.grok_verify import verify_evolution_change

                grok_verify = verify_evolution_change(cycle_id, evolution, gate_result)
                trace_logger.log_cycle_trace(cycle_id, "grok_verify", grok_verify)
                evolution["grok_verify"] = grok_verify
            except Exception as exc:
                evolution["grok_verify"] = {"error": str(exc)}

        print("[Cycle] Phase 6b: Platform sync (GitHub + aetherforge nexus + Vercel verify)...")
        force_github = os.getenv("DIRECTOR_FORCE_GITHUB", "").lower() in {"1", "true", "yes"}
        force_nexus = os.getenv("DIRECTOR_FORCE_NEXUS", "").lower() in {"1", "true", "yes"}
        from observability.factory_health import persist_factory_health

        platform_sync = run_platform_sync(
            {
                "cycle_id": cycle_id,
                "success": gate_result.get("all_passed", False),
                "execution": execution_result,
                "analysis": analysis,
                "gates": gate_result,
                "proposals": proposals,
                "evolution": evolution,
                "ledger_net": ledger.calculate_net(),
                "xrpl_factory_address": wallet.classic_address,
                "current_xrp_balance": float(current_balance),
                "factory_state": self.state.snapshot(),
            },
            force_github=force_github,
            force_nexus=force_nexus,
            factory_state=self.state,
        )
        trace_logger.log_cycle_trace(cycle_id, "platform_sync", platform_sync)
        execution_result["github_distribution"] = platform_sync.get("github", {})
        persist_factory_health(
            cycle_id=cycle_id,
            featured=execution_result.get("featured_surfaces"),
            factory_state=self.state.snapshot(),
        )
        if platform_sync.get("nexus", {}).get("emitted"):
            print(f"[Cycle] aetherforge nexus emit: {platform_sync['nexus'].get('wave_id')}")
        elif platform_sync.get("github", {}).get("pushed"):
            print("[Cycle] GitHub distribution pushed")

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

        try:
            from factory_core.parallel_lanes import dispatch_post_cycle_async

            async_lanes = dispatch_post_cycle_async(
                cycle_id,
                {
                    "cycle_id": cycle_id,
                    "execution": execution_result,
                    "analysis": analysis,
                    "ledger_net": ledger.calculate_net(),
                },
                factory_state=self.state,
            )
            trace_logger.log_cycle_trace(cycle_id, "parallel_async", async_lanes)
        except Exception as exc:
            trace_logger.log_cycle_trace(cycle_id, "parallel_async", {"error": str(exc)})

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
            "organic_revenue_usd": ledger.calculate_net().get("organic_revenue_usd_est", 0),
            "factory_state": self.state.snapshot(),
            "platform_sync": platform_sync,
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