"""
Published artifact hygiene — keep deploy bundle small while preserving latest surfaces.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.integration import PUBLISHED_DEPLOY_MAX_HTML, PUBLISHED_DIR as _PUBLISHED_DIR

PUBLISHED_DIR = Path(os.getenv("PUBLISHED_DIR", _PUBLISHED_DIR))
ARCHIVE_DIR = PUBLISHED_DIR / "archive"

_PREFIX_PATTERNS = (
    ("tip-cycle-", r"tip-cycle-(\d+)"),
    ("briefing-cycle-", r"briefing-cycle-(\d+)"),
    ("cycle-", r"cycle-(\d+)"),
    ("mythos-cycle-", r"mythos-cycle-(\d+)"),
    ("micro-tool-cycle-", r"micro-tool-cycle-(\d+)"),
)

_KEEP_ALWAYS = {
    "index.html",
    "tip-manifest.json",
    "service-catalog.json",
    "sitemap.xml",
    "vercel.json",
}


def _cycle_num(name: str, pattern: str) -> int:
    match = re.search(pattern, name)
    return int(match.group(1)) if match else 0


def _latest_per_prefix(html_files: List[Path]) -> Dict[str, Path]:
    best: Dict[str, Tuple[int, Path]] = {}
    for path in html_files:
        name = path.name
        if name in _KEEP_ALWAYS:
            continue
        for prefix, pat in _PREFIX_PATTERNS:
            if name.startswith(prefix):
                num = _cycle_num(name, pat)
                prev = best.get(prefix)
                if prev is None or num > prev[0]:
                    best[prefix] = (num, path)
                break
    return {k: v[1] for k, v in best.items()}


def prune_published_for_deploy(
    cycle_id: Optional[int] = None,
    max_html: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Move stale HTML to published/archive/; retain latest per surface type + always-keep files.
    """
    max_html = max_html if max_html is not None else PUBLISHED_DEPLOY_MAX_HTML
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    html_files = sorted(PUBLISHED_DIR.glob("*.html"))
    keep_paths = set(_KEEP_ALWAYS)
    for path in _latest_per_prefix(html_files).values():
        keep_paths.add(path.name)

    if cycle_id is not None:
        for prefix, _ in _PREFIX_PATTERNS:
            for path in sorted(PUBLISHED_DIR.glob(f"{prefix}{cycle_id}-*.html"), reverse=True):
                keep_paths.add(path.name)
                break

    keep_list = sorted(keep_paths)
    if len(keep_list) > max_html:
        keep_list = keep_list[:max_html]

    archived: List[str] = []
    kept: List[str] = []
    for path in html_files:
        if path.name == "index.html" or path.name in keep_list:
            kept.append(path.name)
            continue
        dest = ARCHIVE_DIR / path.name
        if dest.exists():
            dest.unlink()
        shutil.move(str(path), str(dest))
        archived.append(path.name)

    return {
        "archived_count": len(archived),
        "kept_count": len(kept),
        "archived_sample": archived[:8],
        "kept": kept,
        "archive_dir": str(ARCHIVE_DIR),
    }