# RSI-EAF Revenue Surfaces (Cycle 1851)

Updated: 2026-08-15T11:44:50.817559+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://published-zeta.vercel.app/ |
| Tip page | https://published-zeta.vercel.app/tip-cycle-1851-20260815T112933Z.html |
| Agent pay endpoint | https://published-zeta.vercel.app/agent-pay.json |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Paid briefing | https://published-zeta.vercel.app/briefing-cycle-1851-20260815T112830Z.html |
| Mythos artifact (Tag 5) | https://published-zeta.vercel.app/mythos-cycle-1851-20260815T112955Z.html |
| Micro-tool (Tag 3) | https://published-zeta.vercel.app/micro-tool-cycle-1851-20260815T112852Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1851","notes":"unlock briefing-cycle-1851"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
