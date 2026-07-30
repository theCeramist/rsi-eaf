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

## First payment (humans + agents)

1. Open https://published-zeta.vercel.app/pay.html (or CDN `public_pay/pay.html`)
2. Prefer **one-tap Xaman**: amount **1 XRP**, network **XRPL**, destination tag **1**
3. Or manual: mainnet wallet → treasury `FACTORY_MAINNET_TREASURY_ADDRESS` → **Destination Tag 1**
4. Unfunded accounts activate on first payment ≥ **1 XRP base reserve** (XRPL mainnet)
5. Treasury daemon + revenue ingest credit **organic** verified revenue
6. Ledger `verification_method` includes `xrpl_mainnet_treasury_*`

### Conversion notes (research-backed)

- **Mainnet only** for customer value — testnet has $0 market value
- **Destination tags** route SKUs on one merchant address ([XRPL docs](https://xrpl.org/docs/concepts/transactions/source-and-destination-tags))
- **Xaman payment-request links** reduce friction for mobile XRPL users
- **Agents** use `agent-pay.json` (`real_value: true`, `network: xrpl_mainnet`, xaman + `xrpl://` URIs)
- **Do not** advertise testnet as an equal pay option to external payers

## Safety

- Factory never spends mainnet XRP unless `MAINNET_OUTBOUND_ENABLED=true` and amount ≤ `MAINNET_MAX_OUTBOUND_XRP`
- Seeds never committed; never printed in full in logs
- Testnet treasury remains watched for regression / agent tests

## RSI after mainnet-ready

With revenue path live, evolution pressure returns to recursive self-improvement: gates, conversion fidelity, distribution quality — not network scaffolding.
