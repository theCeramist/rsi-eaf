"""
Grok Build CLI helpers — headless prompts with JSON output, worktree isolation, subagents.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

GROK_BIN = os.getenv("GROK_BIN", shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok.exe"))
DEFAULT_TIMEOUT = int(os.getenv("GROK_CLI_TIMEOUT_SEC", "120"))

GrokMode = Literal["plan", "execute", "verify", "analyze"]


def format_agents_for_cli(agents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grok CLI --agents expects a map, not a list."""
    payload: Dict[str, Any] = {}
    for idx, agent in enumerate(agents):
        name = str(agent.get("name") or f"agent_{idx}")
        payload[name] = {k: v for k, v in agent.items() if k != "name"}
    return payload


def _parse_json_output(output: str) -> Dict[str, Any]:
    """Extract JSON object from grok --output-format json stdout."""
    text = output.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {"text": text[-4000:]}


def _ingest_session_cost(session_id: Optional[str], cycle_id: Optional[int]) -> None:
    if not session_id or cycle_id is None:
        return
    try:
        from observability.grok_usage import ingest_headless_session

        ingest_headless_session(session_id, cycle_id)
    except Exception:
        pass


def run_headless(
    prompt: str,
    *,
    mode: GrokMode = "execute",
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    session_id: Optional[str] = None,
    worktree: bool = False,
    yolo: Optional[bool] = None,
    max_turns: Optional[int] = None,
    agents: Optional[List[Dict[str, Any]]] = None,
    extra_args: Optional[List[str]] = None,
    cycle_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run Grok Build headless with mode-appropriate flags.

    Modes:
      plan    — explore/plan only (json output, fewer turns)
      execute — autonomous edits (--yolo, optional --worktree, --check)
      verify  — read-only verification pass
      analyze — parallel subagents via --agents when provided
    """
    if not GROK_BIN or not Path(GROK_BIN).exists():
        return {"skipped": True, "reason": "grok_unavailable"}

    use_yolo = yolo if yolo is not None else mode == "execute"
    turns = max_turns or int(os.getenv("GROK_EVOLUTION_MAX_TURNS", "12"))

    cmd: List[str] = [GROK_BIN, "-p", prompt, "--output-format", "json", "--max-turns", str(turns)]

    if session_id:
        cmd.extend(["--resume", session_id])

    if worktree and mode == "execute":
        cmd.append("--worktree")

    if use_yolo and mode in ("execute", "plan"):
        cmd.append("--yolo")

    if mode == "execute":
        cmd.append("--check")

    if cwd:
        cmd.extend(["--cwd", cwd])

    if agents and mode == "analyze":
        cmd.extend(["--agents", json.dumps(format_agents_for_cli(agents))])

    if mode == "verify":
        cmd.extend(["--disallowed-tools", "Write,search_replace"])

    if extra_args:
        cmd.extend(extra_args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or DEFAULT_TIMEOUT,
            cwd=cwd or os.getcwd(),
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        parsed = _parse_json_output(result.stdout or output)
        sid = parsed.get("sessionId") or parsed.get("session_id")
        _ingest_session_cost(sid, cycle_id)
        return {
            "executed": result.returncode == 0,
            "exit_code": result.returncode,
            "mode": mode,
            "session_id": sid,
            "text": parsed.get("text", parsed.get("result", "")),
            "stop_reason": parsed.get("stopReason"),
            "parsed": parsed,
            "output_tail": output[-2000:],
            "command": " ".join(cmd[:6]) + " ...",
        }
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"executed": False, "error": str(exc), "mode": mode}


def run_plan_prompt(
    prompt: str,
    timeout: Optional[int] = None,
    cwd: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    cycle_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Backward-compatible wrapper — plan-mode headless with JSON output."""
    return run_headless(
        prompt,
        mode="plan",
        timeout=timeout,
        cwd=cwd,
        yolo=False,
        max_turns=int(os.getenv("GROK_PROPOSAL_MAX_TURNS", "6")),
        extra_args=extra_args,
        cycle_id=cycle_id,
    )


def run_evolution_task(
    cycle_id: int,
    task: str,
    *,
    worktree: bool = True,
    timeout: Optional[int] = None,
    best_of_n: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute one surgical evolution in isolated worktree with verification."""
    if os.getenv("GROK_ORCHESTRATION", "subprocess").lower() == "acp":
        from factory_core.grok_acp import run_cycle_via_acp

        prompt = (
            f"RSI-EAF cycle {cycle_id} executable evolution:\n{task}\n\n"
            "Apply ONE minimal surgical change per AGENTS.md. "
            "Ground truth: pytest tests/test_core.py must pass."
        )
        return run_cycle_via_acp(cycle_id, prompt)

    prompt = (
        f"RSI-EAF cycle {cycle_id} executable evolution:\n{task}\n\n"
        "Apply ONE minimal surgical change per AGENTS.md. "
        "Ground truth: pytest tests/test_core.py must pass. "
        "Never commit seeds or .env secrets."
    )
    n = best_of_n or int(os.getenv("GROK_BEST_OF_N", "1"))
    extra: List[str] = []
    if n > 1:
        extra.extend(["--best-of-n", str(n)])

    rules = "Follow .grok/skills/rsi-evolve and rsi-revenue-surfaces skills."
    extra.extend(["--rules", rules])
    return run_headless(
        prompt,
        mode="execute",
        timeout=timeout or int(os.getenv("GROK_EVOLUTION_TIMEOUT_SEC", "180")),
        worktree=worktree,
        yolo=True,
        cycle_id=cycle_id,
        extra_args=extra,
    )


def run_parallel_analysis(cycle_id: int, analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Spawn explore-style subagents for bottleneck + revenue surface analysis."""
    if os.getenv("GROK_PARALLEL_ANALYSIS", "true").lower() not in {"1", "true", "yes"}:
        return {"skipped": True, "reason": "GROK_PARALLEL_ANALYSIS disabled"}

    prompt = (
        f"RSI-EAF cycle {cycle_id} parallel analysis.\n"
        f"Data: {json.dumps(analysis, default=str)[:6000]}\n\n"
        "Return JSON: {\"bottleneck_insights\":[], \"revenue_hypotheses\":[], "
        "\"xrpl_verification_steps\":[]}"
    )
    if os.getenv("GROK_ORCHESTRATION", "subprocess").lower() == "acp":
        from factory_core.grok_acp import run_cycle_via_acp

        return run_cycle_via_acp(cycle_id, prompt)
    agents = [
        {"name": "bottleneck_explorer", "type": "explore", "prompt": "Find revenue bottlenecks in analysis data."},
        {"name": "treasury_researcher", "type": "explore", "prompt": "Suggest XRPL payment UX improvements for treasury tips."},
    ]
    return run_headless(prompt, mode="analyze", agents=agents, max_turns=8, cycle_id=cycle_id)


def parse_proposals_from_grok(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract proposal objects from Grok JSON/text output."""
    text = result.get("text") or ""
    parsed = result.get("parsed") or {}
    if isinstance(parsed.get("proposals"), list):
        return parsed["proposals"]
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "proposals" in data:
            return data["proposals"]
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            arr = json.loads(match.group())
            if isinstance(arr, list) and arr:
                return arr
        except json.JSONDecodeError:
            pass
    if result.get("executed") and text:
        return [{
            "title": text.split("\n")[0][:120] or "Grok proposal",
            "impact": text[:500],
            "verification": "pytest + XRPL gate verification",
            "source": "grok_build_plan",
        }]
    return []