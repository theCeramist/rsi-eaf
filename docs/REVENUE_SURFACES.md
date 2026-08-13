# RSI-EAF Revenue Surfaces (Cycle 1794)

Updated: 2026-08-13T01:01:34.770627+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/ |
| Tip page | https://aetherforge.world/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/tip-manifest.json |
| Paid briefing | https://aetherforge.world/briefing-cycle-1794-20260813T005843Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/mythos-cycle-1794-20260813T010013Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/micro-tool-cycle-1794-20260813T005910Z.html |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1794","notes":"unlock briefing-cycle-1794"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
