# XRPL Mainnet Revenue Path

## Posture

| Layer | Network | Purpose |
|-------|---------|---------|
| **Public revenue** | **Mainnet** | Real XRP tips/products from social + agent payers |
| **Ops anchors** | Testnet | Cycle memos / self-payments (no real XRP spend) |
| **Outbound mainnet** | Disabled by default | `MAINNET_OUTBOUND_ENABLED=false` |

## Bootstrap

```bash
python -u scripts/mainnet_revenue_ready.py
```

Creates (if missing):

- `FACTORY_MAINNET_TREASURY_ADDRESS` / `FACTORY_MAINNET_TREASURY_SEED` in `.env`
- Dual-network config: `XRPL_NETWORK=dual`, `XRPL_REVENUE_NETWORK=mainnet`, `XRPL_OPS_NETWORK=testnet`
- Local secret mirror: `observability/secrets/mainnet_treasury.json` (gitignored)

## Public surfaces

- `pay.html` — primary mainnet CTA
- `agent-pay.json` — machine contract (`network: xrpl_mainnet`, `real_value: true`)
- `tip-manifest.json` — tip tags
- `network-status.json` / `treasury-map.json` — dual treasury map

## First payment

1. Payer sends **mainnet XRP** to published treasury with **Destination Tag 1**
2. Unfunded accounts activate on first payment ≥ reserve
3. Treasury daemon + revenue ingest credit **organic** verified revenue
4. Ledger `verification_method` includes `xrpl_mainnet_treasury_*`

## Safety

- Factory never spends mainnet XRP unless `MAINNET_OUTBOUND_ENABLED=true` and amount ≤ `MAINNET_MAX_OUTBOUND_XRP`
- Seeds never committed; never printed in full in logs
- Testnet treasury remains watched for regression / agent tests

## RSI after mainnet-ready

With revenue path live, evolution pressure returns to recursive self-improvement: gates, conversion fidelity, distribution quality — not network scaffolding.
