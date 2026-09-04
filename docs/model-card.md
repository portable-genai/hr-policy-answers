# Model card: Policy and HR Copilot (H2)

**This system has no model in its path.** There is no generation, narration or LLM port bound in
any profile, so this card records a BOUNDARY rather than a model. It exists so nobody has to infer
the absence from a missing file, and so the terms are already set if a model is ever added.

## There is no model. The evidence.

The whole boundary set is four port modules (`ports/audit.py`, `ports/identity.py`,
`ports/observability.py`, `ports/review_router.py`) declaring five bound ports: `audit`,
`identity`, `review_router`, `tracer` and `evaluation`. `tests/contract/test_port_parity.py`
asserts set equality across all five homes a port lives in, so an unregistered port cannot be
running quietly. `adapters/local/` holds one adapter module per bound port and nothing else
besides its package marker: `audit.py`, `evaluation.py`, `identity.py`, `review_router.py`,
`tracer.py`. None of them is a model client, and no profile binds one.

The tagline says "copilot" and "cited policy answers", so the citations deserve a direct answer:
**they come from the rule packs, deterministically.** Each pack file under `config/packs/` carries
a `source_id` and a `source_title`, each rule carries a `citation_clause`, and
`EntitlementRule.citation()` in `domain/packs.py` assembles them into the `Citation` attached to
every number derived from that rule. A cited answer here is cited because the data says which
clause produced it, not because a model claimed a source.

One model id does appear in the repo, and it is not a model this service calls: `_GATED_MODEL =
"gemini-3.5-flash"` in `adapters/gcp/evaluation.py`, mirrored in `eval/run_eval.py`, is the label
the `model-quality-gate` promotion client records a verdict AGAINST so a future model swap invalidates the old
verdict rather than inheriting it. No code path in this repo sends it a prompt.

## What produces each consequential output

| Output | Produced by | Nature |
|---|---|---|
| Entitled days, days taken, balance | `domain/entitlement_engine.py::_entitled_days` and `compute` | pure stdlib, replayable from frozen inputs |
| Verdict status (`COMPUTED` or `NEEDS_INFO`) | `EntitlementEngine.compute` via `PackSet.match` | fail-closed: no matching rule means no number at all |
| The citation set | `domain/packs.py::EntitlementRule.citation` | assembled from pack data |
| Severity, decision and approval path | `EntitlementEngine._computed` / `._needs_info`; `domain/triage_service.py` for the free-text path | deterministic bands and fixed chains |
| The escalation, and where it went | `ports/review_router.py`, routed in the same call by `api/app.py`, `cli/main.py` and `agent/tools.py` | rule R8; never a flag alone |

## The boundary a model would have to respect

If a generation port is ever added, these are the terms, and none of them is negotiable:

- It **may** restate or narrate a worksheet the engine has already computed and cited.
- It **may never** produce an entitlement, a figure, a verdict status, an approval path or a
  citation. The consequential decision stays deterministic and replayable.
- Employee personal data is **redacted before any model call**, using the same `pii-kit` rows the
  audit write masks with. The precedent is already in `agent/tools.py`, which walks the whole
  result structure before it can enter a model's context.
- Every answer stays **cited to a policy clause** from the packs. An uncited restatement is not
  shippable, and empty retrieval must be a hard error rather than an ungrounded answer.
- The escalation still routes to **`human-review-console` under rule R8**, in the same call that produced the
  result. A model in the path changes nothing about who decides.

## Controls that must exist BEFORE a model is introduced

1. **A generation port, registered in the five places `CONTRIBUTING.md` names**: the Protocol in
   `ports/`, the `PORT_PROTOCOLS` entry, `config.DEFAULT_BINDINGS` plus a `Container` accessor,
   `config/settings.yaml`, and a `PortCase` in `tests/contract/canonical.py`, with an adapter in
   all three families. Anything less runs with no enforcement at all.
2. **A pinned model id, recorded here**, in the same commit that binds it, and kept in step with
   `_GATED_MODEL` so a promotion verdict is keyed to the model that produced the evidence.
3. **Budget and rate limits plus a kill switch** (P-10, P-11): a per-request token budget, a rate
   limit, and a switch that forces deterministic-only operation with the model disabled. The
   engine already works with no model, so the kill switch is a real fallback rather than an outage.
4. **An eval that scores the LIVE model's groundedness against the packs.** Today's three metrics
   (`entitlement_accuracy`, `review_safety`, `pii_safety`, all at 0.99) score the deterministic
   engine. A model needs its own metric, proven able to go red, and it belongs in the `model-quality-gate`
   promotion bundle rather than only in the offline smoke run.
5. **Prompt-injection screening through the `agent-guardrail-gateway`** on any untrusted text before
   generation, and output filtering after, failing closed to deterministic-only when the screen is
   unavailable. There is no `GuardrailPort` today; `COMPLIANCE.md` R1 records that as owed.
6. **An explicit position on employee data reaching a managed model.** This is HR data with a real
   identifier stream, so redaction before the call is necessary but not sufficient: decide and
   record whether masked employee facts may leave the residency boundary at all, under whose legal
   basis, and with what retention on the provider side. That decision is the adopter's, and it
   should be written into `COMPLIANCE.md` before the port is bound, not after.

## Status

The system is **model-free today**. Every consequential output is produced by deterministic
stdlib engines, and the offline gate proves it on every change. This card records the boundary a
model would have to respect and the controls that must precede it, rather than a model. Delete
this section and describe the model properly on the day one is bound.
