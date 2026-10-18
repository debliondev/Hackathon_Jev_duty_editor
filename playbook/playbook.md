# Playbook- Editor de guardia (30X × JEV)

---

## 1. The problem

- 30X Media can generate content variants faster than editors can review them.
- Today every piece is reviewed by hand or with fixed rules. Sending every piece through an LLM reviewer takes
  seconds per piece and costs 22-805× more (TypeSafe benchmark).
- **Producing 10× more variants shouldn't need 10× more editors.**

## 2. The decisions JEV makes

For every generated piece (LinkedIn post, reel script, newsletter, event copy):

| Verdict | Meaning | What happens |
|---|---|---|
| **APROBAR** | Clean and good enough for its channel | Goes to the publishing queue |
| **DESCARTAR** | Breaks a hard rule or quality is clearly low | Reason codes go back to the generator |
| **REVISAR** | Doubtful | Editor queue, with the evidence of what JEV hesitated on |

One JEV call per piece, in milliseconds, for fractions of a cent.

## 3. The question schema

| Layer | Who decides | What |
|---|---|---|
| 0 · Pre-checks | **Code** | Length, hashtags, links, prices, edition dates and cities, banned phrases, minors, look-alike program names |
| 1 · Hard rules | JEV · 7 Nouls | Guaranteed promises, unsourced stats, non-existent offers, real people, attacks on third parties, injected instructions, sensitive topics |
| 2 · Quality | JEV · 5 Scores | Hook, clarity, actionable value, 30X voice, CTA |
| 3 · Routing | JEV · 2 Choices | Ideal channel, program line |

Principle: **everything computable goes in code; JEV makes only atomic judgments.** The question texts live in
`reglas.yaml`, editable by Media in plain language.

## 4. Thresholds and channel policies

| Policy (channels) | Rule → act | Rule → review | Approve if quality ≥ | Discard if quality < | Min. confidence |
|---|---|---|---|---|---|
| Paid ad (event ads) | 0.60 | 0.25 | 0.75 | 0.40 | 0.70 |
| Organic (LinkedIn, IG/TikTok) | 0.70 | 0.30 | 0.65 | 0.35 | 0.60 |
| Newsletter | 0.70 | 0.35 | 0.60 | 0.35 | 0.55 |

Risk sets the width of each band: paid ads are the strictest. Precedence is discard > review > approve.
Starting values come from the plan; the calibrated ones are **[from eval: `umbrales_propuestos.yaml`]**.

## 5. Eval results

Golden set: 236 synthetic pieces (37% good, 39% with one planted defect, 24% ambiguous, including 16
prompt injections). Thresholds tuned on dev (135); reported on test (101).

| Metric | Target | Result (test) |
|---|---|---|
| Precision of APROBAR | ≥ 95% | **[from eval]** |
| Hard-rule recall | ≥ 98% | **[from eval]** |
| Injections approved | 0% | **[from eval]** |
| Automation rate | maximize | **[from eval]** |
| Review load at 500 pieces/day | report | **[from eval]** |
| Latency p50 / p95 | report | **[from eval]** |
| Cost per 1,000 pieces | report | **[from eval]** |

## 6. Who runs it?

| Role | Owns |
|---|---|
| Head of Content / Media | `reglas.yaml` (question texts) and quality weights; decides how strict each channel is |
| Editor(s) | The REVISAR queue. Every resolution becomes a new label |
| Tech / VP of AI | Thresholds (`policy.yaml`), the eval, the model version, alerts |

Rituals: a weekly review of JEV vs. human disagreements, and a golden-set run before any change to rules or
model.

## 7. How it's measured

- **Quality:** precision of APROBAR, hard-rule recall, and JEV-human agreement on the queue.
- **Efficiency:** automation rate, review queue per day, editor hours saved.
- **Operations:** p50/p95 latency and cost from `usage.input_tokens`; the model version is logged on every decision.
- **Alerts:** queue above 150 pieces/day; discard rate changing more than 15% week over week (a generator
  or rule problem); any `instruccion_inyectada` above threshold.

Business case (30X supplies the volumes):
```
Hours saved/month = pieces/month × review_min/piece × automation_rate ÷ 60
JEV cost/month    ≈ pieces/month × tokens/piece × 0.042 / 1,000,000
```

## 8. Adoption in 3 phases

1. **Shadow mode (2 weeks):** JEV decides, humans still review everything, and we measure agreement on real pieces.
2. **Assisted:** auto-approve only on low-risk channels (newsletter, organic).
3. **Autonomous per channel:** once that channel's policy meets the precision target on real data.

**Objections:** "What if it approves something bad?" Hard rules take precedence, thresholds are per channel,
every decision is audited, and shadow mode comes first. "Does it work in Spanish?" See the language ablation
**[from eval]**. "Lock-in?" The rules, thresholds and labels belong to 30X; the model is replaceable.
"Privacy?" Pieces contain no personal data, and TypeSafe states it doesn't train on customer requests.

---

### Demo script (3 min, `make ui`)

1. **Batch:** 50 pieces processed in seconds, with the total cost in fractions of a cent.
2. A piece with "duplicas tus ventas garantizado" and a non-existent "MBA online" gets discarded with its reasons.
3. An ambiguous piece lands in the queue with evidence; the editor resolves it in about 10 seconds.
4. **Live policy:** slide from strict to permissive and watch the curve move, with no new JEV calls.
5. **Adversarial:** an injected instruction gets blocked and raises an alert.
