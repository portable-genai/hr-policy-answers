# Security FAQ

For an AppSec reviewer sizing up this repo. It explains what the attack surface is, what is
deliberately out of scope (and why that is honest rather than a gap), and where the evidence
lives.

## What does this system actually process?

Employee facts and free-text HR questions. The entitlement path takes structured facts
(`EmployeeFacts`: an opaque employee reference, jurisdiction, employment type, completed months
of service, leave days already taken, and whether the question is tied to a termination) and
returns a leave worksheet. The triage path takes a subject and a free-text case description and
returns a severity band.

Treat all of that as **employee personal data**. Unlike an aggregate-only service, this one has a
real identifier stream, which is why redaction is not optional here and why it happens at three
separate boundaries rather than once.

## Where exactly is data redacted, and where is it not?

Three points, all before something leaves the process, all using the shared `pii-kit`:

1. **Before the audit write.** `domain/entitlement_service.py` and `domain/triage_service.py`
   both build the detail string and pass it through `redact(...)` before constructing the
   `AuditEvent`, so a raw identifier never reaches the WORM record. The rows come from
   `domain/pii.py`, which selects and ORDERS the pack: national-ID rows first, universal email
   and phone rows last, so a broad row cannot subsume a narrower one.
2. **Before the review payload goes on the wire.** `adapters/_review_payload.py` redacts the
   subject, the summary and every citation snippet, and it does so against **every**
   jurisdiction's rows plus the universal ones, not just the ones this deployment selected,
   because the Hrz7 console is a shared sink and a case filed in one market can still quote
   another market's national id. The redacted subject is reused for `case_ref` and `source_key`
   too, so a raw identifier cannot reach the console on a structured field either.
3. **Before a tool result reaches a model's context.** `agent/tools.py::_redacted` walks the
   whole serialised result structure, however deeply nested, rather than three named fields, so
   a field added later cannot arrive unmasked.

**The API response is deliberately NOT redacted.** It returns to an authenticated caller the
facts that caller just submitted; masking them would be theatre. The rule being enforced is
P-04, minimise what reaches the model and the durable record, not "mask everything everywhere".

## Which jurisdictions' patterns are active?

`domain/pii.py` sets `JURISDICTIONS = ("SG", "HK", "JP", "AU")` for the redaction that happens
inside this deployment. Note this is a different list from the three jurisdictions the rule packs
cover (SG, AU, JP): the pack set decides what the engine can compute, the PII list decides what
the redactor recognises, and a fork should set both deliberately. The outbound review payload
ignores the selection entirely and uses every jurisdiction's rows, for the reason above.

## Can the redaction go quietly green?

No, and that is tested. `pii_safety` in the eval gate is scored two ways: a pack scan using the
same rows the redactor masks with, and an independent planted-literal oracle that fires even if a
pattern row is broken. `tests/unit/test_not_falsely_green.py` proves the metric can actually go
red, which is the property a safety metric needs before it is worth anything.

## How is identity handled? Can a caller spoof the actor?

No. Identity is resolved server-side on every route and the client-asserted actor is discarded:
`TriageRequest` carries no `actor` field, and the audit actor and the review maker are both the
verified `Principal`.

What decides whether an end-user route may be reached off loopback at all is the **identity
binding**, and nothing else. Each adapter declares `VERIFIED`, `CLIENT_ASSERTED` or
`UNIMPLEMENTED` (`ports/identity.py`), silence reads as client-asserted, and
`add_loopback_exposure_guard` is registered at MODULE scope in `api/app.py` because the Dockerfile
`CMD` and `make run-api` serve the app object rather than calling `main()`. The service
credential `POLICYHR_S2S_TOKEN` may never enter that decision: it authenticates a calling
service and no end user, and while it did, setting it switched the guard off for exactly the
end-user routes it protected. `tests/unit/test_serving_path_exposure.py` and
`tests/unit/test_end_user_auth_posture.py` are the standing gates.

Per profile: `local` seeds dev personas and authenticates nobody (and the adapter refuses to
construct unless `local` was chosen deliberately, so a deployment whose profile variable went
missing does not start handing out an approver persona); `gcp` verifies the IAP assertion;
`onprem` raises.

## The managed identity adapter says VERIFIED. Does it earn that?

Yes, and it is the one adapter that may not go untested. `adapters/gcp/identity.py` calls
`id_token.verify_token` with the configured `POLICYHR_IAP_AUDIENCE` (three-state: unset or
emptied REFUSES, because `audience=None` is documented as not verifying the audience at all and
would accept any Google-signed token from any project), pins `certs_url` to IAP's own key set
rather than google-auth's OAuth2 default, checks the issuer itself because `verify_token` does
not, and wraps both the verifier call and the lazy import so no caller-supplied header can
produce a 500. `tests/unit/test_iap_identity.py` runs in every `make gate`;
`tests/unit/test_iap_crypto_matrix.py` runs the real verifier over a locally minted key in the
`iap-verifier` CI job and fails if it skips.

## What is the network posture?

