# RSI-EAF Revenue Surfaces (Cycle 1775)

Updated: 2026-08-12T06:42:06.723704+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/ |
| Tip page | https://aetherforge.world/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/tip-manifest.json |
| Paid briefing | https://aetherforge.world/briefing-cycle-1775-20260812T063456Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/mythos-cycle-1775-20260812T063614Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/micro-tool-cycle-1775-20260812T063521Z.html |
| Agent service catalog (Tag 4) | https://aetherforge.world/service-catalog.json |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1775","notes":"unlock briefing-cycle-1775"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
