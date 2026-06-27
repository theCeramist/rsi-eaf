"""
Grok Build session token usage ingestion for RSI-EAF.

Reads per-message/turn usage from Grok session artifacts on disk:
  ~/.grok/sessions/<encoded-cwd>/<session-id>/updates.jsonl
  ~/.grok/sessions/<encoded-cwd>/<session-id>/signals.json

Token deltas are derived from peak context `totalTokens` per promptId turn.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

GROK_HOME = Path(os.getenv("GROK_HOME", os.path.expanduser("~/.grok")))


@dataclass
class TurnUsage:
    prompt_id: str
    tokens_delta: int
    peak_context_tokens: int
    user_preview: str = ""
    completed: bool = False


@dataclass
class GrokUsageSnapshot:
    session_id: str
    session_dir: str
    tokens_new: int
    turns_new: List[TurnUsage] = field(default_factory=list)
    context_tokens_used: int = 0
    context_window_tokens: int = 0
    bootstrapped: bool = False
    source: str = "grok_session_updates"


def encode_cwd(cwd: str) -> str:
    return quote(os.path.abspath(cwd), safe="")


def _norm_cwd(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def find_active_session(cwd: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Resolve the active Grok session for a workspace directory."""
    cwd = cwd or os.getcwd()
    active_path = GROK_HOME / "active_sessions.json"
    if active_path.exists():
        try:
            sessions = json.loads(active_path.read_text(encoding="utf-8"))
            for sess in sessions:
                if _norm_cwd(sess.get("cwd", "")) == _norm_cwd(cwd):
                    return sess
        except (json.JSONDecodeError, OSError):
            pass

    encoded = encode_cwd(cwd)
    group_dir = GROK_HOME / "sessions" / encoded
    if not group_dir.exists():
        return None

    candidates: List[tuple[str, Path]] = []
    for child in group_dir.iterdir():
        if child.is_dir() and (child / "summary.json").exists():
            candidates.append((child.name, child))

    if not candidates:
        return None

    def _updated_at(path: Path) -> str:
        try:
            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            return summary.get("updated_at", "")
        except (json.JSONDecodeError, OSError):
            return ""

    candidates.sort(key=lambda item: _updated_at(item[1]), reverse=True)
    session_id, session_dir = candidates[0]
    return {"session_id": session_id, "cwd": cwd, "session_dir": str(session_dir)}


def _extract_user_preview(text: str) -> str:
    match = re.search(r"<user_query>\s*(.*?)\s*</user_query>", text, re.DOTALL)
    preview = match.group(1) if match else text
    preview = re.sub(r"\s+", " ", preview).strip()
    return preview[:120]


def parse_session_usage(session_dir: Path) -> Dict[str, Any]:
    """Parse updates.jsonl into per-turn peaks and completion markers."""
    updates_path = session_dir / "updates.jsonl"
    peak_by_prompt: Dict[str, int] = {}
    prompt_order: List[str] = []
    seen_prompts: Set[str] = set()
    completed_prompts: Set[str] = set()
    user_preview_by_prompt: Dict[str, str] = {}
    pending_user_text = ""

    if not updates_path.exists():
        return {
            "turns": [],
            "completed_prompt_ids": set(),
            "total_peak_tokens": 0,
        }

    for line in updates_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        params = obj.get("params", {})
        update = params.get("update", {})
        meta = params.get("_meta", {})
        kind = update.get("sessionUpdate")

        if kind == "user_message_chunk":
            pending_user_text = update.get("content", {}).get("text", pending_user_text)

        if kind == "turn_completed":
            prompt_id = update.get("prompt_id")
            if prompt_id:
                completed_prompts.add(prompt_id)
                if pending_user_text and prompt_id not in user_preview_by_prompt:
                    user_preview_by_prompt[prompt_id] = _extract_user_preview(pending_user_text)
                pending_user_text = ""

        prompt_id = meta.get("promptId")
        total_tokens = meta.get("totalTokens")
        if prompt_id and total_tokens is not None:
            peak_by_prompt[prompt_id] = max(peak_by_prompt.get(prompt_id, 0), int(total_tokens))
            if prompt_id not in seen_prompts:
                seen_prompts.add(prompt_id)
                prompt_order.append(prompt_id)
                if pending_user_text and prompt_id not in user_preview_by_prompt:
                    user_preview_by_prompt[prompt_id] = _extract_user_preview(pending_user_text)

    turns: List[TurnUsage] = []
    prev_peak = 0
    for prompt_id in prompt_order:
        peak = peak_by_prompt.get(prompt_id, prev_peak)
        turns.append(
            TurnUsage(
                prompt_id=prompt_id,
                tokens_delta=max(0, peak - prev_peak),
                peak_context_tokens=peak,
                user_preview=user_preview_by_prompt.get(prompt_id, ""),
                completed=prompt_id in completed_prompts,
            )
        )
        prev_peak = peak

    return {
        "turns": turns,
        "completed_prompt_ids": completed_prompts,
        "total_peak_tokens": prev_peak,
    }


