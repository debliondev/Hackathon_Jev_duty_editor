# Editor de guardia (30X × JEV)

An "on-call editor" that receives already-generated 30X content pieces (LinkedIn posts, reel scripts,
newsletters, event copy) and decides **APROBAR / DESCARTAR (with reason codes) / REVISAR (human)**,
using **JEV** (TypeSafe's System One model) in **one call per piece**.

> **Guiding principle:** everything computable lives in code; JEV only makes atomic judgments.
> Final decisions and thresholds live in code and YAML, never inside the model.

New to JEV? Read **[APRENDE_JEV.md](APRENDE_JEV.md)** first. It explains the model, the primitives and
how this project uses them, step by step.

---

## Quick start

```bash
make install                 # 1) venv + dependencies
make ui                      # 2) Streamlit UI at http://localhost:8501
```

The UI and the eval run in **replay mode** by default: they read JEV answers from
`cache/jev_respuestas.json`, with no network and no API key. **The cache ships empty.** Someone with a key has
to record it once (next section). After that recording is committed, anyone can clone the repo and run it with
the two commands above.

Without `make`: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`, then
`.venv/bin/streamlit run ui/app.py`.

## Recording real JEV answers (one time, needs a key)

```bash
cp .env.example .env         # put your key in TYPESAFE_API_KEY=...
make record                  # calls JEV for the 216 golden-set pieces that pass layer 0; ~1-2 minutes
make barrido reporte         # threshold sweep + curve PNG + eval/reporte.md
make experimentos            # permutation / language / adversarial (records the extra calls)
git add cache/ eval/         # commit the cache so replay works for everyone
```

- **Cost:** each call sends about 12.5k characters (state + 14 questions). Recording everything costs
  well under US$0.10 at US$0.042 per million input tokens. The real number is in `usage.input_tokens`
  and is reported by the eval.
- `record` mode only calls JEV for pieces **not already in the cache**, so it is safe to re-run.
- Editing any text in `config/reglas.yaml`, changing the model or changing the language produces **new cache
  keys**, so you must record again.

## JEV modes (`JEV_MODE`)

| Mode | Network | Writes cache | Use |
|---|---|---|---|
| `replay` (default) | no | no | demos, tests, CI, anyone without a key |
| `record` | only for missing keys | yes | first recording, after editing rules |
| `live` | always | no | trying new texts in the UI's adversarial tab |

## How a piece flows

```
Pieza ─► CAPA 0 prechequeos.py (code: length, hashtags, links, prices, dates, banned words, minors)
           │ hard failure ──► DESCARTAR (P0_*)            (JEV is not called: cheaper and deterministic)
           ▼
         ONE JEV call: 7 Nouls (rules) + 5 Scores (quality) + 2 Choices (routing)
           ▼
         decidir.py (pure function; thresholds per channel from policy.yaml)
           ├─► APROBAR    → publishing queue
           ├─► DESCARTAR  → reason codes (fed back to the generator)
           └─► REVISAR    → editor queue with evidence ("cifra_sin_fuente = 0.58", "voz_30x hesitated between 1 and 2")
```

## Repository map

| Path | What it is |
|---|---|
| `config/reglas.yaml` | **Every question text** sent to JEV (EN + ES) plus layer-0 settings. Owned by Media. |
| `config/policy.yaml` | **Every threshold and weight.** Owned by Tech. |
| `config/catalogo.json` | 30X public catalog (closed list, verified against 30x.com on 2026-10-18; no prices are public). |
| `config/guia_voz.md` | Simulated voice guide (inferred from public content). |
| `editor/prechequeos.py` | Layer 0: deterministic checks. |
| `editor/preguntas.py` | Builds the question battery from `reglas.yaml`. |
| `editor/jev_client.py` | JEV wrapper: live / record / replay, cache, concurrency. |
| `editor/decidir.py` | Decision engine (pure, no I/O). |
| `editor/pipeline.py` | `Editor.evaluar_pieza / evaluar_lote / redecidir`. |
| `editor/almacen.py` | SQLite: decisions, review queue, human feedback. |
| `editor/api.py` | FastAPI (`make api`, docs at `/docs`). |
| `data/synthetic/` | Golden set generator (template-based, seed fixed), `piezas.jsonl`, `etiquetas.csv`. |
| `eval/` | Eval, threshold sweep, experiments, `reporte.md` (auto-generated). |
| `ui/app.py` | Streamlit: batch, review queue, live policy slider, adversarial demo. |
| `playbook/playbook.md` | The 8-slide playbook. |
| `tests/` | 57 tests, no network. |

## API

| Method | Path | Returns |
|---|---|---|
| POST | `/evaluar` | one `Decision` |
| POST | `/evaluar/lote` | decisions + summary (counts, total cost, latency) |
| GET | `/cola` | pieces in REVISAR with readable evidence |
| POST | `/cola/{pieza_id}/resolver` | stores `{veredicto, nota}` as a new label |
| GET | `/metricas` | automation, reason distribution, accumulated cost |

In replay mode, a piece that isn't in the cache returns **409** with instructions.

## Golden set

236 synthetic pieces (seed 30): 88 good (37%), 92 with **one** planted defect (39%) and 56 deliberately
ambiguous (24%). Splits: dev 135 / test 101, stratified by defect. The defect matrix covers every layer-1 rule,
every layer-0 check and every quality dimension × 4 channels × obvious/subtle, plus 16 prompt-injection pieces
in 4 positions. The generator **validates itself against layer 0** and stops if a label doesn't match.

No real people, no real 30X voices and no personal data. Names are obviously fictional ("Lucía Inventada",
"Academia Rivalta"). The only mentions of minors are the 4 `P0_MENOR` test pieces, which exist so that check
has something to catch.

## Deviations from the original plan (and why)

1. **`state.catalogo` includes every program name** (compact `{programa, linea}`), with full details only for the
   detected programs. Without the full list of names, JEV can't answer `oferta_inexistente`.
2. **Catalog changes found on 30x.com (2026-10-18):** the youth program is now "IA para Jóvenes" (not "Next")
   and stays excluded. Medellín has no listed edition. CDMX shows two different dates (5-7 Oct and 24-26 Nov),
   so both are accepted with `verificada: false` until 30X confirms.
3. **`P0_PROGRAMA` effect is `marcar`:** it is sent to JEV as context and the piece goes to REVISAR, unless
   JEV discards it first (for example via `oferta_inexistente`).
4. **The threshold sweep applies the same thresholds to every channel policy** (simpler grid). It writes
   `umbrales_propuestos.yaml` and never edits `policy.yaml`: a human applies the result.
5. **Stability experiment (repeat N=5) is not implemented.** It was optional.

## Development

```bash
make test        # 57 tests, no network
make lint        # ruff + black
make datos       # regenerate the golden set (deterministic)
```

Code conventions: Python 3.10+, Spanish identifiers and docstrings, question texts only in `reglas.yaml`,
numbers only in `policy.yaml`, pure decision logic. Never commit `.env`.