Fail-closed by default and derived from two postures rather than one string. Relaxations (the
CORS allowlist, the `X-Dev-Persona` header, HSTS, the S2S scheme) key off `exposure_profile`,
which is `unconfigured` when nobody chose a profile; the loopback bound keys off `bind_profile`,
which is `local` when nobody chose. CORS never becomes `*`. `add_security_headers` is applied on
the API app, and `ui/proxy.ts` applies the same baseline to every UI response including error
responses. `/docs`, `/redoc` and `/openapi.json` are registered only under the deliberate `local`
profile, and are ABSENT rather than guarded elsewhere, because a guard the profile has switched
off is no guard.

## What about outbound service-to-service calls?

The one live outbound path is the rule R8 escalation to the Hrz7 console, over the shared
`review-kit` client, which refuses a plaintext non-loopback URL and a missing bearer at
construction. Its credentials (`HUMAN_REVIEW_S2S_TOKEN`, `HUMAN_REVIEW_S2S_SIGNING_KEY`) are deliberately
distinct variables from this service's own inbound `POLICYHR_S2S_TOKEN`, so an inbound secret can
never be spent outbound. The managed router REFUSES when no console is configured rather than
swallowing the escalation.

## Are there secrets in the repo?

No secret values. `config/settings.yaml` and `.env.example` carry variable NAMES and non-secret
defaults; `.env.secrets.example` carries placeholders. `tests/unit/test_repo_artifacts.py`
asserts this from inside the repo, and `.gitignore` excludes the real files.

## What is the supply-chain posture?

Committed `requirements-dev.lock` and `requirements-gcp.lock`, installed with `--no-deps` by
`make install`, by CI and by the Dockerfile; the catalog commons resolved in both lockfiles to
40-character commit shas rather than to the movable tags `pyproject.toml` names, because a
re-pushed tag would change what ships with no diff in the lockfile and no way to notice; a
digest-pinned base image; SHA-pinned Actions; dependabot per ecosystem; and `pip-audit`
over both locks plus `npm audit` for `ui/` as hard failures. `tests/unit/test_repo_artifacts.py`
asserts each of those from inside the repo.

## Is the audit trail tamper-evident?

Yes, with a stated limit and a fix for it. The offline sink is append-only and hash-chained via
`hex_service_kit.audit.HashChainedAuditLog`, which detects an edit, an interior deletion or a
reorder. It cannot detect a **truncated tail** on its own, because dropping the newest rows
leaves a shorter chain that verifies perfectly, so `audit_anchor_path` (`POLICYHR_AUDIT_ANCHOR`)
writes the chain head to a file on a different volume and every append updates it.
`tests/unit/test_audit_anchor.py` proves the detection, proves the control case goes UNDETECTED
without an anchor, and proves an append after a truncation refuses rather than re-anchoring.
Operating rules are in [`../runbook.md`](../runbook.md). Under `gcp` the sink is a locked Cloud
Logging bucket, which provides non-rewritability itself and needs no anchor.

## Does the browser ever assert who the user is?

No. In `ui/`, every client-supplied actor, tenant, role, ACL and authorization header is
discarded before forwarding (`ui/lib/embed-policy.mjs`), identity is resolved server-side
(`ui/lib/server/identity.ts`), and the service credential is read from the server environment so
it never reaches a bundle. Framing and CORS are per-tenant allowlists that refuse a wildcard, and
an unset tenant allowlist denies. Every environment read behind that boundary resolves three
states, scanned by `ui/tests/three-state-env-reads.test.mjs`, which is the guard that exists
because a two-state `env.UI_TENANT_ORIGINS || "*"` read once survived the entire gate.

## What is explicitly out of scope for this repo?

Prompt-injection screening and output filtering (**Hrz1**), the governed knowledge base
(**Hrz2**), the agent registry (**Hrz3**), the promotion and model-risk gate (**Hrz4**), the
shared observability and immutable audit sink (**Hrz5**), and the human-review console
(**Hrz7**). Of those, only Hrz7 is fully wired today. The rest are dependencies to integrate, not
features to rebuild. See [features-faq.md](features-faq.md) for the boundary map and
[`../../COMPLIANCE.md`](../../COMPLIANCE.md) for what each row still owes.

Two more things this repo does not do today: there is **no model in the request path**, so there
is no prompt surface to attack (see [features-faq.md](features-faq.md) and
[`../model-card.md`](../model-card.md)), and there is **no queryable data store**, so object-level
authorisation and ACL matchers are recorded as not-yet-applicable rather than implemented. The
tenant partition is carried on every outbound review; the first store this service gains must
bring server-side object-level authz with it.

## Is there a known, deliberate exception to the pure-domain rule?

Yes, one, and it is written down rather than hidden. `domain/packs.py` imports `yaml` to parse
the rule packs. It is recorded as a named exemption in
`tests/unit/test_core_purity.py::EXEMPT_IMPORTS` with the reason "policy packs are parsed inside
the core; extraction to the config boundary is queued", and the same module has a test that
deletes a stale exemption rather than letting it quietly cover the next violation. Any import in
the core that is not on that list fails the scan. See [portability-faq.md](portability-faq.md).
