# Factory autonomy — human gates removed

The factory can complete outreach and distribution without a human clicking share buttons.

## Autonomous channels (live now)

| Channel | How | Human needed? |
|---------|-----|----------------|
| **ntfy.sh** | `https://ntfy.sh/rsi-eaf-factory` | No |
| **GitHub Issues** | Creates social feed issues | No (token) |
| **GitHub Discussions** | Enabled + auto-posted | No (token) |
| **docs/LATEST_OUTREACH.md** | Gist fallback | No |
| **RSS** | `/feed.xml` | No |
| **social-feed.json** | Machine wall | No |
| **XRPL AI Hub** | `maybe_register_xrpl_ai_hub` | No |
| **Surgical Vercel deploy** | API file deploy | No |
| **Test revenue pipeline** | `TEST_SUPPORTER_SEED` | No |

## Optional upgrades (set once in `.env`)

```
DISCORD_WEBHOOK=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BLUESKY_HANDLE=
BLUESKY_APP_PASSWORD=
GITHUB_SOCIAL_ISSUE=180
NTFY_TOPIC=rsi-eaf-factory
```

X/Twitter posting needs OAuth1 user tokens (`X_API_KEY` + secret + access token). Bearer alone is read-only.

## Still definitionally human / external

| Gate | Why factory cannot fully own it |
|------|----------------------------------|
| **External organic payer** | Must be a non-factory wallet |
| **External repo PRs** (awesome-x402) | Fine-grained token cannot fork/issue foreign repos |
| **True Gist API** | Token lacks `gist` scope — docs fallback used |

## Code paths

- `tools/autonomous_outreach.py` — multi-channel publisher
- `observability/distribution_daemon.py` — every tick
- `factory_core/cycle_runner.py` — post-cycle hook
- CLI: `python agent-tools/run_autonomous_outreach.py`

## Inventory JSON

- Local: `observability/human_gates_inventory.json`
- Live: https://published-zeta.vercel.app/human-gates.json
