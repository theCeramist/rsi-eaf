# RSI-EAF Revenue Surfaces (Cycle 1895)

Updated: 2026-08-17T06:28:29.956220+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/factory/ |
| Tip page | https://aetherforge.world/factory/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/factory/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/factory/tip-manifest.json |
| Paid briefing | https://aetherforge.world/factory/briefing-cycle-1895-20260817T062539Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/factory/micro-tool-cycle-1895-20260817T062609Z.html |
| Agent service catalog (Tag 4) | https://aetherforge.world/factory/service-catalog.json |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1895","notes":"unlock briefing-cycle-1895"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
