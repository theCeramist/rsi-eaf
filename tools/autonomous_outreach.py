"""
Autonomous outreach — zero human click required for free distribution channels.

Channels (ordered by autonomy):
  1. ntfy.sh public topics (no signup)
  2. GitHub issues on own repo (token already works)
  3. GitHub Discussions (enabled on rsi-eaf)
  4. RSS / social-feed artifacts under published/
  5. Optional: Discord webhook, Telegram bot, Bluesky (when env set)
  6. Gist fallback → public docs file on repo (when gist scope missing)

This module removes "human must click share intent" from the critical path.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from tools.github_client import github_headers, github_token

PUBLISHED = Path(os.getenv("PUBLISHED_DIR", "published"))
LOG_FILE = Path(os.getenv("AUTONOMOUS_OUTREACH_LOG", "observability/autonomous_outreach.jsonl"))
STATE_FILE = Path(os.getenv("AUTONOMOUS_OUTREACH_STATE", "observability/autonomous_outreach_state.json"))
SOCIAL_ACCOUNTS = Path("observability/social_accounts.json")

BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")
TREASURY = os.getenv("FACTORY_TREASURY_ADDRESS", "rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN")
OWNER = os.getenv("GITHUB_DISTRIBUTION_OWNER", "theCeramist")
REPO = os.getenv("GITHUB_DISTRIBUTION_REPO", "rsi-eaf")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "rsi-eaf-factory")
NTFY_BASE = os.getenv("NTFY_BASE", "https://ntfy.sh").rstrip("/")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"schema": "rsi_eaf_autonomous_outreach_state_v1", "last_posts": {}}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_log(record: Dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _share_bundle(cycle_id: int) -> Dict[str, str]:
    pay = f"{BASE}/pay.html"
    agent = f"{BASE}/agent-pay.json"
    hub = f"https://xrpl-ai.org/address/{TREASURY}"
    free_ads = f"{BASE}/free-ads.html"
    handle = os.getenv("X_HANDLE", "PM27319682").lstrip("@")
    # Exclusive posture — human ICP @thatcrypto_guy-class; agents sophisticated only.
    # Do not put raw r-addresses in short text — X blocks crypto addresses for ~7d
    # after new app auth; pay.html is the conversion surface.
    try:
        from factory_core.target_icp import outreach_long, outreach_short

        short = outreach_short(cycle_id, handle)
        long = outreach_long(cycle_id)
    except Exception:
        short = (
            f"RSI-EAF c{cycle_id}: XRPL mainnet factory (real XRP) — crypto-critical humans + "
            f"sophisticated agents only. {pay} · @{handle}"
        )
        long = (
            f"Exclusive RSI-EAF cycle {cycle_id} (XRPL testnet).\n"
            f"Human ICP: @thatcrypto_guy-class (critical, anti-hype).\n"
            f"Agent ICP: x402/settlement-capable only — not toy bots.\n"
            f"Pay Tag 1/2: {pay}\nAgent-pay: {agent}\nHub: {hub}\n"
        )
    return {
        "short": short,
        "long": long,
        "pay": pay,
        "agent": agent,
        "hub": hub,
        "free_ads": free_ads,
        "bounty": "https://github.com/theCeramist/rsi-eaf/issues/178",
        "posture": "critical_exclusive",
        "human_icp": "thatcrypto_guy",
        "agent_icp": "sophisticated_only",
    }


def publish_ntfy(cycle_id: int, text: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Free push channel — no account required for public topics."""
    url = f"{NTFY_BASE}/{NTFY_TOPIC}"
    # ntfy header values must be latin-1/ascii-safe
    safe_title = (title or f"RSI-EAF cycle {cycle_id}").encode("ascii", "replace").decode("ascii")
    headers = {
        "Title": safe_title,
        "Tags": "robot,moneybag,rocket",
        "Priority": "default",
        "Click": f"{BASE}/pay.html",
    }
    try:
        r = httpx.post(url, content=text.encode("utf-8"), headers=headers, timeout=30.0)
        return {
            "channel": "ntfy",
            "success": r.status_code in {200, 201},
            "status_code": r.status_code,
            "topic": NTFY_TOPIC,
            "url": url,
            "body": (r.text or "")[:200],
        }
    except httpx.HTTPError as exc:
        return {"channel": "ntfy", "success": False, "error": str(exc)}


