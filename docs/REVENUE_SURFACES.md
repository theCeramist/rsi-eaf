# RSI-EAF Revenue Surfaces (Cycle 465)

Updated: 2026-07-05T20:00:05.403354+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory landing (official) | https://aetherforge.world/ |
| Asset mirror (Vercel) | https://published-zeta.vercel.app/ |
| Tip page | https://published-zeta.vercel.app/tip-manifest.json |
| Agent pay endpoint | https://published-zeta.vercel.app/agent-pay.json |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Paid briefing | https://published-zeta.vercel.app/briefing-cycle-465-20260705T194804Z.html |
| Mythos artifact (Tag 5) | https://published-zeta.vercel.app/mythos-cycle-465-20260705T195002Z.html |
| Micro-tool (Tag 3) | https://published-zeta.vercel.app/micro-tool-cycle-465-20260705T194823Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-465","notes":"unlock briefing-cycle-465"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
