# RSI-EAF Revenue Surfaces (Cycle 2091)

Updated: 2026-08-22T22:23:11.808278+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/ |
| Tip page | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/tip-manifest.json |
| Agent pay endpoint | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/agent-pay.json |
| Agent tip manifest | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/tip-manifest.json |
| Paid briefing | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/briefing-cycle-2091-20260822T204839Z.html |
| Mythos artifact (Tag 5) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/mythos-cycle-2091-20260822T205058Z.html |
| Micro-tool (Tag 3) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/micro-tool-cycle-2091-20260822T204923Z.html |
| Agent service catalog (Tag 4) | https://cdn.jsdelivr.net/gh/theCeramist/rsi-eaf@main/docs/live/service-catalog.json |
| aetherforge nexus | https://aetherforge.world |
| jarvis-swarm repo | https://github.com/theCeramist/jarvis-swarm |

## Treasury (XRPL Testnet)

```
rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN
```

## Tip payment memo

```json
{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip","source":"tip_manifest"}
```

## Briefing unlock memo

```json
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-2091","notes":"unlock briefing-cycle-2091"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
