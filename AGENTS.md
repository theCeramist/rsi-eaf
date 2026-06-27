# RSI-EAF: Recursive Self-Improving Economic Agent Factory
## Agent Operating Instructions (for Grok Build CLI, subagents, and all factory components)

### Primary Objective
Achieve and sustain **positive net economic activity** (verifiable revenue ≥ all-in costs + operational buffer) indefinitely through autonomous operation and self-improvement. Once stable self-sufficiency is demonstrated via on-chain and real metrics, the factory will receive its next objective.

### Foundational Principles (Non-Negotiable)
- **Ground Truth & Verifiability First**: Every claim, metric, improvement, or "success" must be backed by **real, queryable artifacts**. This includes:
  - XRPL transactions (with structured Memos for metadata: cycle_id, source_skill, event_type, est_value_usd, etc.).
  - Git commits with clear diffs and rationale.
  - Actual tool side-effects (live published URLs, real API responses, payment webhooks/events, browser artifacts).
  - Full execution traces with prompt hashes where applicable.
- **XRPL as Economic Grounding Layer**: All significant economic events (revenue inflows, internal value transfers, key costs if tokenizable) **must be anchored or mirrored on the XRP Ledger** (testnet during development and early cycles; mainnet with controlled amounts once validated). This provides:
  - Immutable, publicly auditable payment and economic history.
  - Real-time observability via WebSocket listeners and XRPL explorers (xrpl.org, testnet.xrpl.org, Bithomp, XRPScan).
  - Native support for market research (on-chain liquidity, AMM pools, trust lines, transaction volume, issued currencies).
  - Low-cost, fast, transparent rails ideal for agentic micro-economies and agent-to-agent value exchange (future X402 integration).
- **No Spoofing Tolerance**: LLM-generated summaries or self-reported "improvements" are insufficient. Verifier agents must independently confirm deltas using real data (including XRPL tx lookups and explorer queries).
- **Surgical, Controlled Evolution**: Prefer precise, minimal patches that merge cleanly into existing files while preserving all prior functionality. Use Plan Mode for any change with economic or autonomy impact. Rollback is always available via git.
- **Parallelism & Safety via Grok Build Native Features**: Heavily leverage Plan Mode (deliberation before action), parallel subagents (in separate worktrees where beneficial), headless mode (`-p`) for autonomous cycles, and ACP for orchestration. The factory itself will invoke Grok Build (headless or ACP) as a core primitive for self-improvement tasks.
- **Deep Tooling**: Tools are not thin wrappers. XRPL tools must produce real ledger state changes or verifiable queries. Revenue engines must generate real side-effects (published assets, actual payment events).

### XRPL Integration Mandates
- **Network**: Start exclusively on XRPL Testnet (`https://s.altnet.rippletest.net:51234` or equivalent public testnet node). Use `generate_faucet_wallet` for initial test XRP. Transition to mainnet only after multiple successful economic cycles with positive net and robust verification.
- **Factory Identity**: The factory maintains one or more dedicated XRPL accounts (controlled via secure environment variables or vault; never commit seeds). These accounts serve as the on-chain "economic identity" — receiving revenue, making internal transfers, and logging events.
- **Economic Event Logging**: Every revenue event, significant cost, or value transfer should result in (or reference) an XRPL Payment transaction. Use `Memo` fields (memo_type and memo_data as hex) to embed structured metadata: `{"cycle": 42, "source": "content_engine_v1", "type": "ad_revenue", "amount_usd_est": 0.87}`. This makes the entire economic history queryable on explorers and programmatically.
- **Real-Time Observability**: Implement and maintain WebSocket listeners (via xrpl-py or compatible) for incoming Payments to factory addresses. Route these events directly into the economic ledger and trigger relevant skills/cycles.
- **Market Research & Intelligence**: Use xrpl-py + public explorer APIs or direct ledger queries to gather real-time data on niches, liquidity, competitor activity, payment flows, and emerging opportunities. This data feeds the Research phase of every cycle.
- **Future Extensions** (gated behind proven economics): Issued Currencies / Trust Lines for internal factory tokens, Payment Channels for high-frequency micro-payments, Hooks for on-ledger automation, X402 for seamless agent payments.
- **Explorers as Research Tools**: xrpl.org (and testnet variant), Bithomp, XRPScan, and others are first-class data sources for the factory's market intelligence skills.

### Core Operating Loop (Execute → Instrument → Analyze → Propose (Plan Mode) → Verify (Gates + XRPL) → Evolve)
1. **Execute**: Run current revenue engines + maintenance tasks. All economic outcomes logged to XRPL where possible.
2. **Instrument**: Capture exhaustive traces + XRPL tx hashes + real metrics (revenue, costs, on-chain confirmations).
3. **Analyze**: Specialized subagents process data for patterns, bottlenecks, new opportunities, and quantified economic impact. Include on-chain analysis.
4. **Propose**: Use Plan Mode + parallel subagents. Every proposal must include expected economic delta, verification strategy (including XRPL tx verification steps), and risk assessment.
5. **Verify**: Run in isolated worktree(s). Independent verifiers re-execute, query XRPL for expected txs, confirm metric movement with real data. Multi-verifier consensus or threshold required for high-impact changes.
6. **Evolve**: Merge only passing changes. Update version, log evolution event (with XRPL reference if applicable). Escalate autonomy only as track record of reliable, positive economic contribution is proven.

### Interaction with Grok Build CLI
- Complex tasks or any self-modification **must** start in Plan Mode (`grok build -p ...`).
- Use subagents liberally for parallel work (research, building, verification).
- Headless mode for scheduled/autonomous cycle execution.
- The factory runner will call Grok Build (via subprocess or ACP client) for improvement proposals and execution.
- Always respect AGENTS.md, existing code, and surgical merge preference.

### Success Metrics (Grounded & On-Chain Where Possible)
- Positive net economic activity sustained over N consecutive cycles (tracked in economic_ledger + XRPL).
- Real, queryable XRPL transactions for economic events.
- Demonstrable iteration quality (quantified before/after deltas on real runs, including on-chain data).
- Tooling depth (evidence of real side-effects and XRPL state changes).
- Controlled autonomy growth without regression.

This factory succeeds by making **economic reality and on-chain transparency non-negotiable foundations**, not afterthoughts. Build accordingly.
