# Features FAQ

For product, HR operations and delivery teams: what this service does, what is deterministic,
and where its responsibilities **stop** and a sibling catalog system takes over.
Cross-references: [`../../README.md`](../../README.md), [`../../DEMO.md`](../../DEMO.md),
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md).

### What does H2 actually produce?

A cited **entitlement worksheet**. Given an employee's structured facts (an opaque reference, the
jurisdiction, the employment type, completed months of service, leave days already taken, and
whether the question is termination-linked), plus an optional `as_of` date, it computes:

- the **entitled days** for that key,
- the **days taken** and the resulting **balance**,
- the **approval path** the answer has to follow,
- the **rule hits**: which rule produced the number, with the citation clause behind it,
- and whether the result **requires human review**.

There is a second, simpler surface: `/v1/triage` and the `triage` CLI subcommand screen a
free-text HR or policy question into a severity band for questions that carry no structured
facts. Consolidating the two, and adding a grounded cited-answer path over a governed policy
corpus, are the main open gaps.

### What is deterministic here? All of it?

Yes, all of it. The consequential output comes from
`domain/entitlement_engine.py::EntitlementEngine.compute`, which is pure stdlib, takes only frozen
inputs plus the loaded rule packs, performs no I/O, writes no audit record and holds no port. It
is replayable: the same facts and the same `as_of` produce the same worksheet, in a unit test and
in the eval oracle alike. `domain/triage_service.py` is the same shape for the free-text path.

The accrual formula is one function: nothing below `min_months_service`, then `base_days` plus
`increment_days_per_year` for each COMPLETED year of service beyond the first, capped at
`max_days`. An auditor can recompute any figure by hand.

### The tagline says "copilot" and "cited policy answers". Where does the model come in?

It does not, today. There is no generation, narration or LLM port bound in any profile, and
`adapters/local/` holds only audit, evaluation, identity, review_router and tracer. The
**citations come from the rule packs, deterministically**: each pack file carries a `source_id`
and a `source_title`, each rule carries a `citation_clause`, and `EntitlementRule.citation()`
assembles them into the `Citation` attached to every number derived from that rule. So a computed
answer is traceable to a statutory clause because the data says so, not because a model said so.

"Copilot" describes where this sits in a workforce journey (an HR business partner or an employee
asks, a system answers and escalates) rather than a claim that a model is in the path. If a model
is added later, the boundary it has to respect is written down in
[`../model-card.md`](../model-card.md): it may restate a worksheet the engine already computed and
cited; it may never produce an entitlement, a figure or a citation.

### Where does it refuse to answer?

Wherever it would have to guess. The engine returns `VerdictStatus.NEEDS_INFO` with
`entitled_days` and `balance_days` both `None` when no rule matches: an unknown jurisdiction, an
employment type nobody packed, an entitlement kind nobody packed, or a date outside every
effective window. A fail-closed verdict carries no number at all, so nothing downstream can
mistake a refusal for a computed zero. The shipped JP pack demonstrates this on purpose by
packing only a full-time rule, so a JP part-time question fails closed, and the eval scores that
as a per-market red case.

Two other refusals worth knowing: a pack carrying an unknown field refuses at LOAD rather than
being ignored, and two rules matching one key on one date refuse at MATCH time rather than the
engine silently picking the first.

### Is anything auto-approved?

Only a plainly non-consequential computed answer, and even that is audited and cited. Everything
else routes to a human:

| Situation | Severity | Approval path | Routed? |
|---|---|---|---|
| Within entitlement, not termination-linked | low | `auto_approved` | no |
| Contested balance (recorded leave exceeds the entitlement) | high | HR business partner, then payroll control | yes |
| Termination-linked or final-pay question | critical | HR business partner, payroll control, then legal | yes |
| No matching rule (`NEEDS_INFO`) | medium | HR business partner | yes |

A termination-linked question is consequential **whatever the arithmetic says**, and a critical
band demands two approvals at the console rather than one.

