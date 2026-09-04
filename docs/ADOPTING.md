# Adopting this repo as your base

This repository (H2, the Policy and HR Copilot) is a **common base** that a bank or other
regulated institution forks to build its own **HR entitlement and policy-answer service**: a
deterministic engine that computes a leave balance and an approval path from versioned rule
packs, cites the clause behind every number, and routes anything consequential to a human
instead of auto-answering it. It ships a reusable hexagonal core (a pure-stdlib domain, typed
ports, three swappable adapter profiles, a green offline gate) plus a fully worked annual-leave
vertical over three jurisdictions that you keep, retune, or replace with your own policy.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the layout, the port table and the
> request pipeline), [`CONTRIBUTING.md`](../CONTRIBUTING.md) (the file-by-file touch list for a
> new adapter and for a new port), [`COMPLIANCE.md`](../COMPLIANCE.md) (which controls this repo
> already holds and which it still owes), the [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The domain is split physically, and the dependency direction is enforced (practices-audit check
A7). [`domain/kernel.py`](../src/hr_policy_answers/domain/kernel.py) holds the vertical-neutral
machinery and imports nothing from this vertical;
[`domain/models.py`](../src/hr_policy_answers/domain/models.py) holds this vertical's artifacts
and imports `kernel`, never the reverse. A fork building a different HR surface rewrites
`models.py` and leaves `kernel.py` alone.

| Layer | Where | For your institution |
|---|---|---|
| **Kernel** (vertical-neutral) | `domain/kernel.py`: `Citation`, `Severity`, `Decision`, `VerdictStatus`, `AuditEvent`, the `ReviewableResult` protocol and the single `utcnow` clock. Plus every port in `ports/`, the DI wiring in `config.py`, the shared redacted review conversion in `adapters/_review_payload.py`, and the three-state env reader in `envread.py` | keep untouched |
| **Policy** (your numbers) | The rule packs under [`config/packs/`](../config/packs), the approval chains `_AUTO_APPROVED` / `_CONTESTED_CHAIN` / `_TERMINATION_CHAIN` / `_NEEDS_INFO_CHAIN` in `domain/entitlement_engine.py`, the severity keyword bands in `domain/triage_service.py`, the jurisdiction list in `domain/pii.py`, and the thresholds in `eval/run_eval.py` | change deliberately (section 4) |
| **Vertical** (the artifacts) | `domain/models.py` (`EmployeeFacts`, `EntitlementRequest`, `EntitlementResult`, `RuleHit`, `TriageInput`, `TriageResult`), the accrual formula `_entitled_days` in `domain/entitlement_engine.py`, the pack schema in `domain/packs.py`, the fixtures, the eval golden set, and the UI views | rewrite for your policy |

If your product is another *deterministic HR or workforce* service (overtime, notice periods,
severance, allowances, working-time limits), most of this transfers directly: the packs-as-data
convention, the fail-closed `NEEDS_INFO` verdict, the citation on every figure, the R8 routing
and the eval gate are all entitlement-shaped rather than leave-shaped. You replace the rules and
the accrual formula, and retune the approval chains.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly.

- **Upstream-owned** (take our changes): `domain/kernel.py`, `domain/packs.py` (the loader and
  its strict schema, not the packs themselves), `ports/`, `config.py`, `tests/contract/`, the
  eval harness mechanics in `eval/run_eval.py`, the CI workflows, and `adapters/_review_payload.py`.
- **Adopter-owned** (yours; expect to edit): **the rule packs**, the values in
  `config/settings.yaml`, `adapters/onprem/*`, the fixtures in `tests/fixtures/sample_cases.py`,
  the golden sets in `eval/datasets/`, UI theming, and the jurisdiction rows in `COMPLIANCE.md`.

### The rule packs are THE adopter-owned surface here

Every bank's leave, benefits and conduct policy differs, so this repo puts the policy in data
rather than in code. A pack is one YAML file under `config/packs/<jurisdiction>/`, loaded by
[`domain/packs.py`](../src/hr_policy_answers/domain/packs.py) from every `*.yaml` beneath
`config/packs` (recursively) into one immutable `PackSet`. Three ship today, all marked
ILLUSTRATIVE and SYNTHETIC in their own headers:
[`config/packs/sg/annual-leave.yaml`](../config/packs/sg/annual-leave.yaml),
[`config/packs/au/annual-leave.yaml`](../config/packs/au/annual-leave.yaml) and
[`config/packs/jp/annual-leave.yaml`](../config/packs/jp/annual-leave.yaml).

A pack file carries exactly five top-level fields: `jurisdiction`, `version`, `source_id`,
`source_title` and a non-empty `rules` list. Each rule carries `rule_id`, `entitlement`,
`employment_type`, `min_months_service`, `base_days`, `increment_days_per_year`, `max_days` and
`citation_clause` as required fields, plus the optional `effective_from` / `effective_to` window.
`source_id` plus `source_title` plus `citation_clause` are what become the `Citation` on every
number the engine derives from that rule, which is the whole reason a computed figure is
traceable to a clause.

The loader is deliberately strict, and the strictness is the point of adopting it rather than
working around it:

- an **unknown** field on a rule or on the pack refuses at load, because a pack carrying a field
  the engine does not read would be a policy nobody reviewed;
- a **missing** required field, a negative day count, a non-integer `min_months_service`, a
  `max_days` below `base_days` or a non-ISO effective date all refuse;
- a **duplicate** `rule_id` anywhere in the tree refuses, so a citation is never ambiguous;
- **two rules matching one key** on one date refuse at match time rather than silently picking
  the first;
- a named packs directory that does not exist, or one holding no rules at all, refuses, because
  computing on an empty rule set looks exactly like computing correctly.

So a fork's real work here is to replace these files with your own reviewed packs, keeping the
schema. Adding a jurisdiction, an entitlement kind or an employment type is a new file or a new
rule, never an engine edit. A key nobody packed a rule for produces no number at all: the engine
returns `VerdictStatus.NEEDS_INFO`, carries `entitled_days` and `balance_days` as `None`, and
routes to a human. The shipped JP pack demonstrates that on purpose by packing only a full-time
rule.

Track upstream via git tags, and rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

[`scripts/rename_fork.py`](../scripts/rename_fork.py) rewrites five identifiers across the whole
tree in one simultaneous pass: the python package (`hr_policy_answers`), the console-script name
(also `hr_policy_answers`, since `[project.scripts]` maps the two to the same token here), the
`POLICYHR` environment-variable stem, the Terraform `name_prefix` stem (`h2-svc`) and the
distribution / git id (`hr-policy-answers`). It prints its plan and writes nothing without
`--yes`.

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_hr_copilot --cli acme-hr \
    --env-prefix ACME --resource acme-hr --dry-run

# Apply, sweeping Markdown prose as well:
python scripts/rename_fork.py --package acme_hr_copilot --cli acme-hr \
    --env-prefix ACME --resource acme-hr --include-docs --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
make docs-check
```

`--dist` defaults to the package name with hyphens (`acme-hr-copilot` above); pass it explicitly
if your git id differs from the hyphenated package name.
Markdown is skipped unless you pass `--include-docs`, so you can rebrand the code first and read
the prose diff separately. The `--resource` value is validated here against the same
`^[a-z][a-z0-9-]{2,18}$` pattern the Terraform `name_prefix` variable validates at plan time, so
a bad stem fails in a second rather than in a plan.

The script deliberately does NOT touch the human decisions below.

## 4. The human decisions (the script cannot make these)

1. **Region and residency.** The region is chosen once and shared by the runtime and Terraform.
   Set `GCP_REGION` (it feeds `region` in `config/settings.yaml`, defaulting to
   `asia-southeast1`) and, in your tfvars, BOTH `region` and `allowed_regions`, which is the
   residency allowlist `region` is validated against at plan time. Add `additional_resource_locations`
   only if your own policy evaluation needs the location-less global edge objects. See
   [`runbook.md`](runbook.md).
2. **Identity and your IdP.** This repo owns no login flow. `local` seeds dev personas and
   authenticates nobody, `gcp` verifies the IAP-injected assertion against `POLICYHR_IAP_AUDIENCE`
   (unset or emptied refuses every caller rather than verifying without an audience), and
   `onprem` raises. To wire your own IdP, implement the `onprem` identity adapter and rebind the
   `identity` port in `config/settings.yaml`; the adapter must declare `VERIFIED` /
   `CLIENT_ASSERTED` / `UNIMPLEMENTED` on the class, because the loopback exposure guard reads
   that declaration and nothing else. `CONTRIBUTING.md` row 2c lists the four things a `VERIFIED`
   claim has to earn.
3. **The entitlement rules and the accrual numbers.** These are the consequential figures, and
   the shipped ones are a reference, not your policy. The packs currently encode: SG full-time
   7 base days after 3 months of service, plus 1 day for each completed year beyond the first,
   capped at 14 (Employment Act 1968 Part IV, s43(1)), with a pro-rated part-time rule at 4 and
   8; AU 20 flat days from day one with no increment, and 10 pro-rated part-time (Fair Work Act
   2009 NES, s87(1)(a)); JP 10 base days after 6 months plus 1 per completed year to a cap of 20
   (Labor Standards Act art.39(1)), full-time only. The accrual formula itself (`_entitled_days`:
   nothing below `min_months_service`, then `base_days` plus `increment_days_per_year` for each
   completed year beyond the first, capped at `max_days`) is a simplification you should confirm
   against your own scheme. Own the approval chains too: termination-linked questions currently
   route to `hr_business_partner`, `payroll_control` and `legal`, a contested overdrawn balance
   to the first two, and a `NEEDS_INFO` verdict to the HR business partner. The severity keyword
   bands on the free-text triage path are still module constants in `domain/triage_service.py`
   rather than a `policy:` settings block; that is the open B4 item in
   [`practices-audit.md`](practices-audit.md), and lifting them out is a good first fork commit.
4. **Fixtures and demo data.** Everything shipped is obviously fictional: `tests/fixtures/sample_cases.py`,
   the demo arc in `scripts/demo.py`, and the `.example` domains throughout. The one national id
   in the fixtures exists solely so a redaction check has an independent literal to look for.
   Replace them with your own synthetic data, and keep them synthetic. Also set the jurisdictions
   your redactor selects rows for: `JURISDICTIONS` in `domain/pii.py` currently lists SG, HK, JP
   and AU, and the order matters (national-ID rows first, universal email and phone rows last).
5. **The eval golden set.** [`eval/datasets/golden_entitlements.jsonl`](../eval/datasets/golden_entitlements.jsonl)
   is the entitlement oracle and `golden_cases.jsonl` the triage one. The `expected_status`,
   `expected_balance` and `expected_review` fields are hand-computed INDEPENDENTLY of the engine,
   which is the only reason `entitlement_accuracy` can go red. Rebuild them for your packs: a
   fork inherits a green gate that measures the WRONG policy until you do. The three thresholds
   (`entitlement_accuracy`, `review_safety`, `pii_safety`, all at 0.99) are yours to justify.
6. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001,
   healthcheck on `/healthz`) and `infra/terraform/` before you expose anything. The stack
   defaults to the full sovereign posture: `enable_org_policies`, `enable_vpc_sc` and
   `worm_locked` are all true, `vpc_sc_enforce` starts false so you watch dry-run violations
   first, and `production_edge_enabled` is false so the serving edge is opt-in. The WORM lock is
   irreversible; confirm `retention_days` before the first apply.
7. **The employment-law review.** This is the one an entitlement engine cannot skip. Every number
   this service computes is a statutory or contractual entitlement, and getting it wrong is a
   payroll error and a conduct issue rather than a bad suggestion. Before any live use, have
   employment counsel review each pack against the jurisdiction it claims, record who owns each
   pack `version` and when it is re-reviewed, and decide what happens to verdicts already issued
   when a pack changes (the `as_of` field and the `effective_from` / `effective_to` window exist
   so a replay a year later picks the rule that was in force, not today's). Second-line review of
   the deterministic policy in `domain/` is already listed as adopter-owned in
   [`COMPLIANCE.md`](../COMPLIANCE.md); this is the specific form it takes here.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable systems. Several concerns it touches belong
to sibling platform services: integrate them rather than rebuilding them. The honest state of
each wire today is below; [`COMPLIANCE.md`](../COMPLIANCE.md) carries the same picture as R1 to
R8 rows with a `TODO (repo owner)` on every one that is not finished.

| Concern | Owner | Wired here today? |
|---|---|---|
| Human review and maker-checker (rule R8) | `human-review-console` | **Yes, fully.** `ReviewRouterPort` with an adapter in all three profiles, built on the shared `review-kit`. The API, the CLI and the agent tool all route in the same call that produced the result. Point `HUMAN_REVIEW_URL` at your console and set the outbound `HUMAN_REVIEW_S2S_TOKEN` / `HUMAN_REVIEW_S2S_SIGNING_KEY`; the managed router REFUSES rather than swallowing an escalation when no console is configured. Do not re-implement the console. |
| Tracing (part of rule R2) | `agent-observability` | **Partly.** `ObservabilityTracerPort` is bound in all three profiles, and the managed adapter exports OTLP to the `agent-observability` collector when `OTEL_EXPORTER_OTLP_ENDPOINT` names one, straight to Cloud Trace when it does not. Span attributes are structural only, never case text or employee facts. |
| Immutable audit sink (the other part of R2) | `agent-observability` | **No.** The audit record lands in this repo's own store: a hash-chained, externally anchored log offline, a locked Cloud Logging bucket under `gcp`. Binding it to the shared `agent-observability` sink is still open. |
| Promotion and model-risk gate | `model-quality-gate` | **Client half only.** `EvaluationGatePort` is bound; `eval/run_eval.py --mode gate` asks `model-quality-gate` through `POLICYHR_QUALITY_URL` and refuses to run off the managed profile, and the local adapter refuses to promote at all. Registering this repo's metric bundle and thresholds with `model-quality-gate` is yours to do, and until you do, gate mode has no authority to ask. |
| Agent registry, versioning, entitlements | `agent-registry` | **Card only.** The A2A discovery card is served at `/.well-known/agent-card.json` and built from the same tool table the runtime binds. It is NOT registered with `agent-registry`, and the agent's identity and entitlements are not taken from it yet. |
| Runtime guardrail, prompt-injection defence, output filtering | `agent-guardrail-gateway` | **No.** There is no `GuardrailPort` in `ports/`. Redaction before every boundary is in place (`domain/pii.py` over the shared `pii-kit`), but injection defence and output screening are not, and they become mandatory the moment untrusted text reaches a model. |
| Governed RAG over a policy corpus | `enterprise-knowledge-base` | **No.** There is no retrieval port. Citations today come from the rule packs, deterministically. A grounded cited-answer path over a governed corpus is exactly where `enterprise-knowledge-base` belongs, together with the rule that empty retrieval is a hard error rather than an ungrounded answer. |

The short version: `human-review-console` is done, `agent-observability`'s tracing half is done, `model-quality-gate` and `agent-registry` are half-done and
waiting on registration rather than on code, and `agent-guardrail-gateway` and `enterprise-knowledge-base` are genuinely absent. Do not build
any of the six inside your fork.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` and `make docs-check` green.
- [ ] Set the region in `GCP_REGION` and in BOTH Terraform `region` and `allowed_regions`.
- [ ] Wired your IdP (rebound the `identity` port, or configured IAP and set `POLICYHR_IAP_AUDIENCE`).
- [ ] Replaced every rule pack under `config/packs/` with your own reviewed policy, keeping the schema.
- [ ] Owned the approval chains, the accrual formula and the triage severity bands with your HR and compliance functions.
- [ ] Replaced every synthetic fixture and the demo data.
- [ ] Rebuilt the eval golden sets so they measure YOUR packs, and justified the three thresholds.
- [ ] Reviewed the deploy posture (Dockerfile, the Terraform toggles, `retention_days` before the WORM lock).
- [ ] Completed the employment-law review per jurisdiction and recorded who owns each pack version.
- [ ] Pointed `HUMAN_REVIEW_URL` at your `human-review-console` and decided which other siblings you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
