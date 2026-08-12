# RSI-EAF Revenue Surfaces (Cycle 1789)

Updated: 2026-08-12T20:17:52.268820+00:00

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://aetherforge.world/ |
| Tip page | https://aetherforge.world/tip-manifest.json |
| Agent pay endpoint | https://aetherforge.world/agent-pay.json |
| Agent tip manifest | https://aetherforge.world/tip-manifest.json |
| Paid briefing | https://aetherforge.world/briefing-cycle-1789-20260812T192302Z.html |
| Mythos artifact (Tag 5) | https://aetherforge.world/mythos-cycle-1789-20260812T192426Z.html |
| Micro-tool (Tag 3) | https://aetherforge.world/micro-tool-cycle-1789-20260812T192330Z.html |
| Agent service catalog (Tag 4) | https://aetherforge.world/service-catalog.json |
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
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-1789","notes":"unlock briefing-cycle-1789"}
```

## Verification

External payments with `type: revenue` and `amount_usd_est > 0` become verified revenue on the next cycle.
