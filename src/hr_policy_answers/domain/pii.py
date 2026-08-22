"""The PII pattern set this vertical redacts with, sourced from the shared `pii-kit`.

Row selection and ORDER are per-vertical (the commons deliberately does not bake them in): here
the national-ID rows run first and the universal email/phone rows last. A vertical with a
bare-digit account catch-all would order that last so it does not subsume a national id.

:func:`redacted_citations` lives here too, next to the rows it masks with, because both services
need the same act and a redaction rule that exists twice is a redaction rule that diverges once.
"""

from __future__ import annotations

from pii_kit import UNIVERSAL_PATTERNS, Pattern, national_patterns_for, redact

from .kernel import Citation

# The jurisdictions this deployment serves (override per client). Obviously synthetic data only.
JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")

PII_PATTERNS: tuple[Pattern, ...] = (
    *national_patterns_for(JURISDICTIONS),
    *UNIVERSAL_PATTERNS,
)


def redacted_citations(citations: tuple[Citation, ...]) -> tuple[Citation, ...]:
    """Mask EVERY field of every citation: the snippet, the title AND the locator.

    A citation travelled into the WORM record beside an already-masked ``redacted_summary`` and
    was written verbatim, so the record kept precisely what the redaction removed. The
    ``source_id`` is not exempt for being a locator: a locator is COMPOSED out of what the case
    supplied (``case:<subject>`` is the subject), and a title that names the employee is the same
    text with a different key. Masking all three unconditionally is cheaper to keep true than
    deciding per field, and masking text that carries no identifier is a no-op, so an engine
    citing a statute is unchanged by this.
    """
    return tuple(
        Citation(
            source_id=redact(citation.source_id, PII_PATTERNS),
            title=redact(citation.title, PII_PATTERNS),
            snippet=redact(citation.snippet, PII_PATTERNS),
        )
        for citation in citations
    )