def publish_github_social_issue(cycle_id: int, text: str) -> Dict[str, Any]:
    """Post/update a living social issue on the factory repo (token already works)."""
    token = github_token()
    if not token:
        return {"channel": "github_issue", "success": False, "error": "no_github_token"}
    headers = github_headers()
    title = f"SOCIAL FEED: factory outreach cycle {cycle_id}"
    body = (
        f"## Autonomous social post — cycle {cycle_id}\n\n"
        f"**Time:** {_now()}\n\n"
        f"{text}\n\n"
        f"---\n"
        f"_Posted by tools.autonomous_outreach without human click._\n"
    )
    # Prefer updating a sticky issue number if configured, else create.
    sticky = int(os.getenv("GITHUB_SOCIAL_ISSUE", "0") or 0)
    try:
        if sticky > 0:
            r = httpx.post(
                f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{sticky}/comments",
                headers=headers,
                json={"body": body},
                timeout=30.0,
            )
            if r.status_code in {200, 201}:
                return {
                    "channel": "github_issue_comment",
                    "success": True,
                    "issue": sticky,
                    "html_url": (r.json() or {}).get("html_url"),
                    "status_code": r.status_code,
                }
            # fall through to create if sticky comment fails (e.g. 403 cap)
        r = httpx.post(
            f"https://api.github.com/repos/{OWNER}/{REPO}/issues",
            headers=headers,
            json={
                "title": title,
                "body": body,
                "labels": ["revenue", "documentation"],
            },
            timeout=30.0,
        )
        ok = r.status_code in {200, 201}
        data = r.json() if r.content else {}
        return {
            "channel": "github_issue",
            "success": ok,
            "status_code": r.status_code,
            "html_url": data.get("html_url"),
            "number": data.get("number"),
            "error": None if ok else (data.get("message") or r.text[:200]),
        }
    except httpx.HTTPError as exc:
        return {"channel": "github_issue", "success": False, "error": str(exc)}


def publish_github_discussion(cycle_id: int, text: str) -> Dict[str, Any]:
    """Create a GitHub Discussion when discussions are enabled."""
    token = github_token()
    if not token:
        return {"channel": "github_discussion", "success": False, "error": "no_github_token"}
    headers = {
        **github_headers(),
        "Accept": "application/vnd.github+json",
    }
    # Resolve repository + first discussion category via GraphQL
    query = """
    query($owner:String!, $name:String!) {
      repository(owner:$owner, name:$name) {
        id
        discussionCategories(first: 10) {
          nodes { id name }
        }
      }
    }
    """
    try:
        gr = httpx.post(
            "https://api.github.com/graphql",
            headers=headers,
            json={"query": query, "variables": {"owner": OWNER, "name": REPO}},
            timeout=30.0,
        )
        if gr.status_code != 200:
            return {
                "channel": "github_discussion",
                "success": False,
                "status_code": gr.status_code,
                "error": gr.text[:200],
            }
        data = (gr.json() or {}).get("data", {}).get("repository") or {}
        repo_id = data.get("id")
        cats = (data.get("discussionCategories") or {}).get("nodes") or []
        if not repo_id or not cats:
            return {
                "channel": "github_discussion",
                "success": False,
                "error": "no_discussion_categories",
            }
        # Prefer General / Announcements
        cat_id = cats[0]["id"]
        for c in cats:
            if str(c.get("name", "")).lower() in {"general", "announcements", "show and tell"}:
                cat_id = c["id"]
                break
        mutation = """
        mutation($repo:ID!, $cat:ID!, $title:String!, $body:String!) {
          createDiscussion(input:{repositoryId:$repo, categoryId:$cat, title:$title, body:$body}) {
            discussion { url number }
          }
        }
        """
        title = f"Factory outreach — cycle {cycle_id}"
        mr = httpx.post(
            "https://api.github.com/graphql",
            headers=headers,
            json={
                "query": mutation,
                "variables": {
                    "repo": repo_id,
                    "cat": cat_id,
                    "title": title,
                    "body": text + f"\n\n_Autonomous post {_now()}_",
                },
            },
            timeout=30.0,
        )
        payload = mr.json() if mr.content else {}
        disc = ((payload.get("data") or {}).get("createDiscussion") or {}).get("discussion") or {}
        ok = bool(disc.get("url")) and not payload.get("errors")
        return {
            "channel": "github_discussion",
            "success": ok,
            "status_code": mr.status_code,
            "html_url": disc.get("url"),
            "number": disc.get("number"),
            "error": payload.get("errors"),
        }
    except httpx.HTTPError as exc:
        return {"channel": "github_discussion", "success": False, "error": str(exc)}


