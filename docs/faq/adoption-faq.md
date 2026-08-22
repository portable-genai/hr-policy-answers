# Adoption FAQ

For an engineering lead forking this repo as their institution's HR entitlement base. The
step-by-step is [`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

[`../../scripts/rename_fork.py`](../../scripts/rename_fork.py) rewrites five identifiers in one
simultaneous pass: the python package (`hr_policy_answers`), the console-script name (also
`hr_policy_answers`, because `[project.scripts]` maps the two to the same token here), the
`POLICYHR` env-var stem, the Terraform `name_prefix` stem (`h2-svc`) and the distribution and git
id (`hr-policy-answers`). Preview with `--dry-run`, apply with `--yes`, add `--include-docs`
to sweep Markdown prose. Then recreate the venv (the distribution name changed), `make install`,
and run `make gate` and `make docs-check`.

The pass is simultaneous rather than sequential on purpose: a sequential search and replace would
rename the console script twice, since upstream it IS the package name. The script does the
mechanical rename; the human decisions (region, IdP, the rule packs, fixtures, the eval golden
set, the employment-law review) are the checklist in `ADOPTING.md`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream by git tag. The repo declares a core-vs-adopter-owned boundary
([`../ADOPTING.md`](../ADOPTING.md) section 2): upstream owns `domain/kernel.py`, the pack LOADER
and its schema, `ports/`, `config.py`, `tests/contract/`, the eval harness mechanics and CI; you
own the packs themselves, the settings values, `adapters/onprem/*`, the fixtures, the golden sets
and the jurisdiction rows in `COMPLIANCE.md`. Rebase your adopter-owned changes onto each release
rather than merging `main` continuously, so conflicts stay in the files you were told to expect.

Releases are tracked by git tag and the `pyproject.toml` version. The practice that would require
a hand-maintained release narrative is retired upstream: a tag and a version bump already state
what a narrative would restate, and the two drift the moment anyone forgets one of them.

### Is there a real kernel module I keep untouched?

Yes, unlike some siblings. `domain/kernel.py` holds the vertical-neutral machinery (`Citation`,
`Severity`, `Decision`, `VerdictStatus`, `AuditEvent`, the `ReviewableResult` protocol, the single
`utcnow` clock) and imports nothing from this vertical; `domain/models.py` holds this vertical's
artifacts and imports `kernel`, never the reverse. Practices-audit check A7 records the split as
a PASS. A fork building a different HR surface rewrites `models.py` and leaves `kernel.py` alone.

### How do I change the policy without touching the engine?

Edit the rule packs. A pack is a YAML file under `config/packs/<jurisdiction>/`, loaded
recursively by `domain/packs.py` into one immutable `PackSet`. Adding a jurisdiction, an
entitlement kind or an employment type is a new file or a new rule, never an engine edit.

The loader is strict on purpose, and it is worth understanding before you fight it: an unknown
field refuses at load (a pack carrying a field the engine does not read would be a policy nobody
reviewed), a missing required field refuses, a negative day count or a `max_days` below
`base_days` refuses, a duplicate `rule_id` anywhere in the tree refuses so a citation is never
ambiguous, and two rules matching one key on one date refuse at match time rather than the engine
picking one. A named packs directory that does not exist raises rather than yielding an empty
rule set.

What you cannot change in the packs is the **accrual formula**: `base_days` once
`min_months_service` is passed, plus `increment_days_per_year` for each completed year beyond the
first, capped at `max_days`. A scheme that does not fit that shape needs an engine change, and
that is a deliberate constraint rather than an oversight, because a pack format that could
express arbitrary arithmetic would be code with a YAML syntax.

### Which numbers are still hard-coded, honestly?

Two sets. The **approval chains** (`_AUTO_APPROVED`, `_CONTESTED_CHAIN`, `_TERMINATION_CHAIN`,
`_NEEDS_INFO_CHAIN`) are module constants in `domain/entitlement_engine.py`, and the **triage
severity keyword bands** are module constants in `domain/triage_service.py`. The second of those
is the open **B4** item in [`../practices-audit.md`](../practices-audit.md): lift them into a
frozen policy dataclass with a `from_policy(...)` constructor and a `policy:` block in
`config/settings.yaml`, so a bank sets its own values as configuration. If your compliance
function must own those as config rather than code, plan that small addition as part of adoption.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and the contract suite enforces it, because four of the five homes
can be satisfied while the fifth is missing and the result is a port with zero enforcement and a
green build. The five: the `@runtime_checkable` Protocol under `ports/`, the `PORT_PROTOCOLS`
entry in `ports/__init__.py`, an entry in `config.DEFAULT_BINDINGS` plus a `Container`
`cached_property` that asserts the Protocol, the same three bindings in `config/settings.yaml`,
and a `PortCase` in `tests/contract/canonical.py`. Then three adapters: `local` that WORKS
offline, `gcp` with its SDK import inside the method, and `onprem` that RAISES a subclass
carrying a status and a reason. `tests/contract/test_port_parity.py` asserts set equality across
all five homes. The full file-by-file table is in [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add a new deterministic sub-service?

Same shape, with two rules that are not negotiable: the consequential decision stays pure stdlib
and replayable (a model may narrate it, never produce it), and every consequential result it
produces escalates through `ReviewRouterPort` rather than terminating in a boolean. Then wire it
into the API, the CLI and the agent tools together: a capability on one surface out of three
behaves differently depending on how it is called.

### Will the demo rot after I diverge?

It is guarded from inside the gate. A demo step lives in exactly two places, `demo.STEPS` and
`walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two sets equal, so a claim
the demo narrates but nobody verifies cannot exist. The same module drives the whole arc against
the real adapters inside `make gate`, and `make demo-selftest` runs the presenter walkthrough
headless in its own required workflow. Put the numbers a panel shows in the step's `facts` dict
as well as in the rendered rows: a check that parses prose breaks on a wording change.

`tests/unit/test_demo_surface.py` also fails the gate if a `scripts/*.py` file is not listed in
`scripts/README.md`, so adding a script means adding a row.

### What will fail the gate that I might not expect?

- **Any two-state environment read that ships.** `tests/unit/test_three_state_env_reads.py` walks
  the AST of `src/`, `scripts/` and `eval/`; `ui/tests/three-state-env-reads.test.mjs` scans every
  shipped `.mjs`, `.ts` and `.tsx`. Unset, emptied and set are three states, and an emptied value
  never inherits the unset default.
- **A second module re-deriving the profile.** Only `config.py` may read `POLICYHR_PROFILE`;
  `tests/unit/test_profile_single_source.py` fails the build otherwise, because a permissive
  default comes back one module at a time.
- **An em-dash or en-dash in any shipped `.md` or `.html`,** an unclosed code fence, or a relative
  link that resolves to nothing. `scripts/check_docs_links.py` runs in `make docs-check` and the
  same functions run in the offline gate via `tests/unit/test_docs_links.py`.
- **A `ui/` half-decision.** `ui/`, its npm dependabot ecosystem and its CI job are present
  together or absent together; `make drop-ui` is the one step that keeps them consistent, and
  `tests/unit/test_ui_surface.py` fails until they agree in both directions.
- **A new import in `domain/`.** `tests/unit/test_core_purity.py` fails on any core import that is
  not stdlib, not an allowed commons kit, and not on the written `EXEMPT_IMPORTS` list. There is
  exactly one row there today (`domain/packs.py` importing `yaml`), and a companion test deletes
  a row that has outlived the import it covers.

### Does CI run for my fork out of the box?

The offline gate does, because it is credential-free by construction: no cloud SDK, no project,
no network, and the workflow references no `secrets.`. Anything needing a live service lives in
`tests/integration/`, marked so `pytest -m 'not integration'` deselects it, and
`tests/unit/test_test_layout.py` fails the build if such a module is not marked. You add secrets
only when you wire the `gcp` profile. Note the eval gate measures the REFERENCE packs and golden
set until you rebuild them, which is an explicit adoption step rather than a silent pass.
