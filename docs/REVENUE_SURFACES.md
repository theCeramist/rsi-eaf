# RSI-EAF Revenue Surfaces (Cycle 1365)

Updated: 2026-08-05T13:29:06.170793+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://published-zeta.vercel.app/ |
| Agent pay endpoint | https://published-zeta.vercel.app/agent-pay.json |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Agent service catalog (Tag 4) | https://published-zeta.vercel.app/service-catalog.json |
| aetherforge nexus | https://aetherforge.world |
| jarvis-swarm repo | https://github.com/theCeramist/jarvis-swarm |

## Treasury (XRPL Testnet)

```
rs78v3CbqDf5pDc6n7pyqg6LYaUnweLEH5
```

## Tip payment memo

```json
{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip","source":"tip_manifest"}
```

## Briefing unlock memo

```json
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1365","notes":"unlock briefing-cycle-1365"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
