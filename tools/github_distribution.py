"""
Publish revenue surfaces to GitHub (gist + repo docs) for distribution.
"""

import base64
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config.integration import (
    DISTRIBUTION_EVERY_N_CYCLES,
    FACTORY_PUBLIC_BASE_URL,
    GITHUB_BRANCH,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_REPO_URL,
    GITHUB_SUPPORT_ISSUE,
    revenue_surface_rows,
)

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
DOCS_DIR = Path("docs")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_revenue_surfaces_markdown(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> str:
    rows = revenue_surface_rows(featured, cycle_id)
    table = "\n".join(f"| {label} | {url or 'n/a'} |" for label, url in rows)
    product_id = f"briefing-cycle-{cycle_id}"
    return f"""# RSI-EAF Revenue Surfaces (Cycle {cycle_id})

Updated: {datetime.now(timezone.utc).isoformat()}

## Live surfaces

| Surface | URL |
|---------|-----|
{table}

## Treasury (XRPL Testnet)

```
{treasury_address}
```

## Tip payment memo

```json
{{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip","source":"tip_manifest"}}
```

## Briefing unlock memo

```json
{{"type":"revenue","amount_usd_est":2.0,"product_id":"{product_id}","notes":"unlock {product_id}"}}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
"""




def _github_token() -> Optional[str]:
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def _github_headers() -> Dict[str, str]:
    token = _github_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_file_sha(path: str) -> Optional[str]:
    token = _github_token()
    if not token:
        return None
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        response = httpx.get(
            url,
            headers=_github_headers(),
            params={"ref": GITHUB_BRANCH},
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("sha")
    except httpx.HTTPError:
        pass
    return None


def push_file_to_github(path: str, content: str, message: str) -> Dict[str, Any]:
    token = _github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    sha = _get_file_sha(path)
    if sha:
        payload["sha"] = sha

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    try:
        response = httpx.put(url, headers=_github_headers(), json=payload, timeout=60.0)
        ok = response.status_code in {200, 201}
        return {
            "success": ok,
            "path": path,
            "status_code": response.status_code,
            "detail": response.text[-300:] if not ok else "ok",
        }
    except httpx.HTTPError as exc:
        return {"success": False, "path": path, "error": str(exc)}


def push_distribution_to_github(cycle_id: int) -> Dict[str, Any]:
    """Push docs bundle to GitHub in a single commit."""
    from tools.github_client import push_files, push_file

    files = distribution_file_bundle(cycle_id)
    message = f"docs: refresh revenue surfaces (cycle {cycle_id})"
    batch = push_files(GITHUB_OWNER, GITHUB_REPO, files, message, GITHUB_BRANCH)
    if batch.get("success"):
        return {
            "pushed": True,
            "files_attempted": len(files),
            "files_pushed": len(files),
            "commit_sha": batch.get("commit_sha"),
            "results": [batch],
            "urls": distribution_urls(cycle_id),
        }
    results = [push_file(GITHUB_OWNER, GITHUB_REPO, item["path"], item["content"], message, GITHUB_BRANCH) for item in files]
    pushed = [r for r in results if r.get("success")]
    return {
        "pushed": len(pushed) > 0,
        "files_attempted": len(files),
        "files_pushed": len(pushed),
        "results": results,
        "batch_error": batch.get("error"),
        "urls": distribution_urls(cycle_id),
    }


def build_support_issue_body(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> str:
    from tools.distribution_tools import canonical_tip_url

    tip = canonical_tip_url(cycle_id) or featured.get("tip_page", "n/a")
    return f"""## RSI-EAF Revenue Surfaces — Cycle {cycle_id}

Updated: {datetime.now(timezone.utc).isoformat()}

### Pay (easiest path)
- **Treasury:** `{treasury_address}`
- **Destination Tag `1`** → $1.00 verified tip
- **Tip page:** {tip}
- **Manifest:** {featured.get('tip_manifest', 'n/a')}

### Briefing unlock
- Tag `2` or memo `briefing` → $2.00
- **Page:** {featured.get('briefing_page', 'n/a')}

### Verify on XRPL testnet
Payments ingested automatically on the next factory cycle.
"""


def refresh_support_issue(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> Dict[str, Any]:
    token = _github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    body = build_support_issue_body(cycle_id, featured, treasury_address)
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/issues/{GITHUB_SUPPORT_ISSUE}"
    try:
        response = httpx.patch(
            url,
            headers=_github_headers(),
            json={"title": f"RSI-EAF Support & Revenue Surfaces (cycle {cycle_id})", "body": body},
            timeout=30.0,
        )
        ok = response.status_code == 200
        return {
            "success": ok,
            "issue_updated": ok,
            "issue_number": GITHUB_SUPPORT_ISSUE,
            "issue_url": f"{GITHUB_REPO_URL}/issues/{GITHUB_SUPPORT_ISSUE}",
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def maybe_push_distribution(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
    force: bool = False,
    factory_state: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Push GitHub docs + refresh support issue every N cycles (or when forced).
    """
    due = force or (cycle_id % DISTRIBUTION_EVERY_N_CYCLES == 0)
    if not due:
        return {"pushed": False, "skipped": True, "reason": f"not due (every {DISTRIBUTION_EVERY_N_CYCLES} cycles)"}

    from tools.github_ci_gate import block_distribution_if_ci_red

    ci_block = block_distribution_if_ci_red()
    if ci_block and not force:
        return {"pushed": False, "skipped": True, "reason": ci_block, "ci_blocked": True}

    write_local_distribution_artifacts(cycle_id, featured, treasury_address)
    push_result = push_distribution_to_github(cycle_id)
    issue_result = refresh_support_issue(cycle_id, featured, treasury_address)

    from tools.gist_distribution import maybe_publish_tip_gist
    from tools.github_issues import post_cycle_milestone_comment
    from tools.github_releases import maybe_create_cycle_release
    from observability.economic_ledger import ledger

    release_result = maybe_create_cycle_release(
        cycle_id, treasury_address=treasury_address, factory_state=factory_state, force=force
    )
    gist_result = maybe_publish_tip_gist(
        cycle_id, featured, treasury_address, factory_state=factory_state, force=force
    )
    comment_result = post_cycle_milestone_comment(
        cycle_id,
        ledger.calculate_net(),
        treasury_address,
        featured,
    )

    urls = distribution_urls(cycle_id)
    if gist_result.get("gist_url"):
        urls["gist_url"] = gist_result["gist_url"]
    if release_result.get("html_url"):
        urls["github_release"] = release_result["html_url"]

    if factory_state is not None:
        factory_state.set_github_distribution({
            **urls,
            "cycle_id": cycle_id,
            "canonical_tip_url": featured.get("canonical_tip_page"),
        })

    return {
        "due": due,
        "pushed": push_result.get("pushed", False),
        "issue_updated": issue_result.get("issue_updated", False),
        "gist_published": gist_result.get("published", False),
        "release_created": release_result.get("created", False),
        "cycle_comment": comment_result.get("success", False),
        "push": push_result,
        "release": release_result,
        "issue": issue_result,
        "gist": gist_result,
        "comment": comment_result,
    }


def write_local_distribution_artifacts(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> Dict[str, Path]:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = DOCS_DIR / "REVENUE_SURFACES.md"
    md_path.write_text(
        build_revenue_surfaces_markdown(cycle_id, featured, treasury_address),
        encoding="utf-8",
    )
    manifest_src = PUBLISHED_DIR / "tip-manifest.json"
    manifest_dst = DOCS_DIR / "tip-manifest.json"
    if manifest_src.exists():
        manifest_dst.write_text(manifest_src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"revenue_surfaces": md_path, "tip_manifest": manifest_dst}


def distribution_urls(cycle_id: int) -> Dict[str, str]:
    urls = {
        "github_repo": GITHUB_REPO_URL,
        "github_revenue_doc": f"{GITHUB_REPO_URL}/blob/main/docs/REVENUE_SURFACES.md",
        "github_tip_manifest": f"{GITHUB_REPO_URL}/blob/main/docs/tip-manifest.json",
        "github_issue": f"{GITHUB_REPO_URL}/issues/1",
        "vercel_index": f"{FACTORY_PUBLIC_BASE_URL}/" if FACTORY_PUBLIC_BASE_URL else "",
        "vercel_tip_manifest": f"{FACTORY_PUBLIC_BASE_URL}/tip-manifest.json" if FACTORY_PUBLIC_BASE_URL else "",
    }
    return urls


def distribution_file_bundle(cycle_id: int) -> List[Dict[str, str]]:
    md = _read_text(DOCS_DIR / "REVENUE_SURFACES.md")
    manifest = _read_text(DOCS_DIR / "tip-manifest.json")
    readme = _read_text(Path("README.md"))
    if "## Revenue Surfaces" not in readme:
        readme += f"""

## Revenue Surfaces

Public factory outputs and XRPL payment endpoints (cycle {cycle_id}):

- **Live index:** {FACTORY_PUBLIC_BASE_URL}/
- **Tip manifest:** {FACTORY_PUBLIC_BASE_URL}/tip-manifest.json
- **Docs:** [REVENUE_SURFACES.md](docs/REVENUE_SURFACES.md)

Send XRPL testnet payments to the factory treasury with a `revenue` memo — see docs for templates.
"""
    files = [
        {"path": "docs/REVENUE_SURFACES.md", "content": md},
        {"path": "README.md", "content": readme},
    ]
    if manifest:
        files.append({"path": "docs/tip-manifest.json", "content": manifest})
    return files