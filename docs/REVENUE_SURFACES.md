# RSI-EAF Revenue Surfaces (Cycle 1924)

Updated: 2026-08-18T08:11:27.407005+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/ |
| Tip page | https://aetherforge.world/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/tip-manifest.json |
| Paid briefing | https://aetherforge.world/briefing-cycle-1924-20260818T080747Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/mythos-cycle-1924-20260818T080858Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/micro-tool-cycle-1924-20260818T080810Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1924","notes":"unlock briefing-cycle-1924"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