def publish_discord_webhook(text: str) -> Dict[str, Any]:
    url = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not url:
        return {"channel": "discord", "success": False, "skipped": True, "reason": "DISCORD_WEBHOOK missing"}
    try:
        r = httpx.post(url, json={"content": text[:1900]}, timeout=30.0)
        return {
            "channel": "discord",
            "success": r.status_code in {200, 204},
            "status_code": r.status_code,
        }
    except httpx.HTTPError as exc:
        return {"channel": "discord", "success": False, "error": str(exc)}


def publish_telegram(text: str) -> Dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return {
            "channel": "telegram",
            "success": False,
            "skipped": True,
            "reason": "TELEGRAM_BOT_TOKEN/CHAT_ID missing",
        }
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": False},
            timeout=30.0,
        )
        data = r.json() if r.content else {}
        return {
            "channel": "telegram",
            "success": bool(data.get("ok")),
            "status_code": r.status_code,
            "error": None if data.get("ok") else data,
        }
    except httpx.HTTPError as exc:
        return {"channel": "telegram", "success": False, "error": str(exc)}


def publish_x(text: str) -> Dict[str, Any]:
    """Post to factory X account (@X_HANDLE) when OAuth1 user tokens are present."""
    try:
        from tools.x_publisher import publish_x_tweet

        return publish_x_tweet(text)
    except Exception as exc:
        return {"channel": "x", "success": False, "error": str(exc)}


def publish_bluesky(text: str) -> Dict[str, Any]:
    handle = os.getenv("BLUESKY_HANDLE", "").strip()
    password = os.getenv("BLUESKY_APP_PASSWORD", "").strip()
    if not handle or not password:
        return {
            "channel": "bluesky",
            "success": False,
            "skipped": True,
            "reason": "BLUESKY_HANDLE/APP_PASSWORD missing",
        }
    try:
        session = httpx.post(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            json={"identifier": handle, "password": password},
            timeout=30.0,
        )
        if session.status_code != 200:
            return {
                "channel": "bluesky",
                "success": False,
                "status_code": session.status_code,
                "error": session.text[:200],
            }
        sess = session.json()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        record = {
            "$type": "app.bsky.feed.post",
            "text": text[:300],
            "createdAt": now,
        }
        r = httpx.post(
            "https://bsky.social/xrpc/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {sess['accessJwt']}"},
            json={
                "repo": sess["did"],
                "collection": "app.bsky.feed.post",
                "record": record,
            },
            timeout=30.0,
        )
        ok = r.status_code in {200, 201}
        return {
            "channel": "bluesky",
            "success": ok,
            "status_code": r.status_code,
            "uri": (r.json() or {}).get("uri") if ok else None,
            "error": None if ok else r.text[:200],
        }
    except httpx.HTTPError as exc:
        return {"channel": "bluesky", "success": False, "error": str(exc)}


