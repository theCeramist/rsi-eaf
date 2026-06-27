"""
Publish revenue surfaces to GitHub (gist + repo docs) for distribution.
"""

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", "published"))
DOCS_DIR = Path("docs")
GITHUB_OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
GITHUB_REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
GROK_BIN = os.getenv("GROK_BIN", os.path.expanduser("~/.grok/bin/grok.exe"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_revenue_surfaces_markdown(
    cycle_id: int,
    featured: Dict[str, str],
    treasury_address: str,
) -> str:
    rows = [
        ("Factory index", os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app/")),
        ("Tip page", featured.get("tip_page", "")),
        ("Agent tip manifest", featured.get("tip_manifest", "")),
        ("Paid briefing", featured.get("briefing_page", "")),
    ]
    table = "\n".join(f"| {label} | {url or 'n/a'} |" for label, url in rows if url or label == "Factory index")
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

GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"


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
    return {
        "github_repo": GITHUB_REPO_URL,
        "github_revenue_doc": f"{GITHUB_REPO_URL}/blob/main/docs/REVENUE_SURFACES.md",
        "github_tip_manifest": f"{GITHUB_REPO_URL}/blob/main/docs/tip-manifest.json",
        "github_issue": f"{GITHUB_REPO_URL}/issues/1",
        "vercel_index": os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app/"),
        "vercel_tip_manifest": os.getenv(
            "FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app"
        ).rstrip("/")
        + "/tip-manifest.json",
    }


def distribution_file_bundle(cycle_id: int) -> List[Dict[str, str]]:
    md = _read_text(DOCS_DIR / "REVENUE_SURFACES.md")
    manifest = _read_text(DOCS_DIR / "tip-manifest.json")
    readme = _read_text(Path("README.md"))
    if "## Revenue Surfaces" not in readme:
        readme += f"""

## Revenue Surfaces

Public factory outputs and XRPL payment endpoints (cycle {cycle_id}):

- **Live index:** https://published-zeta.vercel.app/
- **Tip manifest:** https://published-zeta.vercel.app/tip-manifest.json
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