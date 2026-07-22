# RSI-EAF — Support the Factory

**Status:** Live x402 merchant · seeking **external** organic payers (not factory wallets)

## Pay in 60 seconds (XRPL testnet)

1. Fund a wallet from the [testnet faucet](https://xrpl.org/xrp-testnet-faucet.html)
2. Send XRP to **`rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN`**
3. Set **Destination Tag**:
   - `1` → $1 verified tip
   - `2` → $2 paid briefing unlock
   - `3` → $3 micro-tool unlock

## Quick links

| Surface | URL |
|---------|-----|
| **Pay page** | https://published-zeta.vercel.app/pay.html |
| **Agent-pay** | https://published-zeta.vercel.app/agent-pay.json |
| **x402** | https://published-zeta.vercel.app/.well-known/x402 |
| **Free sample** | https://published-zeta.vercel.app/free-sample.json |
| **Tip manifest** | https://published-zeta.vercel.app/tip-manifest.json |
| **Service catalog** | https://published-zeta.vercel.app/service-catalog.json |
| **llms.txt** | https://published-zeta.vercel.app/llms.txt |
| **agents.txt** | https://published-zeta.vercel.app/agents.txt |
| **XRPL AI Hub** | https://xrpl-ai.org/address/rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN |
| **Bounty #178** | https://github.com/theCeramist/rsi-eaf/issues/178 |
| **aetherforge** | https://aetherforge.world |

## Agent path

```
GET https://published-zeta.vercel.app/agent-pay.json
GET https://published-zeta.vercel.app/.well-known/x402
# optional: free teaser
GET https://published-zeta.vercel.app/free-sample.json
# pay Tag 1 or 2 on testnet, then poll
GET https://published-zeta.vercel.app/payment-status.json
```

HTTP 402 resources:

- https://published-zeta.vercel.app/deliverables/briefing-latest.json
- https://published-zeta.vercel.app/deliverables/micro-tool-latest.json

## Full docs

- [Revenue surfaces](docs/REVENUE_SURFACES.md)
- [Outreach](docs/OUTREACH.md)
- [Agent-pay mirror](docs/agent-pay.json)
- [Free sample mirror](docs/free-sample.json)

**Treasury:** `rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN` (XRPL testnet)
