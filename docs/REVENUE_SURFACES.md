# RSI-EAF Revenue Surfaces (Cycle 2160)

Updated: 2026-08-30T03:21:52.381622+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://published-zeta.vercel.app/ |
| Agent pay endpoint | https://published-zeta.vercel.app/agent-pay.json |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Paid briefing | https://published-zeta.vercel.app/briefing-cycle-2160-20260830T031314Z.html |
| Mythos artifact (Tag 5) | https://published-zeta.vercel.app/mythos-cycle-2160-20260830T031416Z.html |
| Micro-tool (Tag 3) | https://published-zeta.vercel.app/micro-tool-cycle-2160-20260830T031338Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-2160","notes":"unlock briefing-cycle-2160"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
