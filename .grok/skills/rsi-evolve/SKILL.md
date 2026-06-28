---
name: rsi-evolve
description: Surgical RSI-EAF factory evolution checklist. Use during Grok headless/ACP evolution tasks on rsi-eaf.
---

# RSI-EAF Evolution Skill

When evolving rsi-eaf:

1. Read `Agents.md` — ground truth, XRPL anchoring, surgical patches only.
2. Change ONE focused thing per evolution turn.
3. Never commit `.env`, seeds, or tokens.
4. Verify: `python -m pytest tests/test_core.py -q`
5. Revenue surfaces: tip Tag 1, briefing Tag 2, treasury in memos.
6. GitHub: single-commit push via `tools/github_client.push_files`.
7. Nexus: merge `rsi_eaf_factory` into jarvis-swarm, do not clobber swarm state.
8. Log economic impact in proposal metadata (expected USD delta).