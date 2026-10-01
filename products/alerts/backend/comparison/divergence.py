"""Why two stacks disagreed, in the three classes a reader can act on.

A harness that cannot separate these is noise.

**Real.** The same alert, the same check, a different verdict. This is the output the whole
exercise exists for.

**Timing.** One stack had not reached the evaluation the other made. Report it as a lag rather
than as a difference.

**Intentional.** The platform behaves differently on purpose, so a design decision shows up as
data. A source declares those on its correspondence, each with a recognizer `compare` asks, and
`test_divergence.py` fails when a source's platform policy departs from its production policy in
a way nobody declared.
"""

from __future__ import annotations

from dataclasses import fields
from enum import StrEnum

from posthog.dataclasses import frozen

from products.alerts.backend.comparison.contracts import (
    CheckRef,
    PlatformCheck,
    SourceCorrespondence,
    SourceCoverage,
    SourceVerdict,
)
from products.alerts.backend.facade.lifecycle import AlertPolicy


class DivergenceClass(StrEnum):
    REAL = "real"
    TIMING = "timing"
    INTENTIONAL = "intentional"


class Agreement(StrEnum):
    AGREED = "agreed"
    DIVERGED = "diverged"
    UNCOMPARABLE = "uncomparable"


def diverging_policy_flags(production: AlertPolicy, platform: AlertPolicy) -> frozenset[str]:
    """The `AlertPolicy` fields on which the two stacks were configured differently."""
    return frozenset(f.name for f in fields(AlertPolicy) if getattr(production, f.name) != getattr(platform, f.name))


@frozen
class Comparison:
    """One platform check set against what the source's own stack held.

    `coverage` rides along so a report can separate an agreement rate from how much of the window
    the source could answer for at all.
    """

    ref: CheckRef
    coverage: SourceCoverage
    platform_state: str
    source_state: str | None
    divergence: DivergenceClass | None = None
    # The declared divergence's policy flag, or a short statement of why nothing could be compared.
    reason: str = ""

    @property
    def agreement(self) -> Agreement:
        if self.coverage is SourceCoverage.UNKNOWN:
            return Agreement.UNCOMPARABLE
        return Agreement.AGREED if self.divergence is None else Agreement.DIVERGED


def compare(check: PlatformCheck, verdict: SourceVerdict, *, correspondence: SourceCorrespondence) -> Comparison:
    """Classifies one platform check against the source's verdict for the same check.

    Takes the correspondence rather than a source kind, so a caller cannot classify one source's
    verdict under another source's declarations.

    The order matters. A declared divergence is asked before a timing one, because the mute that
    explains a difference also stalls the source's own schedule and would otherwise read as a lag.
    A timing difference is asked before a real one, because a source that never reached this
    evaluation cannot have disagreed about it.
    """

    def result(divergence: DivergenceClass | None = None, reason: str = "") -> Comparison:
        return Comparison(
            ref=check.ref,
            coverage=verdict.coverage,
            platform_state=check.state,
            source_state=verdict.state,
            divergence=divergence,
            reason=reason,
        )

    if verdict.coverage is SourceCoverage.UNKNOWN:
        return result(reason=verdict.detail)

    if verdict.state == check.state:
        return result()

    declared = next((d for d in correspondence.intentional_divergences if d.recognizes(check, verdict)), None)
    if declared is not None:
        return result(DivergenceClass.INTENTIONAL, declared.policy_flag)

    if verdict.coverage is SourceCoverage.BEHIND:
        return result(DivergenceClass.TIMING, "source has not reached this check")

    if verdict.coverage is SourceCoverage.SUPPRESSED:
        # Both stacks exclude a disabled or broken alert, so the platform checking one that its
        # source would not have means the two configurations have drifted apart.
        return result(
            DivergenceClass.REAL, f"platform checked an alert its source suppressed ({verdict.suppressed_by})"
        )

    return result(DivergenceClass.REAL)
