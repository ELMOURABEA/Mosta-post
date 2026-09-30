"""What a comparison reads, and what a source must supply for one.

A comparison joins one platform check to the check a source's own stack made of the same alert
at the same due time. The platform side of that join is uniform: `legacy_configuration_id` on
the configuration names the source's own row, and `evaluation_key` on the history row names the
evaluation. The source side is not uniform. Logs keys its own checks on the window, insight will
key on the scheduled run, and neither shape is reconstructible from the platform row alone. So a
source supplies the correspondence through `SourceCorrespondence` rather than the harness
guessing it.

Two stacks never evaluate at the same instant. The key is what corresponds; a timestamp is only
a bound on how far apart two corresponding checks may sit.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import SourceKind


@frozen
class CheckRef:
    """Addresses one platform check.

    `evaluation_key` is minted by the source and names the evaluation the check answered, so the
    pair survives a retry that recomputes the same check.
    """

    alert_id: UUID
    evaluation_key: str


@frozen
class PlatformCheck:
    """One row of the platform's check history, as a comparison reads it.

    `held_notification` is the announcement a mute held back, as a `NotificationAction` value.
    It is the platform's only record that an alert was muted at the moment of a check, because a
    muted check that decided nothing holds nothing and leaves no other trace.
    """

    team_id: int
    configuration_id: UUID
    # None for a configuration no source backfilled, which nothing can be compared against.
    legacy_configuration_id: UUID | None
    alert_id: UUID
    grouping_key: str
    evaluation_key: str
    previous_state: str
    state: str
    held_notification: str
    error_message: str
    occurred_at: datetime

    @property
    def ref(self) -> CheckRef:
        return CheckRef(alert_id=self.alert_id, evaluation_key=self.evaluation_key)


class SourceCoverage(StrEnum):
    """How far the source's own stack had got when the platform made this check.

    A source that cannot answer returns `UNKNOWN` rather than a guess, because a guess turns
    into a disagreement nobody can act on.
    """

    EVALUATED = "evaluated"
    SUPPRESSED = "suppressed"
    # The source's own stack had not reached this evaluation yet.
    BEHIND = "behind"
    UNKNOWN = "unknown"


class SuppressionReason(StrEnum):
    """Why a source's own stack made no check.

    `MUTED` covers a snooze and a schedule restriction together, because one platform policy flag
    covers both.
    """

    MUTED = "muted"
    DISABLED = "disabled"
    BROKEN = "broken"


@frozen
class SourceVerdict:
    """What a source's own stack held for the check that corresponds to one platform check.

    `state` is an `AlertState` value, which both stacks share, so a comparison never has to
    translate one product's state vocabulary into another's.
    """

    coverage: SourceCoverage
    state: str | None
    suppressed_by: SuppressionReason | None = None
    # When the source's evidence was written, so a report can show how far apart the two sit.
    observed_at: datetime | None = None
    # Addresses the source's own row, so a person reading a disagreement can open both sides.
    evidence_id: str | None = None
    detail: str = ""


class SourceCorrespondence(Protocol):
    """How a source says which of its own history corresponds to a platform check.

    Batched rather than per check, because a source answers from its own tables and a per-check
    call would issue one query per row of a comparison window.

    A correspondence returns a verdict for every ref it was given. A check it cannot answer gets
    `SourceCoverage.UNKNOWN`, never a missing entry, so a caller cannot mistake silence for
    agreement.
    """

    source: SourceKind

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]: ...
