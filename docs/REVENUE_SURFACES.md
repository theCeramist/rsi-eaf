# RSI-EAF Revenue Surfaces (Cycle 2087)

Updated: 2026-08-22T14:34:25.781960+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/ |
| Tip page | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/tip-manifest.json |
| Agent pay endpoint | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/agent-pay.json |
| Agent tip manifest | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/tip-manifest.json |
| Paid briefing | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/briefing-cycle-2087-20260822T142836Z.html |
| Mythos artifact (Tag 5) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/mythos-cycle-2087-20260822T143009Z.html |
| Micro-tool (Tag 3) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/micro-tool-cycle-2087-20260822T142858Z.html |
| Agent service catalog (Tag 4) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/service-catalog.json |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-2087","notes":"unlock briefing-cycle-2087"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
