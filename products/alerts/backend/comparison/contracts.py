"""What a comparison reads, and what a source must supply for one.

A comparison joins one platform check to the check a source's own stack made of the same alert
at the same due time. The platform side of that join is uniform: `legacy_configuration_id` on
the configuration names the source's own row, and `evaluation_key` on the history row names the
evaluation. The source side is not uniform. Logs keys its own checks on the window, insight will
key on the scheduled run, and neither shape is reconstructible from the platform row alone. So a
source supplies the correspondence through `SourceCorrespondence` rather than the harness
guessing it.

A source declares everything about itself on that one object: how to find its own verdicts, the
two policies its stacks run, and which differences between them are deliberate. A second
registration point in the shared package would let a source change one and not the other.

Two stacks never evaluate at the same instant. The key is what corresponds; a timestamp is only
a bound on how far apart two corresponding checks may sit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.facade.lifecycle import AlertPolicy


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

    A comparison is over `state`, not over `kind`, because a check that moved the alert while a
    cooldown or a mute held the notification back records `AlertEventKind.CHECK`. Counting kinds
    misses every suppressed move. `kind` and `previous_state` are carried so a report can say what
    the platform announced and what it moved from.

    `muted_notification` is the announcement a mute held back, as a `NotificationAction` value.
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
    kind: str
    previous_state: str
    state: str
    muted_notification: str
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

    `state` is an `AlertState` value as `facade.lifecycle` spells it, which is the vocabulary the
    platform records. A source whose own tables spell its states differently translates here, at
    its own edge: insight stores the `posthog.schema_enums` spelling ("Firing", "Not firing"), and
    returning that raw would read as a disagreement on every check.
    """

    coverage: SourceCoverage
    state: str | None
    suppressed_by: SuppressionReason | None = None
    # When the source's evidence was written, so a report can show how far apart the two sit.
    observed_at: datetime | None = None
    # Addresses the source's own row, so a person reading a disagreement can open both sides.
    evidence_id: str | None = None
    detail: str = ""


@frozen
class IntentionalDivergence:
    """One difference a source's platform stack makes on purpose.

    `recognizes` is what makes this a mechanism rather than a note: the classifier asks each
    declared divergence whether it explains the pair in front of it. A declaration without a
    working recognizer leaves its differences classified as real, which is the safe direction.

    `policy_flag` names the `AlertPolicy` field that causes it, and is what the ratchet matches
    against, so a source cannot configure a deliberate difference and leave it undeclared. Not
    every deliberate difference comes from a flag: insight collapses four failure kinds into two
    skip reasons, which no flag describes, so a declaration may leave it None and still be asked.

    The recognizer belongs to the source because the same flag shows up differently per source.
    Production logs stops checking a muted alert and its schedule stalls; insight keeps checking
    one and its schedule does not.
    """

    cause: str
    recognizes: Callable[[PlatformCheck, SourceVerdict], bool]
    why: str
    policy_flag: str | None = None


class SourceCorrespondence(Protocol):
    """How a source says which of its own history corresponds to a platform check.

    `verdicts_for` is batched rather than per check, because a source answers from its own tables
    and a per-check call would issue one query per row of a comparison window.

    A correspondence returns a verdict for every ref it was given. A check it cannot answer gets
    `SourceCoverage.UNKNOWN`, never a missing entry, so a caller cannot mistake silence for
    agreement.
    """

    source: SourceKind
    # What the source's own stack runs, against what its platform adapter runs. Declared here so
    # it stays next to the code that passes them to the machine.
    production_policy: AlertPolicy
    platform_policy: AlertPolicy
    intentional_divergences: tuple[IntentionalDivergence, ...]

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]: ...
