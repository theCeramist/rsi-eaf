"""
Shared GitHub REST client — single-commit multi-file push (mirrors MCP push_files).
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional

import httpx

GITHUB_API = "https://api.github.com"


def github_token() -> Optional[str]:
    return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")


def github_headers() -> Dict[str, str]:
    token = github_token()
    if not token:
        return {}
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_file_sha(owner: str, repo: str, path: str, branch: str = "main") -> Optional[str]:
    token = github_token()
    if not token:
        return None
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    try:
        response = httpx.get(
            url,
            headers=github_headers(),
            params={"ref": branch},
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json().get("sha")
    except httpx.HTTPError:
        pass
    return None


def fetch_repo_json(owner: str, repo: str, path: str, branch: str = "main") -> Optional[Dict[str, Any]]:
    token = github_token()
    if not token:
        return None
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    try:
        response = httpx.get(
            url,
            headers=github_headers(),
            params={"ref": branch},
            timeout=30.0,
        )
        if response.status_code != 200:
            return None
        raw = response.json().get("content", "")
        decoded = base64.b64decode(raw).decode("utf-8")
        import json

        return json.loads(decoded)
    except (httpx.HTTPError, ValueError):
        return None


def push_file(
    owner: str,
    repo: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
) -> Dict[str, Any]:
    """Single-file Contents API push (fallback)."""
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    sha = get_file_sha(owner, repo, path, branch)
    if sha:
        payload["sha"] = sha

    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    try:
        response = httpx.put(url, headers=github_headers(), json=payload, timeout=60.0)
        ok = response.status_code in {200, 201}
        return {
            "success": ok,
            "path": path,
            "status_code": response.status_code,
            "detail": "ok" if ok else response.text[-300:],
        }
    except httpx.HTTPError as exc:
        return {"success": False, "path": path, "error": str(exc)}


def push_files(
    owner: str,
    repo: str,
    files: List[Dict[str, str]],
    message: str,
    branch: str = "main",
) -> Dict[str, Any]:
    """
    Push multiple files in a single commit via Git Trees API.
    files: [{"path": "...", "content": "..."}]
    """
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}
    if not files:
        return {"success": False, "skipped": True, "reason": "no_files"}

    headers = github_headers()
    ref_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/refs/heads/{branch}"
    try:
        ref_resp = httpx.get(ref_url, headers=headers, timeout=30.0)
        if ref_resp.status_code != 200:
            return {"success": False, "error": f"ref_fetch_{ref_resp.status_code}"}
        base_sha = ref_resp.json()["object"]["sha"]

        commit_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/commits/{base_sha}"
        commit_resp = httpx.get(commit_url, headers=headers, timeout=30.0)
        if commit_resp.status_code != 200:
            return {"success": False, "error": f"commit_fetch_{commit_resp.status_code}"}
        base_tree_sha = commit_resp.json()["tree"]["sha"]

        tree_items = []
        for item in files:
            blob_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/blobs"
            blob_resp = httpx.post(
                blob_url,
                headers=headers,
                json={
                    "content": item["content"],
                    "encoding": "utf-8",
                },
                timeout=60.0,
            )
            if blob_resp.status_code not in {200, 201}:
                return {
                    "success": False,
                    "error": f"blob_{item['path']}_{blob_resp.status_code}",
                }
            tree_items.append({
                "path": item["path"],
                "mode": "100644",
                "type": "blob",
                "sha": blob_resp.json()["sha"],
            })

        tree_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/trees"
        tree_resp = httpx.post(
            tree_url,
            headers=headers,
            json={"base_tree": base_tree_sha, "tree": tree_items},
            timeout=60.0,
        )
        if tree_resp.status_code not in {200, 201}:
            return {"success": False, "error": f"tree_{tree_resp.status_code}"}
        new_tree_sha = tree_resp.json()["sha"]

        new_commit_url = f"{GITHUB_API}/repos/{owner}/{repo}/git/commits"
        commit_create = httpx.post(
            new_commit_url,
            headers=headers,
            json={
                "message": message,
                "tree": new_tree_sha,
                "parents": [base_sha],
            },
            timeout=60.0,
        )
        if commit_create.status_code not in {200, 201}:
            return {"success": False, "error": f"commit_create_{commit_create.status_code}"}
        new_commit_sha = commit_create.json()["sha"]

        update_ref = httpx.patch(
            ref_url,
            headers=headers,
            json={"sha": new_commit_sha, "force": False},
            timeout=30.0,
        )
        ok = update_ref.status_code == 200
        return {
            "success": ok,
            "commit_sha": new_commit_sha if ok else None,
            "files_pushed": len(files),
            "paths": [f["path"] for f in files],
            "status_code": update_ref.status_code,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}


def post_issue_comment(
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
) -> Dict[str, Any]:
    token = github_token()
    if not token:
        return {"success": False, "skipped": True, "reason": "no_github_token"}
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"
    try:
        response = httpx.post(
            url,
            headers=github_headers(),
            json={"body": body},
            timeout=30.0,
        )
        ok = response.status_code == 201
        data = response.json() if ok else {}
        return {
            "success": ok,
            "comment_id": data.get("id"),
            "html_url": data.get("html_url"),
            "status_code": response.status_code,
        }
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}