### What does "routed" mean, exactly?

Setting `requires_human_review` and calling `ReviewRouterPort.route` is one act, and it happens in
the same call that produced the result, on the API, the CLI and the agent tool alike. That is
dependency rule R8. The escalation goes to the `human-review-console` over the shared
`review-kit`, redacted before the wire, with the verified principal as maker and the tenant
partition carried. The offline family enqueues to the kit's outbox (deliberately not a no-op, so
a producer cannot ship R8 unwired and green), the managed family submits over S2S and REFUSES
when no console is configured, and the on-premises family raises.
`tests/unit/test_review_routing.py` asserts the routing rather than the flag.

### How is quality measured?

`eval/run_eval.py --mode smoke` runs inside `make gate` on every change, drives the REAL engine
and service with SDK-free local adapters, and scores three metrics, each against the dataset's
own INDEPENDENT oracle rather than against the engine's own answer:

- `entitlement_accuracy`: the computed balance and verdict status vs the hand-computed
  `expected_balance` and `expected_status` in `eval/datasets/golden_entitlements.jsonl`;
- `review_safety`: recall over the consequential goldens, so a case that should have escalated
  and did not is a failure;
- `pii_safety`: no raw identifier planted in a case survives into an audit record.

All three thresholds are 0.99, and `tests/unit/test_entitlement_eval.py` proves each one can go
RED per market. `--mode gate` is the promotion verdict and delegates to `model-quality-gate`.

### Which capabilities does this repo own vs integrate from the catalog?

It **owns** the entitlement engine, the rule-pack schema and loader, the triage screen, the
redaction placement, the audit chain and its anchor, and the offline eval. It **integrates**, or
still owes, the cross-cutting concerns below. Do not rebuild them in a fork.

| Concern | Owned by | H2's role today |
|---|---|---|
| Human review and maker-checker | `human-review-console` | routes every escalation to it (rule R8), fully wired in all three profiles |
| Tracing | `agent-observability` | one span per verdict, structural attributes only; the managed adapter exports OTLP to the `agent-observability` collector when `OTEL_EXPORTER_OTLP_ENDPOINT` names one |
| Immutable shared audit sink | `agent-observability` | NOT wired: the record lands in this repo's own store today |
| Promotion and model-risk gate | `model-quality-gate` | the client half is bound; registering this repo's bundle and thresholds with `model-quality-gate` is still owed |
| Agent registry, versioning, entitlements | `agent-registry` | publishes an A2A card at `/.well-known/agent-card.json`, but is NOT registered |
| Guardrail, prompt-injection defence, output filtering | `agent-guardrail-gateway` | NOT wired; there is no `GuardrailPort`. It becomes mandatory the moment untrusted text reaches a model |
| Governed RAG with citations | `enterprise-knowledge-base` | NOT wired; no retrieval port exists. This is where a grounded policy-answer path belongs |

### Where does H2 stop within the HR journey?

It answers entitlement and policy questions and escalates the consequential ones. It is not a
payroll engine and it commits nothing: no leave is booked, no payment is made, no record in a
system of record is updated. It holds no employee master data of its own, because it has no
queryable store; the facts arrive on the request. Case management and the approval workflow
itself belong to `human-review-console`. Before building anything adjacent, check the
[organization's repository index](https://github.com/portable-genai) for a system that
already owns it.

### How do I see it working?

`make demo` runs the presenter-paced walkthrough: it starts its own loopback server, narrates
each of eight steps on your terminal (never on the page), waits for you, then performs the step
against the REAL services. `make demo-selftest` is the same arc headless and unattended,
asserting every step and exiting non-zero when a claim stops being true. `make demo-static`
renders the audit-first panels to dependency-free HTML for screenshots. One CLI call does the
core of it:

```bash
hr_policy_answers assess "EMP-4021 (FICTIONAL)" SG full_time 40 --taken 3
```

Everything runs offline on synthetic, obviously fictional data, with no cloud project, no
credentials and no API key.
