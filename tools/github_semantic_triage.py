"""
GitHub issue triage for payment friction — search + similarity hints.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

import httpx

from tools.github_client import github_headers, github_token

GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")

PAYMENT_QUERIES = [
    "tip treasury payment XRPL",
    "destination tag briefing unlock",
    "revenue memo verified",
]


def search_payment_issues(query: str, limit: int = 5) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    q = f"repo:{GITHUB_OWNER}/{GITHUB_REPO} is:issue {query}"
    url = "https://api.github.com/search/issues"
    try:
        response = httpx.get(
            url,
            headers=github_headers(),
            params={"q": q, "per_page": limit},
            timeout=30.0,
        )
        ok = response.status_code == 200
        items = response.json().get("items", []) if ok else []
        return {
            "success": ok,
            "query": query,
            "count": len(items),
            "issues": [
                {
                    "number": i.get("number"),
                    "title": i.get("title"),
                    "state": i.get("state"),
                    "url": i.get("html_url"),
                }
                for i in items
            ],
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def triage_payment_friction() -> Dict[str, Any]:
    """Aggregate payment-related open issues for evolution prioritization."""
    results: List[Dict[str, Any]] = []
    for query in PAYMENT_QUERIES:
        results.append(search_payment_issues(query))
    open_issues = []
    seen = set()
    for block in results:
        for issue in block.get("issues", []):
            num = issue.get("number")
            if num and num not in seen and issue.get("state") == "open":
                seen.add(num)
                open_issues.append(issue)
    return {
        "searches": results,
        "open_payment_issues": open_issues,
        "friction_detected": len(open_issues) > 0,
        "recommendation": (
            "Prioritize payment_intent hardening and support issue response"
            if open_issues
            else None
        ),
    }