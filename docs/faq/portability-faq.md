# Portability FAQ

For architecture, cloud and exit-planning reviewers who want to know how real the "no lock-in"
claim is, and how an off-cloud or sovereign exit would actually work.

## What is the no-lock-in claim, concretely?

`src/hr_policy_answers/domain/` holds the consequential logic and speaks to no infrastructure: no
web framework, no cloud SDK, no HTTP client. Every boundary is a `@runtime_checkable` Protocol in
`ports/`, and which implementation binds is one setting. Swapping the whole stack is a
configuration change in `config/settings.yaml`, not a code edit.

There is **one recorded exception** to the stdlib-only phrasing, and it is a named, dated debt
rather than a loophole: `domain/packs.py` imports `yaml` to parse the rule packs. It is listed in
`tests/unit/test_core_purity.py::EXEMPT_IMPORTS` with the reason "policy packs are parsed inside
the core; extraction to the config boundary is queued". The scan fails on any core import that is
not on that list, and a companion test deletes an exemption that has outlived the import it
covers, so the row cannot quietly grow to cover something else. `yaml` is a pure-python parser
with no cloud or network dependency, so it does not weaken the exit story, but the honest
statement is "stdlib plus the stdlib-only commons, plus one exempted YAML parser being moved to
the config boundary", not "pure stdlib".

## What are the profiles?

`POLICYHR_PROFILE` selects the adapter family for every port at once:

- **`local`** is a real, working, SDK-free offline stack: seeded dev personas, a hash-chained and
  externally anchored WORM audit log, an inspectable review outbox, a no-op tracer and an offline
  eval scorer. This is the dev, test and CI default and the working proof that the domain runs
  entirely off-cloud.
- **`gcp`** is the managed stack: Cloud Logging WORM, IAP identity, Cloud Trace or OTLP to the
  `agent-observability` collector, the `human-review-console` over S2S, and the `model-quality-gate` promotion gate. Every cloud import is
  lazy and lives inside the method, so the other two profiles import with no cloud SDK installed.
  That is proved by BLOCKING the import in a fresh interpreter (`tests/contract/_sdk_free_probe.py`),
  not by the SDK happening to be absent from the machine.
- **`onprem`** is the fail-fast exit placeholder. Every adapter satisfies the same Protocol and
  then RAISES, naming the migration target. A placeholder that returned successfully would be a
  false portability claim; the review router in particular refuses, because one that silently
  returned would convert every consequential result into an unreviewed one.

The read is three-state and resolves once, at import. UNSET is no choice (the offline adapters
still bind, but the seeded personas are refused and every relaxation is withdrawn), SET-AND-EMPTY
raises, and SET-AND-UNKNOWN raises, including the merely mis-capitalised `Local` or `GCP`. Both
raises kill the process before it can serve a request.

## Which ports are there?

Four port modules and five bound ports, and no more:

| Port module | Port name in `PORT_PROTOCOLS` | Boundary |
|---|---|---|
| `ports/audit.py` | `audit` | the WORM audit sink |
| `ports/identity.py` | `identity` | the verified principal (the Protocol itself comes from the commons; this module adds what an adapter DECLARES about end-user authentication) |
| `ports/review_router.py` | `review_router` | rule R8 routing to `human-review-console` |
| `ports/observability.py` | `tracer` and `evaluation` | spans, and the promotion authority |

That is the whole list. There is no generation, narration, LLM or retrieval port, in any profile.
See [`../model-card.md`](../model-card.md).

## Is the port map able to drift?

No. A port lives in five places at once (`ports/__init__.py`'s `PORT_PROTOCOLS`,
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`), and
`tests/contract/test_port_parity.py::test_every_home_of_the_port_set_agrees_exactly` asserts set
equality across all five. Four of the five can be satisfied while the fifth is missing, and the
result would be a port running with zero enforcement and a green build, which is why the check is
set equality rather than a subset. `tests/unit/test_settings_file.py` separately holds the two
binding tables equal, so there is no second place a binding can hide.

## Is the portability claim tested, or just asserted?

Tested, and bounded. `make portability` runs `scripts/portability_demo.py`, which prints a pass
or fail per named check and exits non-zero on any failure: port-map completeness, adapter
construction and Protocol conformance, the offline family ANSWERING a canonical call rather than
merely not raising, the exit family REFUSING, in-place rewrite detection, anchored truncation
detection with its control case, the JSONL export and foreign reload, and the no-cloud-SDK check.

It also prints what it does NOT prove: that an on-premises deployment exists or that anyone has
run one, infrastructure or network portability, and anything at all about the managed profile's
live behaviour, which needs a cloud project and lives in `tests/integration/`. Bounding the claim
is the point.

## How would a sovereign or on-premises exit actually go?

The `onprem` family is the scaffold: each refusal marks a seam where the client supplies its own
component (their IdP, their audit store, their review and approval queue, their trace backend,
their quality service). The domain does not change, so the exit is an adapter exercise rather
than a rewrite. The step-by-step is [`../onprem-migration.md`](../onprem-migration.md);
[`../runbook.md`](../runbook.md) covers operating it.

The rule packs travel with you unchanged: they are plain YAML files under `config/packs/`, not a
managed resource, so the policy itself has no exit cost at all.

## Can the data be exported in an open format?

Yes. The audit trail exports to and restores from JSON Lines, carrying its chain anchor with it,
and a truncated export is refused on reload. The portability check proves the round trip into a
FOREIGN store with the chain intact, so the exit for the evidence is a file copy rather than a
migration project.

## How is residency handled?

The region is chosen once and shared. `config/settings.yaml` carries it (`GCP_REGION`, default
`asia-southeast1`), `/healthz` reports it and the agent card prints it, so a drifting deployment
is visible. At deploy time `infra/terraform/variables.tf` validates `var.region` against
`var.allowed_regions` at plan time, `org_policy.tf` applies a `gcp.resourceLocations` allowlist
pinned to that region's location group, `kms.tf` creates a REGIONAL CMEK key ring (never a
multi-region one), `logging_worm.tf` puts the locked audit bucket in the same region, and
`vpc_sc.tf` stands up a dry-run-first VPC-SC perimeter. `production_edge.tftest.hcl` asserts
those defaults with `terraform test` and mock providers, which is plan-only and needs no
credentials, but note it is NOT part of `make gate`: the offline gate is python-only. See the
P-03 row in [`../../COMPLIANCE.md`](../../COMPLIANCE.md).

## What is honestly NOT portable, or not proved?

- **The managed profile's live behaviour.** Nothing offline can prove it; that is what
  `tests/integration/` is for, and each of those tests skips rather than passes when its
  configuration is absent.
- **The Interconnect attachment and the no-public-egress network posture.** The VPC-SC perimeter
  ships; the private-connectivity half of P-01 does not. VPC-SC governs access to Google APIs
  across perimeters, not arbitrary internet egress, and the outbound R8 call to the `human-review-console`
  is ordinary HTTPS to a non-Google host, so it is a firewall and Cloud NAT concern you still own.
- **Tamper evidence beyond what the offline sink can prove.** Production non-rewritability is the
  locked bucket's job, or `agent-observability`'s.
- **Anything about a model.** There is no model to be portable about. See
  [`../model-card.md`](../model-card.md).
