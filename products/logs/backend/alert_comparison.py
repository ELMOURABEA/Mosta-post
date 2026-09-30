"""The logs side of the alerts platform comparison contract.

Answers what the production logs stack held for the check that corresponds to one platform
check. The correspondence is reconstructed rather than looked up, because production logs keeps
no per-check row: `LogsAlertEvent` is written only when a check moves the alert or errors, plus
the control-plane rows a user action writes.

So the walk runs backwards from the present. The configuration's current `state` and `enabled`
are known, and every event row carries the state on both sides of itself, which makes the state
at any past instant the `state_before` of the first event after it. An alert that never moved
has no rows at all and resolves to its current state, which is the common case and the one a
forward walk would have to give up on.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from django.db.models import Count

import structlog

from products.alerts.backend.comparison.contracts import (
    CheckRef,
    PlatformCheck,
    SourceCorrespondence,
    SourceCoverage,
    SourceVerdict,
    SuppressionReason,
)
from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.facade.lifecycle import AlertState
from products.alerts.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

logger = structlog.get_logger(__name__)

# An alert that flaps holds many transitions in one window. Past this bound the chain is not
# worth holding in memory, and a truncated chain would date checks wrongly.
MAX_EVENTS_PER_WINDOW = 5000


def _window_end(evaluation_key: str) -> datetime | None:
    """The end of the window a logs evaluation answered for, as its own key names it.

    The key is minted by this source, so this is the only place that has to know its shape.
    Used as the bound a lagging production stack is measured against, and nothing else, so an
    unrecognized key costs the comparison precision rather than an answer.
    """
    _, marker, tail = evaluation_key.rpartition("window:")
    if not marker:
        return None
    try:
        return datetime.fromisoformat(tail)
    except ValueError:
        return None


class LogsCorrespondence(SourceCorrespondence):
    source = SourceKind.LOGS

    def verdicts_for(self, checks: Sequence[PlatformCheck]) -> Mapping[CheckRef, SourceVerdict]:
        verdicts: dict[CheckRef, SourceVerdict] = {}
        by_alert: dict[tuple[int, UUID], list[PlatformCheck]] = defaultdict(list)
        for check in checks:
            if check.legacy_configuration_id is None:
                verdicts[check.ref] = _unknown("the platform configuration names no logs alert")
            else:
                by_alert[(check.team_id, check.legacy_configuration_id)].append(check)

        if not by_alert:
            return verdicts

        configurations = {
            (configuration.team_id, configuration.id): configuration
            for configuration in LogsAlertConfiguration.objects.select_related("team").filter(
                id__in=[alert_id for _, alert_id in by_alert],
                team_id__in={team_id for team_id, _ in by_alert},
            )
        }
        matched = by_alert.keys() & configurations.keys()
        events = self._events_since(
            matched,
            since=min(check.occurred_at for group in by_alert.values() for check in group),
        )

        for key, group in by_alert.items():
            configuration = configurations.get(key)
            if configuration is None:
                for check in group:
                    verdicts[check.ref] = _unknown("no logs alert with that id in this project")
                continue
            chain = events.get(key[1])
            if chain is None:
                for check in group:
                    verdicts[check.ref] = _unknown("too many logs transitions to date this check against")
                continue
            for check in group:
                verdicts[check.ref] = _verdict_at(configuration, chain, check)

        return verdicts

    def _events_since(self, keys: set[tuple[int, UUID]], *, since: datetime) -> dict[UUID, list[LogsAlertEvent]]:
        """Every transition each alert made after `since`, oldest first, keyed by alert.

        An alert whose chain hit the bound is left out, so a caller cannot read a truncated chain
        as a complete one.
        """
        transitions = LogsAlertEvent.objects.filter(
            alert_id__in=[alert_id for _, alert_id in keys],
            alert__team_id__in={team_id for team_id, _ in keys},
            created_at__gt=since,
        )
        # Counted first because the fetch below is ordered across the whole batch, which makes a
        # truncated read impossible to attribute to the alert it truncated. One alert that flaps
        # would otherwise cost every alert in the batch its answer.
        overflowing = set(
            transitions.values("alert_id")
            .annotate(transitions=Count("id"))
            .filter(transitions__gt=MAX_EVENTS_PER_WINDOW)
            .values_list("alert_id", flat=True)
        )
        if overflowing:
            logger.warning(
                "Logs alert comparison read more transitions than it will hold",
                since=since.isoformat(),
                alerts=len(overflowing),
            )

        chains: dict[UUID, list[LogsAlertEvent]] = {alert_id: [] for _, alert_id in keys if alert_id not in overflowing}
        for row in (
            transitions.exclude(alert_id__in=overflowing)
            .only("id", "alert_id", "kind", "created_at", "state_before")
            .order_by("created_at")
        ):
            chains[row.alert_id].append(row)
        return chains


def _unknown(detail: str) -> SourceVerdict:
    return SourceVerdict(coverage=SourceCoverage.UNKNOWN, state=None, detail=detail)


def _verdict_at(
    configuration: LogsAlertConfiguration,
    chain: Sequence[LogsAlertEvent],
    check: PlatformCheck,
) -> SourceVerdict:
    at = check.occurred_at
    boundary = next((event for event in chain if event.created_at > at), None)
    state = boundary.state_before if boundary is not None else configuration.state

    toggle = next(
        (
            event
            for event in chain
            if event.created_at > at and event.kind in (LogsAlertEvent.Kind.ENABLE, LogsAlertEvent.Kind.DISABLE)
        ),
        None,
    )
    enabled = toggle.kind == LogsAlertEvent.Kind.DISABLE if toggle is not None else configuration.enabled

    # The boundary is the transition that ended the state being reported, so it dates that state
    # rather than the check. None means the state still holds.
    observed_at = boundary.created_at if boundary is not None else None
    evidence_id = str(boundary.id) if boundary is not None else None

    def verdict(coverage: SourceCoverage, *, suppressed_by: SuppressionReason | None = None) -> SourceVerdict:
        return SourceVerdict(
            coverage=coverage,
            state=state,
            suppressed_by=suppressed_by,
            observed_at=observed_at,
            evidence_id=evidence_id,
        )

    if not enabled:
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.DISABLED)
    if state == AlertState.BROKEN:
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.BROKEN)
    if state == AlertState.SNOOZED:
        # No history of `snooze_until` is kept, so the state overstates the snooze by up to the
        # one check interval production logs takes to write the transition out of it.
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.MUTED)
    if is_utc_datetime_blocked(
        at, configuration.team.timezone, parse_blocked_windows_tuples(configuration.schedule_restriction)
    ):
        return verdict(SourceCoverage.SUPPRESSED, suppressed_by=SuppressionReason.MUTED)

    # Production logs must have reached this data before it can have disagreed about it.
    bound = _window_end(check.evaluation_key) or at
    if configuration.last_checked_at is None or configuration.last_checked_at < bound:
        return verdict(SourceCoverage.BEHIND)

    return verdict(SourceCoverage.EVALUATED)
