# RSI-EAF Revenue Surfaces (Cycle 1875)

Updated: 2026-08-16T11:57:42.931716+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/factory/ |
| Tip page | https://aetherforge.world/factory/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/factory/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/factory/tip-manifest.json |
| Paid briefing | https://aetherforge.world/factory/briefing-cycle-1875-20260816T114308Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/factory/mythos-cycle-1875-20260816T114432Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/factory/micro-tool-cycle-1875-20260816T114332Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1875","notes":"unlock briefing-cycle-1875"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
