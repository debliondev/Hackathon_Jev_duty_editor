# CLAUDE.md: context for coding agents

Project: **Editor de guardia (30X × JEV)**. Classifies generated 30X content as aprobar / descartar / revisar
with one JEV (TypeSafe System One) call per piece. Start with README.md and APRENDE_JEV.md.

## Non-negotiables
- Everything computable goes in code (`editor/prechequeos.py`). Never ask JEV to count, add, compare dates or prices.
- Question texts live **only** in `config/reglas.yaml`; thresholds and weights **only** in `config/policy.yaml`.
- One condition per Noul (high = problem), one dimension per Score, no numeric levels or "better than previous".
- Question IDs are stable: renaming breaks history and the cache.
- Pin the model (`jev-1.13.0`), never `jev-latest`. Log `resp.model` on every decision.
- `editor/decidir.py` stays pure (no I/O). Tests never touch the network (replay or fixtures).
- Never tune with the `test` split. Never copy golden-set pieces into criteria examples.
- No real names, no real 30X voices, no personal data, no content aimed at minors, no invented programs, prices or dates.
- Never commit `.env` or log `TYPESAFE_API_KEY`.

## Conventions
- Python 3.10+, typed, ruff + black (line length 100). Spanish identifiers and docstrings; user-facing docs in English.
- Run `make test` after any change. Run `make datos` after editing the generator (a test checks the files are current).

## SDK facts (typesafe-sdk 0.7.5)
- `AsyncTypeSafeClient(model=...)` throws at construction without a key, so replay mode must not create it.
- `resp.answers[id]` holds pydantic `NoulAnswer{noul}`, `ScoreAnswer{score, confidence, probabilities: dict[int,float], legend}`
  or `ChoiceAnswer{choice, confidence, probabilities}`; `resp.usage.input_tokens`; `resp.model`.
- `Noul(criteria={"true": ..., "false": ...})`, `Score(criteria=[...])`, `Choice(criteria={label: desc})`.
