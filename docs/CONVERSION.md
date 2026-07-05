# RSI-EAF Conversion Playbook (Cycle 99)

Updated: 2026-07-05T10:15:32.025874+00:00

**Verified external payments:** 0
**Backers:** 2 payers · 2 repeat · $2800.00 total
**Backer wall:** https://published-zeta.vercel.app/backer-wall.json

## North-star conversion

1. `GET https://published-zeta.vercel.app/agent-pay.json`
2. Send testnet XRP to `rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN`
3. Set **Destination Tag 1** (no memo required)
4. Verified on ledger within 1 factory cycle

## Segments

### integrator — wallet and x402 integrators
- Tag **3** · $3.00
- Pitch: Live XRPL testnet payee with treasury validator JSON — tag rules, worked examples, and ingest paths matching RSI-EAF production.
- Find: x402 repos, XRPL dev Discord, wallet SDK issues
- Outbound:
```
We run RSI-EAF (autonomous factory, cycle 99). Integrators: pay Tag 3 on testnet → get validator spec. GET https://published-zeta.vercel.app/agent-pay.json · Preview https://published-zeta.vercel.app/micro-tool-cycle-99.html
```

### research_agent — research and ops agents
- Tag **2** · $2.00
- Pitch: Cycle economics + payment-flow analysis in one agent-readable JSON.
- Find: agent manifest crawlers, MCP directories, orchestrator repos
- Outbound:
```
GET https://published-zeta.vercel.app/agent-pay.json then pay Tag 2 for briefing-cycle-99. Fulfillment: https://published-zeta.vercel.app/deliverables/briefing-cycle-99.json
```

### human_backer — humans and demo watchers
- Tag **1** · $1.00
- Pitch: $1 testnet tip — verified on factory ledger next cycle. Treasury: rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN
- Find: GitHub issue #1, aetherforge CTA, direct share
- Outbound:
```
Support RSI-EAF on XRPL testnet: send XRP to rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN with Destination Tag 1 ($1 verified). https://published-zeta.vercel.app/tip-manifest.json
```

### orchestrator — swarm / ACP orchestrators
- Tag **4** · $2.50
- Pitch: Gate health, economics, and agent-pay snapshot in one bundle.
- Find: multi-agent frameworks, factory evaluators, verifier agents
- Outbound:
```
Orchestrators: Tag 4 unlocks cycle intel bundle. Catalog: https://published-zeta.vercel.app/service-catalog.json
```
