# FAQ index

Answers to the questions different teams ask when evaluating, adopting, or reviewing this
repository (H2, the Policy and HR Copilot) as a common base for a deterministic HR entitlement
and policy-answer service. Each file is written for a specific audience; skim the one that
matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec and security review | what employee data is processed, server-side identity, the three redaction points, secrets, supply chain, the audit chain and its anchor, what is out of scope |
| [portability-faq.md](portability-faq.md) | Architecture, cloud and exit planning | the no-lock-in claim and its one recorded exemption, the three profiles, the executable portability check, the on-premises exit, data export |
| [features-faq.md](features-faq.md) | Product, HR operations and delivery | what the engine computes, what is deterministic, why a "copilot" has no model in it today, and where this repo's responsibility stops |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | the rebrand, taking upstream fixes, the rule packs, extension points, what breaks if you diverge |
| [compliance-faq.md](compliance-faq.md) | Compliance, employment governance and model risk | employee personal data and PDPA-class regimes, maker-checker, residency, the audit trail, the model-risk evidence and what is still owed |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
[catalog](https://github.com/portable-genai). Where a concern belongs to another repo
(the guardrail gateway, the governed knowledge base, the agent registry, the quality gate, the
observability sink, the human-review console), the FAQ names the owner and explains the boundary
rather than duplicating it. See [features-faq.md](features-faq.md) for the full "what this repo
owns vs what it integrates" map, and [`COMPLIANCE.md`](../../COMPLIANCE.md) for the same picture
as principle and rule rows with an explicit TODO on everything unfinished.
