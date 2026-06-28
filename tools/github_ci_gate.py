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
NEXUS_CI_OWNER = os.getenv("NEXUS_CI_GATE_OWNER", os.getenv("NEXUS_GITHUB_OWNER", "theCeramist"))
NEXUS_CI_REPO = os.getenv("NEXUS_CI_GATE_REPO", os.getenv("NEXUS_GITHUB_REPO", "jarvis-swarm"))
CI_WORKFLOW_NAME = os.getenv("GITHUB_CI_WORKFLOW", "Factory CI")
def _ci_gate_enabled() -> bool:
    return os.getenv("GITHUB_CI_GATE", "true").lower() in {"1", "true", "yes"}


def _hygiene_job_passed(owner: str, repo: str, run_id: int) -> bool:
    """True when Pre-Deploy Validation & Hygiene succeeded (nexus-portal-ci)."""
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            headers=github_headers(),
            timeout=30.0,
        )
        if response.status_code != 200:
            return False
        for job in response.json().get("jobs", []):
            if job.get("name") == "Pre-Deploy Validation & Hygiene":
                return job.get("conclusion") == "success"
    except httpx.HTTPError:
        return False
    return False


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
        run_id = latest.get("id")
        hygiene_pass = False
        if (
            conclusion == "failure"
            and repo == NEXUS_CI_REPO
            and run_id
            and os.getenv("NEXUS_CI_HYGIENE_GATE", "true").lower() in {"1", "true", "yes"}
        ):
            hygiene_pass = _hygiene_job_passed(owner, repo, run_id)

        effective_conclusion = "success" if hygiene_pass else conclusion
        blocking = effective_conclusion == "failure" or (
            status == "in_progress" and _ci_gate_enabled()
        )
        return {
            "success": True,
            "run_id": run_id,
            "workflow": latest.get("name"),
            "status": status,
            "conclusion": conclusion,
            "effective_conclusion": effective_conclusion,
            "hygiene_pass": hygiene_pass,
            "html_url": latest.get("html_url"),
            "blocking": blocking and effective_conclusion == "failure",
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