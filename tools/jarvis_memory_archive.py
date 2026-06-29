"""
Archive jarvis-swarm-memory scheduled workflows — RSI-EAF is factory SSOT for nexus.

Fitness verdict: memory repo 15m cron competes with rsi-eaf nexus_bridge emits.
"""

from __future__ import annotations

from typing import Any, Dict, List

MEMORY_OWNER = "theCeramist"
MEMORY_REPO = "jarvis-swarm-memory"
ARCHIVE_BRANCH = "main"

ARCHIVED_CONTINUOUS = """# ARCHIVED by RSI-EAF factory (2026-06-29)
# Scheduled autonomous cycles moved to rsi-eaf runner + nexus_bridge → jarvis-swarm.
# Manual dispatch only for historical debugging.

name: JARVIS Continuous Autonomous Cycle (ARCHIVED)

on:
  workflow_dispatch:

jobs:
  archived_notice:
    runs-on: ubuntu-latest
    steps:
      - name: Workflow archived
        run: |
          echo "This workflow was archived. Use rsi-eaf factory runner for nexus/economics."
          echo "See: https://github.com/theCeramist/rsi-eaf"
          exit 0
"""

ARCHIVED_SYNC = """# ARCHIVED — rsi-eaf tools/nexus_bridge.py owns jarvis-swarm nexus emits.

name: Sync Rich State to Nexus (ARCHIVED)

on:
  workflow_dispatch:

jobs:
  archived_notice:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Archived. RSI-EAF platform_sync pushes to jarvis-swarm." && exit 0
"""

ARCHIVED_MIRROR = """# ARCHIVED — mirror-state writes conflict with rsi-eaf factory wave merges.

name: Update Mirror State (ARCHIVED)

on:
  workflow_dispatch:

jobs:
  archived_notice:
    runs-on: ubuntu-latest
    steps:
      - run: echo "Archived. Do not push mirror-state over rsi-eaf control-state." && exit 0
"""


def archive_workflow_specs() -> List[Dict[str, str]]:
    return [
        {
            "path": ".github/workflows/jarvis_continuous_cycle.yml",
            "content": ARCHIVED_CONTINUOUS,
            "message": "chore(archive): disable 15m JARVIS cron — rsi-eaf factory SSOT",
        },
        {
            "path": ".github/workflows/sync-to-nexus.yml",
            "content": ARCHIVED_SYNC,
            "message": "chore(archive): disable memory→nexus sync — rsi-eaf nexus_bridge",
        },
        {
            "path": ".github/workflows/update-mirror-state.yml",
            "content": ARCHIVED_MIRROR,
            "message": "chore(archive): disable mirror-state push — prevent nexus drift",
        },
    ]


def push_memory_workflow_archive(dry_run: bool = False) -> Dict[str, Any]:
    """Push archived workflow stubs to jarvis-swarm-memory via GitHub API."""
    from tools.github_client import push_files

    if dry_run:
        return {"dry_run": True, "files": [s["path"] for s in archive_workflow_specs()]}

    files = [
        {"path": spec["path"], "content": spec["content"]}
        for spec in archive_workflow_specs()
    ]
    result = push_files(
        MEMORY_OWNER,
        MEMORY_REPO,
        files,
        "chore(archive): RSI-EAF factory archives competing memory cron workflows",
        branch=ARCHIVE_BRANCH,
    )
    return {
        "repo": f"{MEMORY_OWNER}/{MEMORY_REPO}",
        "archived_workflows": [f["path"] for f in files],
        "push": result,
        "fitness_verdict": "memory_cron_archived_for_factory_use",
    }