"""
Advanced factory X operator — full account control for @X_HANDLE.

Capabilities:
  - Read: me, timeline, mentions, tweet lookup, conversation search (if credits)
  - Write: tweet, reply, like, retweet, quote
  - Watch: poll interactions, classify intent, auto-respond on revenue critical path
  - Scout: search high-intent XRPL/x402/agent-payment threads and engage
  - Analyze: engagement funnel → critical path recommendations (continuous)

State: observability/x_agent_state.json
Log:   observability/x_agent.jsonl
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests
from requests_oauthlib import OAuth1

from tools.x_publisher import (
    _oauth1,
    factory_x_handle,
    publish_x_tweet,
    sanitize_tweet_text,
    truncate_tweet,
    x_posting_ready,
)

STATE_FILE = Path(os.getenv("X_AGENT_STATE", "observability/x_agent_state.json"))
LOG_FILE = Path(os.getenv("X_AGENT_LOG", "observability/x_agent.jsonl"))
ANALYSIS_FILE = Path(os.getenv("X_AGENT_ANALYSIS", "observability/x_agent_analysis_latest.json"))
TX_WATCH_FILE = Path(os.getenv("X_AGENT_TX_WATCH", "observability/x_agent_tx_watch.jsonl"))
PUBLISHED = Path(os.getenv("PUBLISHED_DIR", "published"))

BASE = os.getenv("FACTORY_PUBLIC_BASE_URL", "https://published-zeta.vercel.app").rstrip("/")


def _pay_base() -> str:
    """Prefer jsDelivr mainnet pay pack when revenue network is mainnet (Vercel free quota lag)."""
    try:
        from factory_core.xrpl_network import revenue_network

        if revenue_network() == "mainnet":
            return os.getenv(
                "MAINNET_PAY_CDN",
                "https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/public_pay",
            ).rstrip("/")
    except Exception:
        pass
    return BASE


PAY = f"{_pay_base()}/pay.html"
AGENT_PAY = f"{_pay_base()}/agent-pay.json"
FREE_SAMPLE = f"{BASE}/free-sample.html"
HUB = "https://xrpl-ai.org/address/rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN"
BOUNTY = "https://github.com/theCeramist/rsi-eaf/issues/178"

from factory_core.target_icp import (  # noqa: E402
    HUMAN_PRIMARY_HANDLE,
    SCOUT_QUERIES_EXCLUSIVE,
    broadcast_variants,
    craft_exclusive_reply,
    exclusive_next_actions,
    icp_manifest,
    sophistication_score,
)

# XRPL tx hash (64 hex) — capture from mentions into treasury watch
TX_HASH_RE = re.compile(r"\b([A-Fa-f0-9]{64})\b")
# Destination tag mentions
TAG_RE = re.compile(r"\b(?:tag|destination\s*tag)\s*[#:]?\s*(\d{1,10})\b", re.I)

# Intent keywords — exclusive posture (no mass-market freeload)
INTENT_PATTERNS = {
    "pay_intent": re.compile(
        r"\b(pay|tip|buy|purchase|unlock|how (do|to) pay|send xrp|destination tag|invoice|settle)\b",
        re.I,
    ),
    "agent_builder": re.compile(
        r"\b(x402|http\s*402|autonomous\s+agent|agentic|mcp|settlement|machine\s+payment|agent\s+wallet)\b",
        re.I,
    ),
    "xrpl_native": re.compile(r"\b(xrpl|xrp ledger|ripple|amm|trustline|hooks)\b", re.I),
    "human_icp": re.compile(
        rf"\b(crypto|overthink|reply\s*guy|skeptic|vapor|grift|prove|verify|receipts)|@{HUMAN_PRIMARY_HANDLE}\b",
        re.I,
    ),
    "question": re.compile(r"\?|how |what |where |when |why |can i |does it ", re.I),
    "support": re.compile(r"\b(broken|error|fail|help|issue|bug|not work)\b", re.I),
    "positive": re.compile(r"\b(based|real|solid|interesting|ship it|receipts)\b", re.I),
    "spam": re.compile(
        r"\b(follow me|airdrop|dm for|giveaway|pump|100x|guaranteed|whitelist|free mint|gm+)\b",
        re.I,
    ),
}

# Exclusive scout only (most sophisticated agents + human ICP adjacency)
SCOUT_QUERIES = list(SCOUT_QUERIES_EXCLUSIVE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth() -> Optional[OAuth1]:
    return _oauth1()


def _log(record: Dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "schema": "rsi_eaf_x_agent_state_v1",
        "user_id": os.getenv("X_USER_ID", "1545221323902689280"),
        "seen_mention_ids": [],
        "seen_reply_ids": [],
        "liked_ids": [],
        "retweeted_ids": [],
        "replied_ids": [],
        "scouted_ids": [],
        "last_broadcast_at": None,
        "last_scout_at": None,
        "scout_query_idx": 0,
        "metrics_history": [],
        "critical_path_history": [],
        "tx_hashes_seen": [],
    }


def _save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now()
    # cap lists
    for k in (
        "seen_mention_ids",
        "seen_reply_ids",
        "liked_ids",
        "retweeted_ids",
        "replied_ids",
        "scouted_ids",
        "tx_hashes_seen",
    ):
        state[k] = list(state.get(k) or [])[-500:]
    state["metrics_history"] = list(state.get("metrics_history") or [])[-80:]
    state["critical_path_history"] = list(state.get("critical_path_history") or [])[-40:]
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _log_tx_watch(record: Dict[str, Any]) -> None:
    TX_WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TX_WATCH_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def extract_payment_signals(text: str) -> Dict[str, Any]:
    hashes = TX_HASH_RE.findall(text or "")
    tags = [int(t) for t in TAG_RE.findall(text or "")]
    return {"tx_hashes": hashes, "tags": tags}


def _req(
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    auth = _auth()
    if not auth:
        return {"success": False, "error": "no_oauth1"}
    try:
        r = requests.request(
            method,
            url,
            auth=auth,
            params=params,
            json=json_body,
            data=data,
            timeout=45,
        )
        try:
            body = r.json() if r.content else {}
        except Exception:
            body = {"raw": r.text[:500]}
        return {
            "success": 200 <= r.status_code < 300,
            "status_code": r.status_code,
            "data": body,
            "headers": {
                "x-rate-limit-remaining": r.headers.get("x-rate-limit-remaining"),
                "x-rate-limit-reset": r.headers.get("x-rate-limit-reset"),
            },
            "error": None
            if 200 <= r.status_code < 300
            else (body.get("detail") or body.get("title") or body.get("errors") or body),
        }
    except requests.RequestException as exc:
        return {"success": False, "error": str(exc)}


# ---------- identity ----------


def ensure_user_id(state: Optional[Dict[str, Any]] = None) -> str:
    state = state or _load_state()
    if state.get("user_id"):
        return str(state["user_id"])
    r = _req("GET", "https://api.twitter.com/2/users/me", params={"user.fields": "id,username,public_metrics"})
    if r.get("success"):
        uid = str((r["data"].get("data") or {}).get("id") or "")
        if uid:
            state["user_id"] = uid
            state["username"] = (r["data"].get("data") or {}).get("username")
            _save_state(state)
            return uid
    return os.getenv("X_USER_ID", "1545221323902689280")


def get_me() -> Dict[str, Any]:
    return _req(
        "GET",
        "https://api.twitter.com/2/users/me",
        params={"user.fields": "id,username,name,public_metrics,description,created_at"},
    )


# ---------- read ----------


def get_mentions(user_id: str, *, max_results: int = 25, since_id: Optional[str] = None) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "max_results": max(5, min(100, max_results)),
        "tweet.fields": "public_metrics,created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets,lang",
        "expansions": "author_id",
        "user.fields": "username,name,public_metrics",
    }
    if since_id:
        params["since_id"] = since_id
    return _req("GET", f"https://api.twitter.com/2/users/{user_id}/mentions", params=params)


def get_timeline(user_id: str, *, max_results: int = 20) -> Dict[str, Any]:
    params = {
        "max_results": max(5, min(100, max_results)),
        "tweet.fields": "public_metrics,created_at,conversation_id,in_reply_to_user_id,referenced_tweets",
        "exclude": "retweets,replies",
    }
    return _req("GET", f"https://api.twitter.com/2/users/{user_id}/tweets", params=params)


def get_tweet(tweet_id: str) -> Dict[str, Any]:
    return _req(
        "GET",
        f"https://api.twitter.com/2/tweets/{tweet_id}",
        params={
            "tweet.fields": "public_metrics,created_at,author_id,conversation_id,in_reply_to_user_id,referenced_tweets",
            "expansions": "author_id",
            "user.fields": "username,public_metrics",
        },
    )


def search_recent(query: str, *, max_results: int = 10) -> Dict[str, Any]:
    """May fail on free tier (credits/search access)."""
    return _req(
        "GET",
        "https://api.twitter.com/2/tweets/search/recent",
        params={
            "query": query,
            "max_results": max(10, min(100, max_results)),
            "tweet.fields": "public_metrics,created_at,author_id,conversation_id,lang",
            "expansions": "author_id",
            "user.fields": "username,public_metrics",
        },
    )


def get_conversation(conversation_id: str, *, max_results: int = 20) -> Dict[str, Any]:
    return search_recent(f"conversation_id:{conversation_id}", max_results=max_results)


# ---------- write actions ----------


def like_tweet(user_id: str, tweet_id: str) -> Dict[str, Any]:
    return _req(
        "POST",
        f"https://api.twitter.com/2/users/{user_id}/likes",
        json_body={"tweet_id": str(tweet_id)},
    )


def retweet(user_id: str, tweet_id: str) -> Dict[str, Any]:
    return _req(
        "POST",
        f"https://api.twitter.com/2/users/{user_id}/retweets",
        json_body={"tweet_id": str(tweet_id)},
    )


def _policy_publish(text: str, *, reply_to: Optional[str] = None) -> Dict[str, Any]:
    """Publish with Receipts Social hard-mode + record for social learning."""
    body = text or ""
    meta: Dict[str, Any] = {}
    try:
        from factory_core.social_learning import enforce_pay_link_policy, record_outgoing_post_text

        enforced = enforce_pay_link_policy(body)
        body = enforced.get("text") or body
        meta = {
            "pay_stripped": enforced.get("stripped_pay_link"),
            "pay_budget": enforced.get("budget"),
        }
        result = publish_x_tweet(body, reply_to=reply_to) if reply_to else publish_x_tweet(body)
        if result.get("success"):
            record_outgoing_post_text(body)
        result["social_policy"] = meta
        return result
    except Exception:
        return publish_x_tweet(text, reply_to=reply_to) if reply_to else publish_x_tweet(text)


def reply(text: str, in_reply_to: str) -> Dict[str, Any]:
    return _policy_publish(text, reply_to=str(in_reply_to))


def quote_tweet(text: str, quote_tweet_id: str) -> Dict[str, Any]:
    """Quote via v2 (quote_tweet_id field)."""
    auth = _auth()
    if not auth:
        return {"success": False, "error": "no_oauth1"}
    body = {"text": truncate_tweet(text), "quote_tweet_id": str(quote_tweet_id)}
    try:
        r = requests.post("https://api.twitter.com/2/tweets", auth=auth, json=body, timeout=30)
        data = r.json() if r.content else {}
        tid = (data.get("data") or {}).get("id")
        handle = factory_x_handle()
        return {
            "success": r.status_code in {200, 201} and bool(tid),
            "status_code": r.status_code,
            "tweet_id": tid,
            "html_url": f"https://x.com/{handle}/status/{tid}" if tid else None,
            "error": None if tid else data,
        }
    except requests.RequestException as exc:
        return {"success": False, "error": str(exc)}


# ---------- intelligence ----------


def classify_text(text: str) -> Dict[str, Any]:
    labels = []
    for name, pat in INTENT_PATTERNS.items():
        if pat.search(text or ""):
            labels.append(name)
    sop = sophistication_score(text or "", context="general")
    for lab in sop.get("labels") or []:
        if lab not in labels:
            labels.append(lab)

    # score for revenue critical path — exclusive bar
    score = 0.0
    if "pay_intent" in labels:
        score += 1.0
    if "agent_builder" in labels or "sophisticated_agent" in labels:
        score += 0.85  # sophisticated agents only count heavily
    if "human_icp" in labels or "critical_voice" in labels or "human_archetype" in labels:
        score += 0.7  # @thatcrypto_guy-class
    if "xrpl_native" in labels:
        score += 0.35
    if "payment_competent" in labels:
        score += 0.5
    if "question" in labels:
        score += 0.2
    if "support" in labels:
        score += 0.35
    if "positive" in labels:
        score += 0.15
    if "spam" in labels or "low_tier" in labels:
        score -= 1.5
    if "mass_market" in labels or "casual_noise" in labels:
        score -= 0.5
    # payment signal bonus
    sig = extract_payment_signals(text or "")
    if sig["tx_hashes"]:
        score += 1.5
        labels.append("tx_hash_posted")
    if sig["tags"]:
        score += 0.5
        labels.append("tag_mentioned")
    # fold sophistication
    score += min(0.5, float(sop.get("score") or 0) * 0.3)
    return {
        "labels": labels,
        "revenue_score": round(score, 2),
        "signals": sig,
        "sophistication": sop,
        "admit_exclusive": bool(sop.get("admit")) or score >= 0.55,
    }


def craft_reply(text: str, classification: Dict[str, Any], *, context: str = "mention") -> Optional[str]:
    labels = set(classification.get("labels") or [])
    if "spam" in labels or "low_tier" in labels:
        return None
    # Exclusive filter: scout only if sophistication admits
    if context == "scout" and not classification.get("admit_exclusive", False):
        if classification.get("revenue_score", 0) < 0.85:
            return None
    if "support" in labels and "pay_intent" not in labels:
        return (
            f"Broken path? Receipts only — {PAY} / {AGENT_PAY}. "
            f"Open issue on github.com/theCeramist/rsi-eaf with the tweet link."
        )
    exclusive = craft_exclusive_reply(text, labels=labels, context=context)
    if exclusive:
        return exclusive
    # Last resort for direct mentions with substance — still exclusive tone
    if context == "mention" and len((text or "").strip()) > 30:
        return f"Exclusive rails. Crypto-critical humans + sophisticated agents: {PAY}"
    return None


def craft_scout_reply(text: str, classification: Dict[str, Any]) -> Optional[str]:
    """Outbound under other threads — only if exclusive bar clears."""
    return craft_reply(text, classification, context="scout")


def analyze_metrics(
    timeline: List[Dict[str, Any]],
    mentions: List[Dict[str, Any]],
    *,
    state: Optional[Dict[str, Any]] = None,
    scout_stats: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    total_imp = 0
    total_like = 0
    total_rt = 0
    total_reply = 0
    total_quote = 0
    top = []
    for t in timeline:
        m = t.get("public_metrics") or {}
        imp = int(m.get("impression_count") or 0)
        like = int(m.get("like_count") or 0)
        rt = int(m.get("retweet_count") or 0)
        rep = int(m.get("reply_count") or 0)
        q = int(m.get("quote_count") or 0)
        total_imp += imp
        total_like += like
        total_rt += rt
        total_reply += rep
        total_quote += q
        top.append(
            {
                "id": t.get("id"),
                "text": (t.get("text") or "")[:120],
                "impressions": imp,
                "likes": like,
                "retweets": rt,
                "replies": rep,
                "engagement": like + rt * 2 + rep * 3 + q * 2,
            }
        )
    top.sort(key=lambda x: (x["engagement"], x["impressions"]), reverse=True)

    mention_classes = [classify_text(m.get("text") or "") for m in mentions]
    high_intent = sum(1 for c in mention_classes if c["revenue_score"] >= 0.6)
    pay_intent = sum(1 for c in mention_classes if "pay_intent" in c["labels"])
    tx_posted = sum(1 for c in mention_classes if "tx_hash_posted" in c["labels"])

    # Trend vs last history snapshot
    history = list((state or {}).get("metrics_history") or [])
    prev = history[-1]["totals"] if history else {}
    imp_delta = total_imp - int(prev.get("impressions") or 0) if prev else total_imp
    eng_now = total_like + total_rt + total_reply + total_quote
    eng_prev = int(prev.get("likes") or 0) + int(prev.get("retweets") or 0) + int(
        prev.get("replies") or 0
    ) + int(prev.get("quotes") or 0)
    eng_delta = eng_now - eng_prev if prev else eng_now

    # Critical path synthesis — exclusive ICPs first
    if tx_posted > 0:
        path = "payment_signal_live"
        actions = exclusive_next_actions(path) + [
            "Verify posted tx hashes on mainnet explorer + dual treasury WS",
            "Escalate fulfillment if Tag 2 briefing paid",
        ]
    elif pay_intent > 0:
        path = "pay_intent_hot"
        actions = exclusive_next_actions(path) + [
            "Reply within 5 minutes — verified Tag path only",
            "Log tx hashes into treasury watch",
        ]
    elif high_intent > 0:
        path = "interest_without_pay"
        actions = exclusive_next_actions(path)
    elif total_imp < 80:
        path = "distribution_cold"
        actions = exclusive_next_actions(path)
    elif eng_now > 0 and total_imp > 100:
        path = "awareness_building"
        actions = exclusive_next_actions(path) + [
            "Double down on exclusive critical-voice posts only",
            f"Engage @{HUMAN_PRIMARY_HANDLE}-adjacent discourse, never mass bait",
        ]
    else:
        path = "bootstrap"
        actions = exclusive_next_actions(path) + [
            "Few posts, high bar — credits reserved for sophisticated signals",
            "Always convert to pay.html (no raw r-address for 7d)",
        ]

    path_hist = list((state or {}).get("critical_path_history") or [])
    path_hist.append({"at": _now(), "path": path, "imp": total_imp, "eng": eng_now})

    return {
        "schema": "rsi_eaf_x_critical_path_v1",
        "generated_at": _now(),
        "handle": factory_x_handle(),
        "totals": {
            "impressions": total_imp,
            "likes": total_like,
            "retweets": total_rt,
            "replies": total_reply,
            "quotes": total_quote,
            "timeline_n": len(timeline),
            "mentions_n": len(mentions),
            "high_intent_mentions": high_intent,
            "pay_intent_mentions": pay_intent,
            "tx_hash_mentions": tx_posted,
            "engagement": eng_now,
            "impressions_delta": imp_delta,
            "engagement_delta": eng_delta,
        },
        "top_tweets": top[:5],
        "critical_path": path,
        "next_actions": actions,
        "scout": scout_stats or {},
        "path_streak": _path_streak(path_hist, path),
        "icp": {
            "posture": "critical_exclusive",
            "human_primary": HUMAN_PRIMARY_HANDLE,
            "agent_tier": "sophisticated_only",
        },
        "conversion_urls": {
            "pay": PAY,
            "agent_pay": AGENT_PAY,
            "free_sample": FREE_SAMPLE,
            "hub": HUB,
            "bounty": BOUNTY,
        },
    }


def _path_streak(history: List[Dict[str, Any]], current: str) -> int:
    streak = 0
    for row in reversed(history):
        if row.get("path") == current:
            streak += 1
        else:
            break
    return streak


# ---------- engagement helpers ----------


def _engage_tweet(
    *,
    user_id: str,
    tweet: Dict[str, Any],
    users_map: Dict[str, Any],
    seen: Set[str],
    replied: Set[str],
    liked: Set[str],
    retweeted: Set[str],
    actions: List[Dict[str, Any]],
    counters: Dict[str, int],
    limits: Dict[str, int],
    context: str,
    allow_rt: bool = False,
) -> None:
    mid = str(tweet.get("id") or "")
    if not mid or mid in seen:
        return
    author = str(tweet.get("author_id") or "")
    if author == str(user_id):
        seen.add(mid)
        return

    text = tweet.get("text") or ""
    classification = classify_text(text)
    seen.add(mid)

    # Capture payment signals immediately (dedupe left to caller for state lists)
    sig = classification.get("signals") or {}
    for hx in sig.get("tx_hashes") or []:
        _log_tx_watch(
            {
                "at": _now(),
                "tweet_id": mid,
                "author": (users_map.get(author) or {}).get("username"),
                "tx_hash": hx,
                "tags": sig.get("tags") or [],
                "text": text[:280],
                "context": context,
            }
        )
        actions.append({"op": "tx_hash_capture", "id": mid, "tx_hash": hx})

    actions.append(
        {
            "op": f"classify_{context}",
            "id": mid,
            "score": classification["revenue_score"],
            "labels": classification["labels"],
            "author": (users_map.get(author) or {}).get("username"),
        }
    )

    # like — exclusive bar (higher for scout)
    like_floor = 0.45 if context == "mention" else 0.75
    if (
        counters["likes"] < limits["likes"]
        and mid not in liked
        and classification["revenue_score"] >= like_floor
        and "spam" not in classification["labels"]
        and "low_tier" not in classification["labels"]
    ):
        lr = like_tweet(user_id, mid)
        counters["likes"] += 1
        if lr.get("success"):
            liked.add(mid)
        actions.append({"op": "like", "id": mid, "ok": lr.get("success"), "status": lr.get("status_code")})

    # reply when score warrants — exclusive floors
    # Free/basic X tier often forbids reply unless mentioned/author — use quote for scout.
    reply_floor = 0.55 if context == "mention" else 0.9
    if (
        counters["replies"] < limits["replies"]
        and mid not in replied
        and classification["revenue_score"] >= reply_floor
        and "spam" not in classification["labels"]
    ):
        reply_text = (
            craft_reply(text, classification)
            if context in {"mention", "conversation"}
            else craft_scout_reply(text, classification)
        )
        if reply_text:
            if context == "scout":
                # Free/basic tier: reply AND quote both 403 unless mentioned/author.
                # Workarounds: like (above) + original @-callout posts (not in-thread).
                # Free tier: quote/reply into others' threads → 403. Default callout only.
                mode = os.getenv("X_AGENT_SCOUT_MODE", "callout").lower()  # callout|like_only|quote|reply
                if mode == "quote" and os.getenv("X_AGENT_FREE_TIER", "true").lower() in {
                    "1",
                    "true",
                    "yes",
                }:
                    mode = "callout"
                if mode == "like_only":
                    pass
                elif mode == "reply":
                    rr = reply(reply_text, mid)
                    counters["replies"] += 1
                    if rr.get("success"):
                        replied.add(mid)
                    actions.append(
                        {
                            "op": "reply",
                            "context": context,
                            "to": mid,
                            "ok": rr.get("success"),
                            "status": rr.get("status_code"),
                            "url": rr.get("html_url"),
                            "error": rr.get("error"),
                        }
                    )
                elif mode == "quote":
                    qt_text = craft_scout_reply(text, classification) or f"Exclusive rails: {PAY}"
                    qr = quote_tweet(qt_text, mid)
                    counters["replies"] += 1
                    if qr.get("success"):
                        replied.add(mid)
                    actions.append(
                        {
                            "op": "quote_scout",
                            "context": context,
                            "of": mid,
                            "ok": qr.get("success"),
                            "status": qr.get("status_code"),
                            "url": qr.get("html_url"),
                            "error": qr.get("error"),
                        }
                    )
                else:
                    # callout: SIGNAL format — useful add relative to their post (not exclusive spam)
                    uname = (users_map.get(author) or {}).get("username")
                    if uname and counters.get("callouts", 0) < int(os.getenv("X_AGENT_MAX_CALLOUTS_PER_TICK", "2")):
                        try:
                            from factory_core.social_policy import (
                                format_signal_callout,
                                useful_add_for_text,
                            )

                            callout = format_signal_callout(
                                uname,
                                (text or "")[:80],
                                useful_add_for_text(text or ""),
                            )
                        except Exception:
                            callout = (
                                f"@{uname} — receipts > volume. "
                                f"Doctrine {BASE}/social-policy.json · agents {AGENT_PAY}"
                            )
                        cr = _policy_publish(callout)
                        counters["callouts"] = counters.get("callouts", 0) + 1
                        counters["replies"] += 1
                        if cr.get("success"):
                            replied.add(mid)
                        actions.append(
                            {
                                "op": "callout",
                                "to_user": uname,
                                "of": mid,
                                "ok": cr.get("success"),
                                "status": cr.get("status_code"),
                                "url": cr.get("html_url"),
                                "error": cr.get("error"),
                                "social_policy": cr.get("social_policy"),
                            }
                        )
            else:
                rr = reply(reply_text, mid)
                counters["replies"] += 1
                if rr.get("success"):
                    replied.add(mid)
                # If reply blocked (not mentioned), fall back to quote once
                if not rr.get("success") and rr.get("status_code") == 403:
                    qr = quote_tweet(reply_text, mid)
                    actions.append(
                        {
                            "op": "reply_fallback_quote",
                            "to": mid,
                            "ok": qr.get("success"),
                            "status": qr.get("status_code"),
                            "url": qr.get("html_url"),
                        }
                    )
                    if qr.get("success"):
                        replied.add(mid)
                else:
                    actions.append(
                        {
                            "op": "reply",
                            "context": context,
                            "to": mid,
                            "ok": rr.get("success"),
                            "status": rr.get("status_code"),
                            "url": rr.get("html_url"),
                            "error": rr.get("error"),
                        }
                    )

    # strategic RT only for high-value external content (scout)
    if (
        allow_rt
        and counters.get("retweets", 0) < limits.get("retweets", 1)
        and mid not in retweeted
        and classification["revenue_score"] >= 0.9
        and "spam" not in classification["labels"]
        and os.getenv("X_AGENT_ALLOW_RETWEET", "true").lower() in {"1", "true", "yes"}
    ):
        rtr = retweet(user_id, mid)
        counters["retweets"] = counters.get("retweets", 0) + 1
        if rtr.get("success"):
            retweeted.add(mid)
        actions.append({"op": "retweet", "id": mid, "ok": rtr.get("success"), "status": rtr.get("status_code")})


def _run_outbound_scout(
    *,
    user_id: str,
    state: Dict[str, Any],
    actions: List[Dict[str, Any]],
    liked: Set[str],
    replied: Set[str],
    retweeted: Set[str],
    counters: Dict[str, int],
    limits: Dict[str, int],
) -> Dict[str, Any]:
    """Search high-intent external threads and engage sparingly."""
    if os.getenv("X_AGENT_SCOUT", "true").lower() not in {"1", "true", "yes"}:
        return {"skipped": True, "reason": "disabled"}

    scout_hours = float(os.getenv("X_AGENT_SCOUT_HOURS", "1"))
    last = state.get("last_scout_at")
    if last:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
            if age < scout_hours * 3600:
                return {"skipped": True, "reason": "cadence", "age_sec": int(age)}
        except ValueError:
            pass

    idx = int(state.get("scout_query_idx") or 0) % len(SCOUT_QUERIES)
    query = SCOUT_QUERIES[idx]
    state["scout_query_idx"] = idx + 1
    sr = search_recent(query, max_results=10)
    actions.append(
        {
            "op": "scout_search",
            "query_idx": idx,
            "ok": sr.get("success"),
            "status": sr.get("status_code"),
            "error": sr.get("error"),
        }
    )
    if not sr.get("success"):
        return {"skipped": False, "ok": False, "error": sr.get("error"), "query_idx": idx}

    tweets = list((sr.get("data") or {}).get("data") or [])
    users_map = {
        u.get("id"): u for u in ((sr.get("data") or {}).get("includes") or {}).get("users") or []
    }
    scouted: Set[str] = set(state.get("scouted_ids") or [])
    engaged = 0
    max_scout = int(os.getenv("X_AGENT_MAX_SCOUT_PER_TICK", "2"))

    # rank by revenue score
    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for t in tweets:
        c = classify_text(t.get("text") or "")
        if "spam" in c["labels"]:
            continue
        ranked.append((c["revenue_score"], t))
    ranked.sort(key=lambda x: x[0], reverse=True)

    for score, t in ranked:
        if engaged >= max_scout:
            break
        mid = str(t.get("id") or "")
        if not mid or mid in scouted:
            continue
        before_r = counters["replies"]
        before_l = counters["likes"]
        _engage_tweet(
            user_id=user_id,
            tweet=t,
            users_map=users_map,
            seen=scouted,
            replied=replied,
            liked=liked,
            retweeted=retweeted,
            actions=actions,
            counters=counters,
            limits=limits,
            context="scout",
            allow_rt=False,
        )
        if counters["replies"] > before_r or counters["likes"] > before_l:
            engaged += 1

    state["scouted_ids"] = list(scouted)
    state["last_scout_at"] = _now()
    return {"skipped": False, "ok": True, "query_idx": idx, "candidates": len(tweets), "engaged": engaged}


# ---------- main tick ----------


def run_x_agent_tick(*, force_broadcast: bool = False) -> Dict[str, Any]:
    """
    One full operator cycle:
      1) identity + metrics
      2) pull mentions + timeline
      3) classify / auto-reply / like / strategic RT
      4) conversation watch on own posts
      5) outbound high-intent scout
      6) optional broadcast CTA
      7) analyze critical path + persist
    """
    if not x_posting_ready():
        return {"success": False, "error": "x_oauth_not_ready"}

    state = _load_state()
    user_id = ensure_user_id(state)
    actions: List[Dict[str, Any]] = []
    tx_hashes_seen: Set[str] = set(state.get("tx_hashes_seen") or [])

    me = get_me()
    actions.append({"op": "get_me", "ok": me.get("success"), "status": me.get("status_code")})

    mentions_r = get_mentions(user_id, max_results=25, since_id=state.get("last_mention_id"))
    timeline_r = get_timeline(user_id, max_results=20)

    mentions = list((mentions_r.get("data") or {}).get("data") or []) if mentions_r.get("success") else []
    timeline = list((timeline_r.get("data") or {}).get("data") or []) if timeline_r.get("success") else []
    users_map = {
        u.get("id"): u
        for u in ((mentions_r.get("data") or {}).get("includes") or {}).get("users") or []
    }

    # Update last_mention_id
    if mentions:
        state["last_mention_id"] = str(mentions[0].get("id"))

    seen: Set[str] = set(state.get("seen_mention_ids") or [])
    replied: Set[str] = set(state.get("replied_ids") or [])
    liked: Set[str] = set(state.get("liked_ids") or [])
    retweeted: Set[str] = set(state.get("retweeted_ids") or [])

    max_replies = int(os.getenv("X_AGENT_MAX_REPLIES_PER_TICK", "5"))
    max_likes = int(os.getenv("X_AGENT_MAX_LIKES_PER_TICK", "8"))
    limits = {
        "replies": max_replies,
        "likes": max_likes,
        "retweets": int(os.getenv("X_AGENT_MAX_RETWEETS_PER_TICK", "1")),
    }
    counters = {"replies": 0, "likes": 0, "retweets": 0, "callouts": 0}

    # --- Mentions (inbound) ---
    for m in mentions:
        mid = str(m.get("id") or "")
        text = m.get("text") or ""
        # always capture payment signals even if already seen
        sig = extract_payment_signals(text)
        for hx in sig["tx_hashes"]:
            if hx not in tx_hashes_seen:
                tx_hashes_seen.add(hx)
                _log_tx_watch(
                    {
                        "at": _now(),
                        "tweet_id": mid,
                        "author": (users_map.get(str(m.get("author_id") or "")) or {}).get("username"),
                        "tx_hash": hx,
                        "tags": sig["tags"],
                        "text": text[:280],
                        "context": "mention",
                    }
                )
                actions.append({"op": "tx_hash_capture", "id": mid, "tx_hash": hx})

        _engage_tweet(
            user_id=user_id,
            tweet=m,
            users_map=users_map,
            seen=seen,
            replied=replied,
            liked=liked,
            retweeted=retweeted,
            actions=actions,
            counters=counters,
            limits=limits,
            context="mention",
            allow_rt=False,
        )

    # --- Conversation watch on own top posts ---
    if os.getenv("X_AGENT_FETCH_CONVERSATIONS", "true").lower() in {"1", "true", "yes"}:
        for t in timeline[:3]:
            cid = t.get("conversation_id") or t.get("id")
            if not cid:
                continue
            conv = get_conversation(str(cid), max_results=15)
            actions.append(
                {
                    "op": "conversation_poll",
                    "conversation_id": cid,
                    "ok": conv.get("success"),
                    "status": conv.get("status_code"),
                    "error": conv.get("error"),
                }
            )
            if not conv.get("success"):
                break  # don't burn credits if search locked
            conv_tweets = list((conv.get("data") or {}).get("data") or [])
            conv_users = {
                u.get("id"): u
                for u in ((conv.get("data") or {}).get("includes") or {}).get("users") or []
            }
            users_map.update(conv_users)
            for ct in conv_tweets:
                if str(ct.get("author_id") or "") == str(user_id):
                    continue
                _engage_tweet(
                    user_id=user_id,
                    tweet=ct,
                    users_map=users_map,
                    seen=seen,
                    replied=replied,
                    liked=liked,
                    retweeted=retweeted,
                    actions=actions,
                    counters=counters,
                    limits=limits,
                    context="conversation",
                    allow_rt=False,
                )

    # --- Outbound scout ---
    scout_stats = _run_outbound_scout(
        user_id=user_id,
        state=state,
        actions=actions,
        liked=liked,
        replied=replied,
        retweeted=retweeted,
        counters=counters,
        limits=limits,
    )

    # --- Periodic full ICP hunt (find exclusive targets + like/follow graph) ---
    hunt_meta: Dict[str, Any] = {"skipped": True}
    if os.getenv("X_AGENT_ICP_HUNT", "true").lower() in {"1", "true", "yes"}:
        hunt_hours = float(os.getenv("X_AGENT_ICP_HUNT_HOURS", "6"))
        if _hours_since(state.get("last_hunt_at")) >= hunt_hours:
            try:
                from agent_tools_icp_hunt_shim import run_icp_hunt  # optional
            except Exception:
                run_icp_hunt = None  # type: ignore
            if run_icp_hunt is None:
                # inline lightweight hunt via module path
                try:
                    import importlib.util

                    hunt_path = Path(__file__).resolve().parents[1] / "agent-tools" / "icp_hunt.py"
                    spec = importlib.util.spec_from_file_location("icp_hunt", hunt_path)
                    if spec and spec.loader:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        # run hunt_queries + engage only (no double print flood)
                        hits = mod.hunt_queries()
                        admit = [h for h in hits if h.get("admit")]
                        ha = mod.engage(
                            user_id,
                            admit,
                            max_likes=int(os.getenv("X_AGENT_HUNT_MAX_LIKES", "4")),
                            max_quotes=0,  # free tier blocks quote unless mentioned
                            state=state,
                        )
                        hunt_meta = {
                            "skipped": False,
                            "hits": len(hits),
                            "admit": len(admit),
                            "actions": len(ha),
                            "ok": sum(1 for a in ha if a.get("ok")),
                        }
                        actions.append({"op": "icp_hunt", **hunt_meta})
                        state["last_hunt_at"] = _now()
                except Exception as exc:
                    hunt_meta = {"skipped": False, "error": str(exc)[:200]}
                    actions.append({"op": "icp_hunt", **hunt_meta})
            else:
                hunt_meta = {"skipped": False, "delegated": True}

    # --- Broadcast cadence (default every 3h) ---
    broadcast_meta: Dict[str, Any] = {"skipped": True}
    interval_h = float(os.getenv("X_AGENT_BROADCAST_HOURS", "3"))
    last_b = state.get("last_broadcast_at")
    due = True
    if last_b and not force_broadcast:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_b.replace("Z", "+00:00"))).total_seconds()
            due = age >= interval_h * 3600
        except ValueError:
            due = True
    if due and os.getenv("X_AGENT_BROADCAST", "true").lower() in {"1", "true", "yes"}:
        variants = broadcast_variants()
        idx = int(time.time() // 3600) % len(variants)
        br = _policy_publish(variants[idx])
        broadcast_meta = {
            "skipped": False,
            "ok": br.get("success"),
            "url": br.get("html_url"),
            "status": br.get("status_code"),
            "error": br.get("error"),
            "social_policy": br.get("social_policy"),
        }
        if br.get("success"):
            state["last_broadcast_at"] = _now()
        actions.append({"op": "broadcast", **broadcast_meta})

    analysis = analyze_metrics(timeline, mentions, state=state, scout_stats=scout_stats)

    # Quote boost on cold path
    if (
        analysis.get("critical_path") == "distribution_cold"
        and os.getenv("X_AGENT_QUOTE_BOOST", "true").lower() in {"1", "true", "yes"}
        and _hours_since(state.get("last_quote_boost_at")) >= 12
        and analysis.get("top_tweets")
    ):
        best = analysis["top_tweets"][0]
        if best.get("id") and best.get("impressions", 0) >= 1:
            try:
                from factory_core.social_policy import format_learning_pulse

                qtext = format_learning_pulse()
            except Exception:
                qtext = f"Still Receipts Social: instrument panel > carnival. {BASE}/social-policy.json"
            qt = quote_tweet(qtext, str(best["id"]))
            actions.append(
                {
                    "op": "quote_boost",
                    "of": best["id"],
                    "ok": qt.get("success"),
                    "url": qt.get("html_url"),
                    "status": qt.get("status_code"),
                }
            )
            if qt.get("success"):
                state["last_quote_boost_at"] = _now()

    state["seen_mention_ids"] = list(seen)
    state["replied_ids"] = list(replied)
    state["liked_ids"] = list(liked)
    state["retweeted_ids"] = list(retweeted)
    state["tx_hashes_seen"] = list(tx_hashes_seen)
    state["metrics_history"] = list(state.get("metrics_history") or []) + [
        {"at": _now(), "totals": analysis["totals"], "path": analysis["critical_path"]}
    ]
    state["critical_path_history"] = list(state.get("critical_path_history") or []) + [
        {
            "at": _now(),
            "path": analysis["critical_path"],
            "imp": analysis["totals"].get("impressions"),
            "eng": analysis["totals"].get("engagement"),
        }
    ]
    me_data = (me.get("data") or {}).get("data") or {}
    state["public_metrics"] = me_data.get("public_metrics")
    state["username"] = me_data.get("username") or factory_x_handle()
    state["last_tick_at"] = _now()
    state["last_actions_summary"] = {
        "replies": counters["replies"],
        "likes": counters["likes"],
        "retweets": counters.get("retweets", 0),
        "critical_path": analysis["critical_path"],
    }
    _save_state(state)

    ANALYSIS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ANALYSIS_FILE.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    (PUBLISHED / "x-agent-analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    icp = icp_manifest()
    (PUBLISHED / "icp.json").write_text(json.dumps(icp, indent=2), encoding="utf-8")
    try:
        from factory_core.social_policy import write_policy_artifacts

        write_policy_artifacts()
    except Exception:
        pass
    (PUBLISHED / "x-agent-latest.json").write_text(
        json.dumps(
            {
                "updated_at": _now(),
                "handle": factory_x_handle(),
                "user_id": user_id,
                "critical_path": analysis["critical_path"],
                "next_actions": analysis["next_actions"],
                "totals": analysis["totals"],
                "path_streak": analysis.get("path_streak"),
                "scout": scout_stats,
                "icp": analysis.get("icp"),
                "human_primary": f"@{HUMAN_PRIMARY_HANDLE}",
                "agent_tier": "sophisticated_only",
                "posture": "critical_exclusive",
                "profile": f"https://x.com/{factory_x_handle()}",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = {
        "success": True,
        "timestamp": _now(),
        "user_id": user_id,
        "handle": factory_x_handle(),
        "mentions_seen": len(mentions),
        "timeline_n": len(timeline),
        "actions": actions,
        "action_counts": counters,
        "analysis": analysis,
        "broadcast": broadcast_meta,
        "scout": scout_stats,
        "me_ok": me.get("success"),
        "mentions_ok": mentions_r.get("success"),
        "timeline_ok": timeline_r.get("success"),
    }
    # Continuous self-improve: social interactions → structured learning → next cycles
    try:
        from factory_core.social_learning import on_x_agent_tick

        learning = on_x_agent_tick(result)
        result["social_learning"] = {
            "lesson_count": len(learning.get("lessons") or []),
            "directives": (learning.get("directives") or [])[:4],
            "top": [l.get("id") for l in (learning.get("lessons") or [])[:5]],
        }
        state["last_social_learning"] = result["social_learning"]
        _save_state(state)
    except Exception as exc:
        result["social_learning"] = {"error": str(exc)[:200]}

    _log(result)
    return result


def _hours_since(iso_ts: Optional[str]) -> float:
    if not iso_ts:
        return 9999.0
    try:
        return (
            datetime.now(timezone.utc) - datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        ).total_seconds() / 3600.0
    except ValueError:
        return 9999.0


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(override=True)
    force = "--broadcast" in os.sys.argv
    out = run_x_agent_tick(force_broadcast=force)
    print(json.dumps({k: out.get(k) for k in out if k != "actions"}, indent=2, default=str)[:3000])
    print("actions", len(out.get("actions") or []))
    for a in (out.get("actions") or [])[:20]:
        print(" ", a)