def write_social_feed_artifacts(cycle_id: int, text: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Local + published social wall + RSS (no credentials)."""
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    feed_path = PUBLISHED / "social-feed.json"
    items: List[Dict[str, Any]] = []
    if feed_path.exists():
        try:
            items = list((json.loads(feed_path.read_text(encoding="utf-8")) or {}).get("items") or [])
        except (json.JSONDecodeError, OSError):
            items = []
    entry = {
        "cycle_id": cycle_id,
        "timestamp": _now(),
        "text": text,
        "channels": [
            {
                "channel": r.get("channel"),
                "success": r.get("success"),
                "url": r.get("html_url") or r.get("url") or r.get("uri"),
            }
            for r in results
        ],
    }
    items.insert(0, entry)
    items = items[:100]
    payload = {
        "schema": "rsi_eaf_social_feed_v1",
        "updated_at": _now(),
        "items": items,
        "subscribe": {
            "rss": f"{BASE}/feed.xml",
            "ntfy": f"{NTFY_BASE}/{NTFY_TOPIC}",
            "json": f"{BASE}/social-feed.json",
        },
    }
    feed_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # RSS
    rss_items = []
    for it in items[:20]:
        title = f"RSI-EAF cycle {it.get('cycle_id')}"
        desc = (it.get("text") or "").replace("&", "&amp;").replace("<", "&lt;")
        rss_items.append(
            f"<item><title>{title}</title><description>{desc}</description>"
            f"<pubDate>{it.get('timestamp')}</pubDate>"
            f"<link>{BASE}/pay.html</link></item>"
        )
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        "<title>RSI-EAF Factory Outreach</title>"
        f"<link>{BASE}/pay.html</link>"
        "<description>Autonomous factory social/outreach feed</description>"
        + "".join(rss_items)
        + "</channel></rss>\n"
    )
    (PUBLISHED / "feed.xml").write_text(rss, encoding="utf-8")
    return {"channel": "social_feed_artifacts", "success": True, "items": len(items)}


def write_gist_fallback(cycle_id: int, text: str) -> Dict[str, Any]:
    """When gist scope missing, mirror outreach to docs/ on GitHub (works today)."""
    try:
        from tools.github_distribution import push_file_to_github

        content = (
            f"# Autonomous outreach — cycle {cycle_id}\n\n"
            f"Updated: {_now()}\n\n"
            f"{text}\n"
        )
        path = "docs/LATEST_OUTREACH.md"
        Path("docs").mkdir(exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        r = push_file_to_github(path, content, f"outreach: autonomous post cycle {cycle_id}")
        return {
            "channel": "github_docs_fallback",
            "success": bool(r.get("success")),
            "path": path,
            "detail": r,
        }
    except Exception as exc:
        return {"channel": "github_docs_fallback", "success": False, "error": str(exc)}


def inventory_human_gates() -> Dict[str, Any]:
    """Enumerate formerly human-gated actions and current factory power."""
    gates = [
        {
            "id": "social_share_clicks",
            "was_human": "Click free-ads.html share intents",
            "factory_power": "ntfy + github issue/discussion + optional Discord/Telegram/Bluesky",
            "autonomous": True,
        },
        {
            "id": "github_gist",
            "was_human": "Create public gist (token lacked gist scope)",
            "factory_power": "docs/LATEST_OUTREACH.md push fallback",
            "autonomous": True,
            "optional_upgrade": "GITHUB_TOKEN with gist scope",
        },
        {
            "id": "external_repo_issues",
            "was_human": "File issues on awesome-x402 / t54",
            "factory_power": "blocked by token fine-grained permissions; inventory + draft in social-drafts",
            "autonomous": False,
            "blocker": "token_scope_external_repos",
        },
        {
            "id": "x_twitter",
            "was_human": "Manual tweets as factory account",
            "factory_power": "tools.x_publisher posts as @PM27319682 when OAuth1 user tokens set",
            "autonomous": "conditional",
            "handle": "PM27319682",
            "need": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"],
        },
        {
            "id": "discord_telegram_bluesky",
            "was_human": "Manual social logins",
            "factory_power": "posts when DISCORD_WEBHOOK / TELEGRAM_* / BLUESKY_* set",
            "autonomous": "conditional",
        },
        {
            "id": "xrpl_ai_listing",
            "was_human": "Manual hub form",
            "factory_power": "tools.xrpl_ai_hub_register",
            "autonomous": True,
        },
        {
            "id": "vercel_publish",
            "was_human": "CLI login / full tree deploys",
            "factory_power": "surgical API deploy scripts",
            "autonomous": True,
        },
        {
            "id": "external_organic_payer",
            "was_human": "Stranger wallet tip",
            "factory_power": "cannot forge; factory maximizes discovery + ntfy/github demand gen",
            "autonomous": False,
            "note": "definitionally external",
        },
        {
            "id": "test_revenue_pipeline",
            "was_human": "Manual send_test_revenue",
            "factory_power": "scripts/send_test_revenue.py + TEST_SUPPORTER_SEED",
            "autonomous": True,
        },
    ]
    return {
        "schema": "rsi_eaf_human_gates_inventory_v1",
        "updated_at": _now(),
        "gates": gates,
        "env_optional": {
            "DISCORD_WEBHOOK": "Discord channel posts",
            "TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID": "Telegram channel posts",
            "BLUESKY_HANDLE + BLUESKY_APP_PASSWORD": "Bluesky posts",
            "NTFY_TOPIC": f"defaults to {NTFY_TOPIC}",
            "GITHUB_SOCIAL_ISSUE": "sticky issue number for comments",
        },
    }


def run_autonomous_outreach(
    cycle_id: int,
    *,
    force: bool = False,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute all autonomous outreach channels for a cycle."""
    if os.getenv("AUTONOMOUS_OUTREACH_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return {"success": False, "skipped": True, "reason": "disabled"}

    state = _load_state()
    last = (state.get("last_posts") or {}).get(str(cycle_id))
    if last and not force:
        return {"success": True, "skipped": True, "reason": "already_posted_this_cycle", "last": last}

    bundle = _share_bundle(cycle_id)
    text = message or bundle["long"]
    results: List[Dict[str, Any]] = []

    results.append(publish_ntfy(cycle_id, bundle["short"], title=f"RSI-EAF cycle {cycle_id} - pay live"))
    results.append(publish_x(bundle["short"]))
    results.append(publish_github_social_issue(cycle_id, text))
    results.append(publish_github_discussion(cycle_id, text))
    results.append(publish_discord_webhook(bundle["short"]))
    results.append(publish_telegram(bundle["short"]))
    results.append(publish_bluesky(bundle["short"]))
    results.append(write_gist_fallback(cycle_id, text))
    results.append(write_social_feed_artifacts(cycle_id, text, results))

    # Optional surgical publish of feed artifacts
    deploy_meta: Dict[str, Any] = {"skipped": True}
    if os.getenv("AUTONOMOUS_OUTREACH_DEPLOY", "true").lower() in {"1", "true", "yes"}:
        try:
            deploy_meta = _deploy_feed_artifacts()
        except Exception as exc:
            deploy_meta = {"success": False, "error": str(exc)}

    free_ads_meta: Dict[str, Any] = {}
    try:
        free_ads_meta = _ensure_free_ads_local(cycle_id, bundle)
    except Exception as exc:
        free_ads_meta = {"error": str(exc)}

    inventory = inventory_human_gates()
    inv_path = Path("observability/human_gates_inventory.json")
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inv_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    (PUBLISHED / "human-gates.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    successes = [r for r in results if r.get("success")]
    record = {
        "timestamp": _now(),
        "cycle_id": cycle_id,
        "success": len(successes) > 0,
        "success_count": len(successes),
        "channels": results,
        "deploy": deploy_meta,
        "free_ads": free_ads_meta,
        "bundle": bundle,
    }
    _append_log(record)
    state.setdefault("last_posts", {})[str(cycle_id)] = {
        "at": _now(),
        "success_count": len(successes),
    }
    _save_state(state)

    # Update social_accounts status for transparency
    _update_social_accounts_status(results)

    return record


def _ensure_free_ads_local(cycle_id: int, bundle: Dict[str, str]) -> Dict[str, Any]:
    """Keep free-ads.json current so factory surfaces stay share-ready."""
    import urllib.parse

    pay = bundle["pay"]
    short = bundle["short"]
    long = bundle["long"]
    payload = {
        "schema": "rsi_eaf_free_ads_v1",
        "cycle_id": cycle_id,
        "updated_at": _now(),
        "autonomous": True,
        "primary_cta": pay,
        "share_text": long,
        "free_share_intents": {
            "x_twitter": f"https://twitter.com/intent/tweet?text={urllib.parse.quote(short)}&url={urllib.parse.quote(pay)}",
            "reddit_submit": (
                "https://www.reddit.com/submit?url="
                + urllib.parse.quote(pay)
                + "&title="
                + urllib.parse.quote("Live XRPL testnet x402 factory — agents pay Tag 1")
            ),
            "hn_submit": (
                "https://news.ycombinator.com/submitlink?u="
                + urllib.parse.quote(pay)
                + "&t="
                + urllib.parse.quote("Show HN: Autonomous XRPL factory with live x402 (testnet)")
            ),
            "telegram": "https://t.me/share/url?url="
            + urllib.parse.quote(pay)
            + "&text="
            + urllib.parse.quote(short),
            "bluesky": "https://bsky.app/intent/compose?text=" + urllib.parse.quote(long),
        },
        "factory_autonomous_channels": {
            "ntfy": f"{NTFY_BASE}/{NTFY_TOPIC}",
            "rss": f"{BASE}/feed.xml",
            "social_feed": f"{BASE}/social-feed.json",
        },
    }
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    (PUBLISHED / "free-ads.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"success": True, "path": "published/free-ads.json"}


def _deploy_feed_artifacts() -> Dict[str, Any]:
    """
    Surgical deploy of outreach artifacts.

    IMPORTANT: Vercel file deploys replace the production file set entirely.
    Always co-ship CRITICAL_RELS (pay + doctrine + x402) so outreach never
    wipes icp/social-policy and recreates conversion_doctrine_partial.
    """
    token = os.getenv("VERCEL_TOKEN")
    if not token:
        return {"success": False, "skipped": True, "reason": "no_vercel_token"}
    # Ensure doctrine/pay exist locally before upload
    try:
        from tools.conversion_surfaces import ensure_doctrine_artifacts, ensure_local_pay_html, CRITICAL_RELS

        ensure_local_pay_html()
        ensure_doctrine_artifacts()
        critical = list(CRITICAL_RELS)
    except Exception:
        critical = [
            "pay.html",
            "agent-pay.json",
            "icp.json",
            "social-policy.json",
            "social-learning.json",
            "index.html",
            "vercel.json",
            ".well-known/x402.json",
            ".well-known/agent-pay.json",
            "tip-manifest.json",
            "network-status.json",
            "treasury-map.json",
            "blockers.json",
            "link-health.json",
            "free-sample.json",
            "free-ads.html",
        ]
    project = os.getenv("FACTORY_VERCEL_PROJECT_ID", "prj_kMNf4hUsd2dZjhEArOeqVrsWniDe")
    team = os.getenv("FACTORY_VERCEL_TEAM_ID", "team_TaQi1jIfAjwA0mYpRla493rW")
    headers = {"Authorization": f"Bearer {token}"}
    rels = [
        "social-feed.json",
        "feed.xml",
        "free-ads.json",
        "human-gates.json",
        "pay.html",
        "agent-pay.json",
        "llms.txt",
        "agents.txt",
        *critical,
    ]
    # de-dupe preserve order
    seen = set()
    ordered: list[str] = []
    for rel in rels:
        if rel not in seen:
            seen.add(rel)
            ordered.append(rel)
    meta = []
    for rel in ordered:
        path = PUBLISHED / rel
        if not path.exists():
            continue
        data = path.read_bytes()
        digest = __import__("hashlib").sha1(data).hexdigest()
        up = httpx.post(
            f"https://api.vercel.com/v2/files?size={len(data)}",
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "x-vercel-digest": digest,
            },
            params={"teamId": team},
            content=data,
            timeout=90,
        )
        # 409 = already on CDN for digest — still usable
        if up.status_code not in {200, 201, 409}:
            return {
                "success": False,
                "error": f"upload_failed:{rel}",
                "status_code": up.status_code,
                "body": up.text[:200],
            }
        meta.append({"file": rel, "sha": digest, "size": len(data)})
    if not meta:
        return {"success": False, "skipped": True, "reason": "no_files"}
    r = httpx.post(
        "https://api.vercel.com/v13/deployments",
        headers={**headers, "Content-Type": "application/json"},
        params={"teamId": team, "forceNew": "1"},
        json={
            "name": "published",
            "project": project,
            "target": "production",
            "files": meta,
            "projectSettings": {"framework": None},
            "meta": {"deployMethod": "autonomous_outreach"},
        },
        timeout=180,
    )
    ok = r.status_code in {200, 201}
    dep = r.json() if r.content else {}
    did = dep.get("id")
    if ok and did:
        for _ in range(25):
            st = (
                httpx.get(
                    f"https://api.vercel.com/v13/deployments/{did}",
                    headers=headers,
                    params={"teamId": team},
                    timeout=30,
                )
                .json()
                .get("readyState")
            )
            if st in {"READY", "ERROR", "CANCELED"}:
                return {"success": st == "READY", "readyState": st, "deployment_id": did}
            time.sleep(2)
    return {"success": ok, "status_code": r.status_code, "deployment_id": did}


def _update_social_accounts_status(results: List[Dict[str, Any]]) -> None:
    accounts = {
        "schema": "rsi_eaf_social_accounts_v1",
        "updated_at": _now(),
        "factory_handle": "RSI_EAF_Factory",
        "accounts": {
            "ntfy": {
                "platform": "ntfy",
                "topic": NTFY_TOPIC,
                "url": f"{NTFY_BASE}/{NTFY_TOPIC}",
                "enabled": True,
                "status": "autonomous",
            },
            "github": {
                "platform": "github",
                "enabled": True,
                "status": "autonomous",
            },
            "x": {
                "platform": "x",
                "handle": os.getenv("X_HANDLE", "PM27319682").lstrip("@"),
                "profile_url": f"https://x.com/{os.getenv('X_HANDLE', 'PM27319682').lstrip('@')}",
                "enabled": bool(
                    os.getenv("X_API_KEY")
                    and os.getenv("X_API_SECRET")
                    and os.getenv("X_ACCESS_TOKEN")
                    and (os.getenv("X_ACCESS_TOKEN_SECRET") or os.getenv("X_ACCESS_SECRET"))
                ),
                "status": "autonomous"
                if (
                    os.getenv("X_API_KEY")
                    and os.getenv("X_API_SECRET")
                    and os.getenv("X_ACCESS_TOKEN")
                    and (os.getenv("X_ACCESS_TOKEN_SECRET") or os.getenv("X_ACCESS_SECRET"))
                )
                else "awaiting_oauth1_user_tokens",
            },
            "discord": {
                "platform": "discord",
                "enabled": bool(os.getenv("DISCORD_WEBHOOK")),
                "status": "autonomous" if os.getenv("DISCORD_WEBHOOK") else "awaiting_credentials",
            },
            "telegram": {
                "platform": "telegram",
                "enabled": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
                "status": "autonomous"
                if (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))
                else "awaiting_credentials",
            },
            "bluesky": {
                "platform": "bluesky",
                "enabled": bool(os.getenv("BLUESKY_HANDLE") and os.getenv("BLUESKY_APP_PASSWORD")),
                "status": "autonomous"
                if (os.getenv("BLUESKY_HANDLE") and os.getenv("BLUESKY_APP_PASSWORD"))
                else "awaiting_credentials",
            },
        },
        "last_run_channels": [
            {"channel": r.get("channel"), "success": r.get("success"), "skipped": r.get("skipped")}
            for r in results
        ],
        "credential_env": {
            "discord": ["DISCORD_WEBHOOK"],
            "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
            "bluesky": ["BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"],
            "x": ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"],
            "ntfy": ["NTFY_TOPIC", "NTFY_BASE"],
        },
    }
    SOCIAL_ACCOUNTS.parent.mkdir(parents=True, exist_ok=True)
    SOCIAL_ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    from factory_core.state import FactoryState

    cid = int(FactoryState().snapshot().get("current_cycle") or 0)
    out = run_autonomous_outreach(cid or 750, force=True)
    print(json.dumps({k: out.get(k) for k in ("success", "success_count", "channels", "deploy")}, indent=2, default=str)[:4000])
