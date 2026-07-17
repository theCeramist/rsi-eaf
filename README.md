# RSI-EAF: Recursive Self-Improving Economic Agent Factory
**Grounded on the XRP Ledger for verifiable, transparent, self-sustaining economic activity.**

## Vision
A fully agentic factory that iteratively improves its own skills, tooling, and revenue engines until it generates enough verifiable value (via XRPL-anchored payments and real-world outputs) to cover all costs and operate indefinitely without external subsidies. Built and evolved primarily using the Grok Build CLI's Plan Mode, parallel subagents, headless execution, and ACP capabilities.

This scaffold establishes the XRPL grounding layer from day one, ensuring every economic event is observable, auditable, and tied to real ledger state.

## Key Differentiators vs. Prior Attempts
- **XRPL Grounding**: Payments, revenue events, and key metrics anchored on-ledger with Memos for rich metadata. Real-time WebSocket monitoring + explorer-backed research. Eliminates spoofing.
- **Radical Verifiability**: Multi-gate verification (including independent XRPL tx confirmation) before any evolution.
- **Surgical & Safe**: Plan Mode + worktree isolation + git-native merges. No reckless changes.
- **Deep, Real Tooling**: xrpl-py powered tools that produce actual ledger changes and queries.
- **Economic-First Loop**: Every cycle measured against real net (revenue - costs) with on-chain proof.

## Quick Start (Surgical Bootstrap)
1. **Prerequisites**
   - Latest Grok Build CLI installed and authenticated (`curl -fsSL https://x.ai/cli/install.sh | bash` or update).
   - Python 3.10+.
   - Git.

2. **Setup**
   ```bash
   git clone <your-repo> rsi-eaf   # or mkdir + git init if starting fresh
   cd rsi-eaf
   pip install -r requirements.txt
   cp .env.example .env  # Edit with any secrets (XRPL seeds later; start with faucet)
   ```

3. **XRPL Testnet Quickstart (Critical First Step)**
   - The factory uses XRPL Testnet by default.
   - Run the helper to create a factory-controlled test wallet (or let tools auto-faucet):
     ```bash
     python -c "
     from tools.xrpl_tools import create_factory_wallet
     wallet = create_factory_wallet()
     print('Factory XRPL Address:', wallet.classic_address)
     print('Seed (store securely in .env):', wallet.seed)
     "
     ```
   - Fund via public testnet faucet if needed (tools handle `generate_faucet_wallet`).
   - Verify on https://testnet.xrpl.org/

4. **Explore the Scaffold**
   - `AGENTS.md`: The binding instructions (Grok Build reads this).
   - `tools/xrpl_tools.py`: Core XRPL primitives (wallets, payments, monitoring, queries).
   - `observability/economic_ledger.py`: Local + XRPL-anchored event logging.
   - `factory_core/cycle_runner.py`: Skeleton of the main autonomous loop.
   - `revenue_engines/`: Where real value creation lives (start here after scaffold).

5. **Run First Validation Cycle (Manual)**
   Use Grok Build or manual execution to test XRPL integration:
   ```bash
   grok build -p "Using the current scaffold and AGENTS.md, create a minimal end-to-end test: Instantiate XRPL tools, create or load a test wallet, send a small self-payment with a structured Memo containing test cycle metadata, log the event via economic_ledger, and verify the transaction appears on testnet.xrpl.org. Output the tx hash and explorer link."
   ```

## Architecture Overview (Updated with XRPL)
```
rsi-eaf/
├── AGENTS.md                  # Binding rules (XRPL mandates, verification, surgical evolution)
├── README.md
├── requirements.txt
├── .env                       # XRPL seeds, API keys (never commit)
├── factory_core/
│   ├── cycle_runner.py        # Main loop: Execute → Instrument (XRPL) → Analyze → Propose (Plan) → Verify → Evolve
│   └── state.py               # Persistent state (git + optional local DB)
├── observability/
│   ├── trace_logger.py        # Full execution traces
│   ├── economic_ledger.py     # Revenue/cost events + XRPL anchoring + real-time listeners
│   └── dashboard/             # Future live view (metrics, on-chain txs, evolution timeline)
├── tools/
│   ├── xrpl_tools.py          # xrpl-py powered: wallets, payments, WS monitoring, ledger queries, market research
│   ├── hum/                   # Vendored HUM DREAMS (slow cognition) — https://github.com/nobulart/hum
│   └── general_tools.py       # Browser, code exec, publishing, etc. (deep & verifiable)
├── observability/dreams/      # Night capture + SURFACE.md (soft director feed; never auto-edits AGENTS.md)
├── factory_core/dreams_integration.py  # Cycle-end capture + surface cadence
├── skills/
│   ├── base_skill.py
│   └── [domain_skills]/       # Self-improving, versioned, with benchmarks + XRPL hooks
├── revenue_engines/
│   └── content_operator.py    # First engine: autonomous niche content + micro-products (logs revenue to XRPL)
├── gates/
│   └── verifier.py            # Multi-agent verification including XRPL tx confirmation
├── memory/                    # Long-term retrieval (vector + git history)
└── xrpl_integration/          # Advanced (issued currencies, Payment Channels, Hooks — gated)
```

