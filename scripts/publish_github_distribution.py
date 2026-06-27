"""
Print GitHub distribution bundle for MCP push_files (or manual upload).

Agent harness should call grok_com_github push_files with the JSON payload printed here.
"""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from factory_core.state import FactoryState
from tools.github_distribution import (
    GITHUB_REPO_URL,
    distribution_file_bundle,
    distribution_urls,
    write_local_distribution_artifacts,
)
from tools.distribution_tools import featured_links_for_index
from revenue_engines.base_engine import resolve_treasury


def main() -> None:
    state = FactoryState()
    cycle_id = state.current_cycle
    treasury = resolve_treasury()
    featured = featured_links_for_index(cycle_id)
    write_local_distribution_artifacts(cycle_id, featured, treasury)

    payload = {
        "owner": os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist"),
        "repo": os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf"),
        "branch": "main",
        "message": f"docs: refresh revenue surfaces (cycle {cycle_id})",
        "files": distribution_file_bundle(cycle_id),
        "urls": distribution_urls(cycle_id),
    }
    print(json.dumps(payload, indent=2))
    print(f"\n# Push via MCP push_files or open {GITHUB_REPO_URL}", file=sys.stderr)


if __name__ == "__main__":
    main()