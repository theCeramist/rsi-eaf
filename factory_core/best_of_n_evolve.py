"""
Best-of-N evolution worktrees — parallel isolated attempts, merge winner only.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def run_best_of_n_evolution(
    cycle_id: int,
    task: str,
    n: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run N worktree-isolated evolution attempts; pick best by pytest pass + Grok verify.
    """
    if os.getenv("BEST_OF_N_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        from factory_core.grok_cli import run_evolution_task

        return run_evolution_task(cycle_id, task, worktree=True)

    n = n or int(os.getenv("GROK_BEST_OF_N", "3"))
    n = max(1, min(n, int(os.getenv("GROK_BEST_OF_N_MAX", "3"))))

    from factory_core.grok_cli import run_evolution_task
    from factory_core.verifier_subagent import run_worktree_verifier

    attempts: List[Dict[str, Any]] = []
    for i in range(n):
        attempt = run_evolution_task(
            cycle_id,
            f"{task}\n\nAttempt {i + 1}/{n} — minimal diff only.",
            worktree=True,
            best_of_n=1,
        )
        verify = run_worktree_verifier(
            cycle_id,
            {"attempt": i + 1, "evolution": attempt},
            {"all_passed": attempt.get("executed")},
        )
        score = 1.0 if verify.get("approved") else 0.0
        if verify.get("consensus_score") is not None:
            score = float(verify["consensus_score"])
        attempts.append({"attempt": i + 1, "evolution": attempt, "verify": verify, "score": score})

    winner = max(attempts, key=lambda a: a["score"]) if attempts else None
    return {
        "lane": "best_of_n_evolve",
        "n": n,
        "attempts": attempts,
        "winner": winner,
        "winner_score": winner["score"] if winner else 0,
    }