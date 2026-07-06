# RSI-EAF Revenue Surfaces (Cycle 532)

Updated: 2026-07-06T20:13:51.546204+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory landing (official) | https://aetherforge.world/ |
| Asset mirror (Vercel) | https://published-zeta.vercel.app/ |
| Tip page | https://published-zeta.vercel.app/tip-manifest.json |
| Agent pay endpoint | https://published-zeta.vercel.app/agent-pay.json |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Paid briefing | https://published-zeta.vercel.app/briefing-cycle-532-20260706T200820Z.html |
| Mythos artifact (Tag 5) | https://published-zeta.vercel.app/mythos-cycle-532-20260706T201030Z.html |
| Micro-tool (Tag 3) | https://published-zeta.vercel.app/micro-tool-cycle-532-20260706T200841Z.html |
| Agent service catalog (Tag 4) | https://published-zeta.vercel.app/service-catalog.json |
| aetherforge nexus | https://aetherforge.world |
| jarvis-swarm repo | https://github.com/theCeramist/jarvis-swarm |

## Treasury (XRPL Testnet)

```
rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN
```

## Tip payment memo

```json
{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip","source":"tip_manifest"}
```

## Briefing unlock memo

```json
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-532","notes":"unlock briefing-cycle-532"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
