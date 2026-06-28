"""
GitHub issues automation — milestones, cycle comments, supporter tracking.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from tools.github_client import github_headers, github_token, post_issue_comment

GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
GITHUB_SUPPORT_ISSUE = int(os.getenv("GITHUB_SUPPORT_ISSUE", "1"))


def build_cycle_milestone_comment(
    cycle_id: int,
    net: Dict[str, Any],
    treasury_address: str,
    surfaces: Dict[str, str],
) -> str:
    return f"""### Factory cycle {cycle_id} milestone

**Time:** {datetime.now(timezone.utc).isoformat()}

| Metric | Value |
|--------|-------|
| Net USD (est) | {net.get('net_usd_est')} |
| Total revenue | {net.get('total_revenue_usd_est')} |
| Organic revenue | {net.get('organic_revenue_usd_est', 0)} |
| Treasury | `{treasury_address}` |

**Surfaces:** {surfaces.get('tip_page', 'n/a')} · {surfaces.get('briefing_page', 'n/a')}

Payments with `type: revenue` memos are ingested on the next cycle.
"""


def post_cycle_milestone_comment(
    cycle_id: int,
    net: Dict[str, Any],
    treasury_address: str,
    surfaces: Dict[str, str],
) -> Dict[str, Any]:
    if not os.getenv("GITHUB_CYCLE_COMMENTS", "true").lower() in {"1", "true", "yes"}:
        return {"success": False, "skipped": True, "reason": "GITHUB_CYCLE_COMMENTS disabled"}
    body = build_cycle_milestone_comment(cycle_id, net, treasury_address, surfaces)
    return post_issue_comment(GITHUB_OWNER, GITHUB_REPO, GITHUB_SUPPORT_ISSUE, body)


def list_open_issues(limit: int = 10) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues"
    try:
        response = httpx.get(
            url,
            headers=github_headers(),
            params={"state": "open", "per_page": limit},
            timeout=30.0,
        )
        ok = response.status_code == 200
        issues = response.json() if ok else []
        return {
            "success": ok,
            "count": len(issues),
            "issues": [
                {"number": i.get("number"), "title": i.get("title"), "labels": [l.get("name") for l in i.get("labels", [])]}
                for i in issues
            ],
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def refresh_support_issue(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> Dict[str, Any]:
    """Delegate to github_distribution body builder — kept for import stability."""
    from tools.github_distribution import refresh_support_issue as _refresh

    return _refresh(cycle_id, featured, treasury_address)