## XRPL Integration Details
- **Library**: `xrpl-py` (official, pure Python).
- **Testnet URL**: `https://s.altnet.rippletest.net:51234`
- **Core Flows**:
  - Wallet management & faucet.
  - Send XRP Payments with rich Memos (hex-encoded JSON metadata).
  - Real-time incoming payment monitoring via WebSocket → triggers ledger + cycle logic.
  - Balance checks, account objects (trust lines, etc.).
  - On-chain queries for market intelligence (AMM, order books, recent activity).
- **Economic Anchoring**: Revenue events → XRPL Payment (or reference tx) with Memo. Explorer links stored in local ledger for instant auditability.
- **Explorers**: Use https://testnet.xrpl.org/ and mainnet equivalents for research and verification.

## HUM DREAMS (slow cognition)
Vendored from [nobulart/hum](https://github.com/nobulart/hum) (MIT) under `tools/hum/`.

- **Capture**: every hybrid cycle end (`factory_core.dreams_integration.record_cycle_dreams`) → `observability/dreams/DREAMS.md`
- **Surface**: every 3 cycles or when night count ≥ budget → `SURFACE.md` (also daily review)
- **Director/coordination**: soft `dream:*` priorities only — **never** override AGENTS.md, gates, or treasury
- **Skill**: `.grok/skills/dreams-capture`
- **CLI**: `python -m tools.hum.capture ...` · `python scripts/run_dreams_surface.py --force`

Env: `DREAMS_ENABLED`, `DREAMS_DIR`, `DREAMS_MAX_PER_CYCLE`, `DREAMS_SURFACE_EVERY_N_CYCLES`, `DREAMS_DIRECTOR_FEED`.

## Development & Evolution Workflow
- **Always** start significant work in **Plan Mode** with Grok Build.
- Use parallel subagents + worktrees for independent streams (e.g., one subagent researches niches via XRPL data + web, another builds publishing scripts).
- After any change: Run verification gates (including XRPL tx replay/confirmation where relevant).
- Commit surgically. Tag evolution milestones with XRPL tx references.
- Monitor live: WebSocket listeners + economic ledger dashboard (future).

## Success Criteria for This Scaffold Phase
- Factory can create/load XRPL test wallet and execute a real Payment with metadata Memo.
- Economic ledger successfully records events with XRPL tx hash + explorer link.
- First revenue engine stub can log a simulated (then real) revenue event on-ledger.
- Grok Build, when given a task referencing AGENTS.md, respects XRPL grounding and surgical style.

## Next Immediate Milestones (Post-Scaffold)
1. Flesh out `revenue_engines/content_operator.py` (or first chosen engine) with real publishing + XRPL revenue logging.
2. Implement full WebSocket payment monitor that feeds the cycle runner.
3. Close the self-improvement loop with a simple "analyze last cycle + propose small XRPL-optimized improvement" using Plan Mode.
4. Run 5–10 autonomous cycles and demonstrate positive (or trending) net with on-chain proof.

This scaffold is intentionally lean and surgical. Every component is designed to be extended cleanly without breakage. The XRPL layer makes economic reality visible and undeniable from the first transaction.

**Let's make the factory real — on-chain, verifiable, and self-sustaining.**

Run the first Grok Build plan command above and report the tx hash + explorer link when successful. Then we iterate surgically.

## Revenue Surfaces

Public factory outputs and XRPL payment endpoints (cycle 11):

- **Live index:** https://published-zeta.vercel.app/
- **Tip page:** https://published-zeta.vercel.app/tip-cycle-11-20260627T043141Z.html
- **Tip manifest (agents):** https://published-zeta.vercel.app/tip-manifest.json
- **Paid briefing:** https://published-zeta.vercel.app/briefing-cycle-11-20260627T043211Z.html
- **Docs:** [docs/REVENUE_SURFACES.md](docs/REVENUE_SURFACES.md)

Send XRPL testnet payments to the factory treasury with a `revenue` memo — see docs for templates.
