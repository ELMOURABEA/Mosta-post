"""Why two stacks disagreed, in the three classes a reader can act on.

A harness that cannot separate these is noise.

**Real.** The same alert, the same check, a different verdict. This is the output the whole
exercise exists for.

**Timing.** One stack had not reached the evaluation the other made. Report it as a lag rather
than as a difference.

**Intentional.** The platform behaves differently on purpose, so a design decision shows up as
data. `INTENTIONAL_DIVERGENCES` below is the declared set, and `test_divergence.py` fails when a
source's platform policy departs from its production policy in a way nobody declared here.
"""

from __future__ import annotations

from dataclasses import fields
from enum import StrEnum
from typing import Final

from posthog.dataclasses import frozen

from products.alerts.backend.comparison.contracts import (
    CheckRef,
    PlatformCheck,
    SourceCoverage,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.facade.lifecycle import (
    LOGS_ALERT_POLICY,
    PLATFORM_LOGS_ALERT_POLICY,
    AlertPolicy,
    NotificationAction,
)


class DivergenceClass(StrEnum):
    REAL = "real"
    TIMING = "timing"
    INTENTIONAL = "intentional"


class Agreement(StrEnum):
    AGREED = "agreed"
    DIVERGED = "diverged"
    UNCOMPARABLE = "uncomparable"


@frozen
class IntentionalDivergence:
    """One difference the platform makes on purpose.

    `policy_flag` names the `AlertPolicy` field that causes it, and is what the ratchet matches
    against. A divergence that does not come from a policy flag leaves it None and is declared
    here by hand.
    """

    name: str
    sources: frozenset[SourceKind]
    policy_flag: str | None
    why: str


INTENTIONAL_DIVERGENCES: Final[tuple[IntentionalDivergence, ...]] = (
    IntentionalDivergence(
        name="mute_gates_notification_only",
        sources=frozenset({SourceKind.LOGS}),
        policy_flag="mute_gates_notification_only",
        why=(
            "The platform evaluates a muted alert and holds the announcement, so the alert keeps "
            "tracking reality through a snooze or a schedule restriction. Production logs excludes "
            "a snoozed alert from discovery and reschedules a restricted one, so it makes no check "
            "at all. Without this entry every snoozed logs alert reads as divergent."
        ),
    ),
)


# What each source's own stack runs, against what its platform adapter runs. A source joins the
# comparison by adding its pair here; the ratchet then covers it.
SOURCE_POLICIES: Final[dict[SourceKind, tuple[AlertPolicy, AlertPolicy]]] = {
    SourceKind.LOGS: (LOGS_ALERT_POLICY, PLATFORM_LOGS_ALERT_POLICY),
}


def diverging_policy_flags(production: AlertPolicy, platform: AlertPolicy) -> frozenset[str]:
    """The `AlertPolicy` fields on which the two stacks were configured differently."""
    return frozenset(f.name for f in fields(AlertPolicy) if getattr(production, f.name) != getattr(platform, f.name))


def declared_policy_flags(source: SourceKind) -> frozenset[str]:
    return frozenset(
        divergence.policy_flag
        for divergence in INTENTIONAL_DIVERGENCES
        if divergence.policy_flag is not None and source in divergence.sources
    )


def intentional_divergence_for(source: SourceKind, policy_flag: str) -> IntentionalDivergence | None:
    for divergence in INTENTIONAL_DIVERGENCES:
        if divergence.policy_flag == policy_flag and source in divergence.sources:
            return divergence
    return None


@frozen
class Comparison:
    """One platform check set against what the source's own stack held.

    `coverage` rides along so a report can separate an agreement rate from how much of the window
    the source could answer for at all.
    """

    ref: CheckRef
    agreement: Agreement
    coverage: SourceCoverage
    platform_state: str
    source_state: str | None
    divergence: DivergenceClass | None = None
    # The declared intentional divergence, or a short statement of why nothing could be compared.
    reason: str = ""


def _held_an_announcement(check: PlatformCheck) -> bool:
    return check.held_notification not in ("", NotificationAction.NONE.value)


def compare(check: PlatformCheck, verdict: SourceVerdict, *, source: SourceKind) -> Comparison:
    """Classifies one platform check against the source's verdict for the same check.

    The order matters. An intentional difference is checked before a timing one, because a muted
    alert also stalls the source's own schedule and would otherwise read as a lag. A timing
    difference is checked before a real one, because a source that never reached this evaluation
    cannot have disagreed about it.
    """

    def result(
        agreement: Agreement,
        *,
        divergence: DivergenceClass | None = None,
        reason: str = "",
    ) -> Comparison:
        return Comparison(
            ref=check.ref,
            agreement=agreement,
            coverage=verdict.coverage,
            platform_state=check.state,
            source_state=verdict.state,
            divergence=divergence,
            reason=reason,
        )

    if verdict.coverage is SourceCoverage.UNKNOWN:
        return result(Agreement.UNCOMPARABLE, reason=verdict.detail)

    if verdict.state == check.state:
        return result(Agreement.AGREED)

    mute = intentional_divergence_for(source, "mute_gates_notification_only")
    source_muted = verdict.coverage is SourceCoverage.SUPPRESSED and verdict.suppressed_by is SuppressionReason.MUTED
    # A held announcement says the platform was muted. A muted source records nothing and stops
    # advancing its own schedule, so BEHIND is what the same mute looks like from the source's
    # side. A source that reports anything else was not muted, which makes a held announcement
    # evidence that the two configurations disagree rather than evidence of this divergence.
    platform_muted_and_source_stalled = _held_an_announcement(check) and verdict.coverage is SourceCoverage.BEHIND
    if (source_muted or platform_muted_and_source_stalled) and mute is not None:
        return result(Agreement.DIVERGED, divergence=DivergenceClass.INTENTIONAL, reason=mute.name)

    if verdict.coverage is SourceCoverage.BEHIND:
        return result(Agreement.DIVERGED, divergence=DivergenceClass.TIMING, reason="source has not reached this check")

    if verdict.coverage is SourceCoverage.SUPPRESSED:
        # Both stacks exclude a disabled or broken alert, so the platform checking one that its
        # source would not have means the two configurations have drifted apart.
        return result(
            Agreement.DIVERGED,
            divergence=DivergenceClass.REAL,
            reason=f"platform checked an alert its source suppressed ({verdict.suppressed_by})",
        )

    return result(Agreement.DIVERGED, divergence=DivergenceClass.REAL)
