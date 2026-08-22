# Compliance FAQ

For compliance, employment-governance and model-risk teams assessing this repo's posture.
Cross-references: [`../../COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle and rule map
with an adopter-owned crosswalk), [`../../SPEC.md`](../../SPEC.md),
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md), [`../practices-audit.md`](../practices-audit.md).

### Is this deciding an employee's entitlement autonomously?

Only in the plainly non-consequential case, and never for the ones that matter. A computed answer
that is within entitlement and not termination-linked returns `auto_approved`. Everything else
sets `requires_human_review` AND is routed in the same call to the **Hrz7** human-review console
under dependency rule R8: a contested (overdrawn) balance goes to the HR business partner and
payroll control, a termination-linked or final-pay question goes to those two plus legal and
carries a CRITICAL band that demands two approvals, and a question no rule matches carries no
number at all and goes to the HR business partner.

Nothing is committed by this service. No leave is booked, no payment is made, no system of record
is updated. The agent proposes and cites; a human disposes.

### How is employee personal data handled?

As personal data, at three separate boundaries, because unlike an aggregate-only service this one
really does carry an identifier stream:

1. **Before the audit write** (`domain/entitlement_service.py`, `domain/triage_service.py`): the
   detail string, including the employee reference, the months of service and the days taken, is
   passed through the shared `pii-kit` redactor before the `AuditEvent` is constructed, so a raw
   identifier never reaches the WORM record.
2. **Before the review payload leaves the process** (`adapters/_review_payload.py`): the subject,
   the summary and every citation snippet are masked, and the masked subject is reused for
   `case_ref` and `source_key` so no structured field carries a raw identifier either.
3. **Before a tool result enters a model's context** (`agent/tools.py`): the whole serialised
   structure is walked, so a field added later cannot arrive unmasked.

The API response is deliberately not redacted: it returns to an authenticated caller the facts
that caller just submitted. The rule being enforced is P-04, minimise what reaches the durable
record and the model.

### Against which jurisdiction's rows is data redacted?

Two different answers, and the difference is deliberate:

- **Inside this deployment**, `domain/pii.py` selects and ORDERS rows for the jurisdictions this
  deployment serves: `("SG", "HK", "JP", "AU")` as shipped, national-ID rows first and the
  universal email and phone rows last, so a broad pattern cannot subsume a narrower one. A fork
  sets this list to its own footprint.
- **On the outbound review**, `adapters/_review_payload.py` ignores that selection and scrubs
  against EVERY jurisdiction's national-ID rows plus the universal ones, because the Hrz7 console
  is a shared sink and a case filed in one market can still quote another market's identifier.

Note this list is independent of the three jurisdictions the rule packs cover (SG, AU, JP). The
packs decide what can be computed; the PII list decides what is recognised as an identifier.

Alignment is to PDPA-class regimes plus MAS TRM, APRA CPS 234 and CPS 230 and HKMA, as stated at
the top of `COMPLIANCE.md`. The mapping from those to a specific regulation, and the judgement
that a control is SUFFICIENT for it, is explicitly adopter-owned: it depends on your risk
appetite, your regulator and your existing control library, and this repo does not make that
claim on your behalf.

### Can the redaction control be shown to work, rather than asserted?

Yes. `pii_safety` is scored two ways in the eval gate, by a pack scan using the same rows the
redactor masks with and by an INDEPENDENT planted-literal oracle that fires even if a pattern row
is broken, and `tests/unit/test_not_falsely_green.py` proves the metric can actually go red. A
safety metric that cannot fail is evidence of nothing.

### How is the work auditable and reproducible?

Every verdict writes an already-redacted `AuditEvent` carrying the action, the verified actor, the
decision, the severity and the citation set. Every figure carries a `Citation` back to the rule
that produced it, and that rule's `source_id`, `source_title` and `citation_clause` name the
statutory clause. The engine is pure and replayable, so an auditor can recompute any balance from
the same facts and the same `as_of` date without the service running.

The offline trail is append-only and hash-chained AND externally anchored: the chain detects an
edit, an interior deletion or a reorder, and `audit_anchor_path` (`POLICYHR_AUDIT_ANCHOR`) closes
the one gap the chain cannot, a truncated tail. `tests/unit/test_audit_anchor.py` proves the
detection and proves the control case goes undetected without an anchor. Under `gcp` the sink is
a locked Cloud Logging bucket with a 180-day retention floor and CMEK. Operating rules, including
the fact that a store and anchor disagreement REFUSES the next append rather than re-anchoring,
are in [`../runbook.md`](../runbook.md).

### An answer changes when a policy changes. How is that handled?

By date, not by "latest wins". Each rule carries an `effective_from` and `effective_to` window,
and each request carries an `as_of` date the verdict is computed AS OF, so a replay a year later
picks the rule that was in force rather than today's. Each pack carries a `version`. Deciding what
happens to verdicts already issued when a pack changes is an adoption decision, and it is on the
checklist in [`../ADOPTING.md`](../ADOPTING.md).

### What is the model-risk story?

Unusually short, because **there is no model in the request path today**. No generation,
narration or LLM port is bound in any profile, so there is no prompt, no temperature, no
hallucination surface and no drift on a decision. Every consequential output is deterministic
stdlib. [`../model-card.md`](../model-card.md) records that plainly, together with the boundary a
model would have to respect and the controls that must exist before one is introduced. Read it
instead of asking for a model card that describes a model that is not there.

What model risk there is sits in the POLICY rather than the model: the packs encode statutory
entitlements, and a wrong number is a payroll error rather than a bad suggestion. That is why the
employment-law review is an explicit adoption step and why second-line review of the deterministic
policy in `domain/` is listed as adopter-owned in `COMPLIANCE.md`.

The quality evidence is the offline gate: three metrics against an independent oracle, each
proven able to go red, running on every change. Promotion itself is **Hrz4**'s decision, not this
repo's, and the local evaluation adapter REFUSES to promote rather than certifying itself.

### Is data residency enforced, or only documented?

Enforced at deploy time. `infra/terraform/variables.tf` validates `var.region` against
`var.allowed_regions` at plan time, so an unvetted region fails at `terraform plan` rather than
putting regulated data out of jurisdiction. `org_policy.tf` applies a `gcp.resourceLocations` Org
Policy pinned to that region's location group and also disables service-account key creation and
requires uniform bucket-level access. `kms.tf` creates a REGIONAL CMEK key ring with 90-day
rotation and binds each service agent separately, because CMEK does not cascade. `logging_worm.tf`
puts the locked WORM bucket in the same region. `vpc_sc.tf` stands up a VPC-SC perimeter, dry-run
first.

Two honest qualifications. The org-policy and VPC-SC layers are gated on `var.enable_org_policies`
and `var.enable_vpc_sc` so a project-scoped evaluation deploy can skip them, which is NOT a
compliant production posture and is labelled as such in the file. And the assertions that hold all
of this true live in `production_edge.tftest.hcl`, which runs under `terraform test` with mock
providers rather than inside `make gate`, so the offline gate does not guard residency by itself.
See the P-03 row in [`../../COMPLIANCE.md`](../../COMPLIANCE.md).

### What is NOT covered yet? Be specific.

`COMPLIANCE.md` carries an explicit `TODO (repo owner)` on every row that is not finished, and
`practices-audit.md` records the per-check verdict. The substantive open items:

- **P-05 grounding and R3**: no retrieval port and no governed corpus, so there is nothing to
  ground yet. This is Hrz2's boundary.
- **R1**: redaction is in place, but no `GuardrailPort` is bound to the Hrz1 gateway for
  injection defence and output filtering. It becomes mandatory the moment untrusted text reaches
  a model.
- **R2**: tracing reaches the Hrz5 collector when configured, but the immutable audit record
  still lands in this repo's own store rather than the shared sink.
- **R4**: the A2A card is published but not registered with Hrz3.
- **R5 and P-08**: the gate client exists; this repo's metric bundle and thresholds are not yet
  registered with Hrz4, so gate mode has no authority to ask.
- **P-10 resilience**: only the review path degrades correctly today (the outbox retains an
  escalation the console could not take). Timeouts, circuit breakers, a documented kill switch
  per outbound dependency and the CPS 230 recovery objectives are still owed.
- **R6**: the Rsk3 intake validation reference is not recorded here yet.
- **Tenant isolation**: the tenant partition is carried on every outbound review, but there is no
  queryable store yet, so object-level authorisation derived from data tags is recorded as
  not-yet-applicable rather than implemented.
- **P-01**: the VPC-SC perimeter ships, but the Interconnect attachment and the no-public-egress
  network posture do not.

### Can we run it against real employee data today?

Not without your own legal, privacy, security and employment-law sign-off. Every fixture, every
demo party and the three rule packs are obviously fictional or explicitly ILLUSTRATIVE and
SYNTHETIC, marked so in their own file headers, and the packs are simplified for an offline demo.
The adoption checklist in [`../ADOPTING.md`](../ADOPTING.md) lists what must precede any live use:
replace every pack with your own reviewed policy, own the approval chains and the accrual formula,
replace the fixtures, rebuild the eval golden set so it measures your packs, wire your IdP, set
your residency region, and complete the employment-law review per jurisdiction with a named owner
for each pack version.
