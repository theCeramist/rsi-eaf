"""
PR-based evolution workflow — branch + push + draft PR (optional evolution path).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from tools.github_client import github_headers, github_token, push_files

GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
EVOLUTION_VIA_PR = os.getenv("EVOLUTION_VIA_PR", "false").lower() in {"1", "true", "yes"}


def create_branch(branch: str, from_ref: str = "main") -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    ref_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs/heads/{from_ref}"
    try:
        ref_resp = httpx.get(ref_url, headers=github_headers(), timeout=30.0)
        if ref_resp.status_code != 200:
            return {"success": False, "error": f"ref_{ref_resp.status_code}"}
        sha = ref_resp.json()["object"]["sha"]
        create_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/refs"
        create_resp = httpx.post(
            create_url,
            headers=github_headers(),
            json={"ref": f"refs/heads/{branch}", "sha": sha},
            timeout=30.0,
        )
        ok = create_resp.status_code == 201
        exists = create_resp.status_code == 422
        return {
            "success": ok or exists,
            "branch": branch,
            "created": ok,
            "already_exists": exists,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def create_pull_request(
    branch: str,
    title: str,
    body: str,
    base: str = "main",
    draft: bool = True,
) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/pulls"
    try:
        response = httpx.post(
            url,
            headers=github_headers(),
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": base,
                "draft": draft,
            },
            timeout=30.0,
        )
        ok = response.status_code == 201
        data = response.json() if ok else {}
        return {
            "success": ok,
            "pr_number": data.get("number"),
            "html_url": data.get("html_url"),
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def evolution_pr_flow(
    cycle_id: int,
    files: List[Dict[str, str]],
    task_summary: str,
) -> Dict[str, Any]:
    """Create branch, push files, open draft PR for evolution review."""
    if not EVOLUTION_VIA_PR:
        return {"success": False, "skipped": True, "reason": "EVOLUTION_VIA_PR disabled"}

    branch = f"evolution/cycle-{cycle_id}"
    branch_result = create_branch(branch)
    if not branch_result.get("success"):
        return {"success": False, "branch": branch_result}

    push_result = push_files(
        GITHUB_OWNER,
        GITHUB_REPO,
        files,
        f"evolution: cycle {cycle_id} — {task_summary[:80]}",
        branch,
    )
    if not push_result.get("success"):
        return {"success": False, "push": push_result}

    pr_result = create_pull_request(
        branch,
        title=f"[Evolution] Cycle {cycle_id}: {task_summary[:60]}",
        body=(
            f"Automated evolution PR for cycle {cycle_id}.\n\n"
            f"Task: {task_summary}\n\n"
            "Merge after pytest CI passes."
        ),
        draft=True,
    )
    return {
        "success": pr_result.get("success", False),
        "branch": branch,
        "push": push_result,
        "pr": pr_result,
    }