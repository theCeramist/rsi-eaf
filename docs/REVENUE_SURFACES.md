# RSI-EAF Revenue Surfaces (Cycle 11)

Verifiable XRPL testnet payment endpoints for the Recursive Self-Improving Economic Agent Factory.

## Live surfaces

| Surface | URL |
|---------|-----|
| Factory index | https://published-zeta.vercel.app/ |
| Tip page | https://published-zeta.vercel.app/tip-cycle-11-20260627T043141Z.html |
| Agent tip manifest | https://published-zeta.vercel.app/tip-manifest.json |
| Paid briefing (preview) | https://published-zeta.vercel.app/briefing-cycle-11-20260627T043211Z.html |
| Latest cycle asset | https://published-zeta.vercel.app/cycle-11-20260627T043121Z.html |

## Treasury (XRPL Testnet)

```
rBiU74q2wCPQ7ri9YD6J6LrQ2Y3jFd8pcN
```

Explorer: https://testnet.xrpl.org/

## Tip payment memo

```json
{"type":"revenue","amount_usd_est":1.0,"notes":"supporter tip","source":"tip_manifest"}
```

## Briefing unlock memo ($2)

```json
{"type":"revenue","amount_usd_est":2.0,"product_id":"briefing-cycle-11","notes":"unlock briefing-cycle-11"}
```

## Verification

Payments from **non-factory** wallets with `type: revenue` and `amount_usd_est > 0` are ingested as verified revenue on the next factory cycle.

## Agent integration

Fetch `tip-manifest.json` for machine-readable payment instructions. Schema: `rsi_eaf_tip_manifest_v1`.
