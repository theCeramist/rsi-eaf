"""
GitHub Actions CI gate — block distribution when factory-ci is failing.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from tools.github_client import github_headers, github_token

GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
CI_WORKFLOW_NAME = os.getenv("GITHUB_CI_WORKFLOW", "Factory CI")
def _ci_gate_enabled() -> bool:
    return os.getenv("GITHUB_CI_GATE", "true").lower() in {"1", "true", "yes"}


def latest_workflow_run(
    owner: str = GITHUB_OWNER,
    repo: str = GITHUB_REPO,
    branch: str = "main",
) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs"
    try:
        response = httpx.get(
            url,
            headers=github_headers(),
            params={"branch": branch, "per_page": 5},
            timeout=30.0,
        )
        if response.status_code != 200:
            return {"success": False, "status_code": response.status_code}
        runs = response.json().get("workflow_runs", [])
        if not runs:
            return {"success": True, "status": "no_runs", "blocking": False}
        latest = runs[0]
        conclusion = latest.get("conclusion")
        status = latest.get("status")
        blocking = conclusion == "failure" or (status == "in_progress" and _ci_gate_enabled())
        return {
            "success": True,
            "run_id": latest.get("id"),
            "workflow": latest.get("name"),
            "status": status,
            "conclusion": conclusion,
            "html_url": latest.get("html_url"),
            "blocking": blocking and conclusion == "failure",
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def block_distribution_if_ci_red(
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Optional[str]:
    owner = owner or GITHUB_OWNER
    repo = repo or GITHUB_REPO
    """Return block reason if CI gate should skip distribution."""
    if not _ci_gate_enabled():
        return None
    result = latest_workflow_run(owner, repo)
    if result.get("blocking"):
        return f"GitHub CI failed: {result.get('html_url')}"
    return None