def read_signals(session_dir: Path) -> Dict[str, Any]:
    signals_path = session_dir / "signals.json"
    if not signals_path.exists():
        return {}
    try:
        return json.loads(signals_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def collect_new_usage(
    watermark: Optional[Dict[str, Any]] = None,
    cwd: Optional[str] = None,
) -> Optional[GrokUsageSnapshot]:
    """
    Return token usage for Grok turns not yet recorded in the factory watermark.

    On first encounter with a session, bootstraps the watermark without charging
    (avoids double-billing historical manual cost entries).
    """
    active = find_active_session(cwd=cwd)
    if not active:
        print("[GrokUsage] No active Grok session found for this workspace.")
        return None

    session_id = active["session_id"]
    session_dir = Path(active.get("session_dir") or (GROK_HOME / "sessions" / encode_cwd(active["cwd"]) / session_id))
    if not session_dir.exists():
        print(f"[GrokUsage] Session directory missing: {session_dir}")
        return None

    parsed = parse_session_usage(session_dir)
    signals = read_signals(session_dir)
    context_used = int(signals.get("contextTokensUsed", 0) or 0)
    context_window = int(signals.get("contextWindowTokens", 0) or 0)

    watermark = watermark or {}
    ingested: Set[str] = set(watermark.get("ingested_prompt_ids", []))
    prior_context = int(watermark.get("context_tokens_used", 0) or 0)
    prior_session = watermark.get("session_id")

    if prior_session != session_id:
        ingested = set()
        prior_context = 0

    completed_ids = parsed["completed_prompt_ids"]
    if not ingested and completed_ids:
        ingested = set(completed_ids)
        return GrokUsageSnapshot(
            session_id=session_id,
            session_dir=str(session_dir),
            tokens_new=0,
            turns_new=[],
            context_tokens_used=context_used,
            context_window_tokens=context_window,
            bootstrapped=True,
        )

    new_turns: List[TurnUsage] = []
    tokens_new = 0
    in_progress_prompt = watermark.get("in_progress_prompt_id")
    in_progress_peak_billed = int(watermark.get("in_progress_peak_billed", 0) or 0)

    for turn in parsed["turns"]:
        if turn.prompt_id in ingested:
            continue
        if turn.completed:
            new_turns.append(turn)
            tokens_new += turn.tokens_delta

    if parsed["turns"]:
        last_turn = parsed["turns"][-1]
        if not last_turn.completed and last_turn.prompt_id not in ingested:
            if in_progress_prompt == last_turn.prompt_id:
                incremental = max(0, last_turn.peak_context_tokens - in_progress_peak_billed)
            else:
                incremental = last_turn.tokens_delta

            if incremental > 0:
                in_progress = TurnUsage(
                    prompt_id=last_turn.prompt_id,
                    tokens_delta=incremental,
                    peak_context_tokens=last_turn.peak_context_tokens,
                    user_preview=last_turn.user_preview,
                    completed=False,
                )
                new_turns.append(in_progress)
                tokens_new += incremental

    if tokens_new == 0 and context_used > prior_context:
        tokens_new = context_used - prior_context

    return GrokUsageSnapshot(
        session_id=session_id,
        session_dir=str(session_dir),
        tokens_new=tokens_new,
        turns_new=new_turns,
        context_tokens_used=context_used,
        context_window_tokens=context_window,
        bootstrapped=False,
    )


def build_watermark_after_ingest(snapshot: GrokUsageSnapshot) -> Dict[str, Any]:
    """Persist watermark after logging costs for a cycle."""
    session_dir = Path(snapshot.session_dir)
    parsed = parse_session_usage(session_dir)
    ingested = set(parsed["completed_prompt_ids"])

    watermark: Dict[str, Any] = {
        "session_id": snapshot.session_id,
        "context_tokens_used": snapshot.context_tokens_used,
        "ingested_prompt_ids": sorted(ingested),
        "session_dir": snapshot.session_dir,
    }

    if parsed["turns"] and not parsed["turns"][-1].completed:
        last_turn = parsed["turns"][-1]
        watermark["in_progress_prompt_id"] = last_turn.prompt_id
        watermark["in_progress_peak_billed"] = last_turn.peak_context_tokens
    else:
        watermark.pop("in_progress_prompt_id", None)
        watermark.pop("in_progress_peak_billed", None)

    return watermark