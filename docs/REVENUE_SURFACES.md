# RSI-EAF Revenue Surfaces (Cycle 1838)

Updated: 2026-08-14T21:31:03.576580+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/factory/ |
| Tip page | https://aetherforge.world/factory/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/factory/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/factory/tip-manifest.json |
| Paid briefing | https://aetherforge.world/factory/briefing-cycle-1838-20260814T212710Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/factory/mythos-cycle-1838-20260814T212835Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/factory/micro-tool-cycle-1838-20260814T212732Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1838","notes":"unlock briefing-cycle-1838"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
