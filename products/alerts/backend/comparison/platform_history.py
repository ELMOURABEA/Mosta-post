"""The platform half of a comparison: the checks the platform recorded in a window.

The history row carries `configuration_id`, and a correspondence needs `legacy_configuration_id`,
which lives on `PlatformAlertConfiguration` in Postgres. So a read is a Postgres query followed by
a ClickHouse one, and that stays true whatever columns the row grows.

Restricting the ClickHouse read to one source's configurations is what selects a source, rather
than a column on the row. A `source_kind` column would let ClickHouse do the filtering instead of
receiving the answer, which is a narrower read rather than a different one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.alerts.backend.comparison.contracts import PlatformCheck
from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.models import PlatformAlertConfiguration
from products.alerts.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

# Refused rather than cut short, because an agreement rate over a silently truncated window
# is worse than no rate at all.
MAX_CHECKS_PER_WINDOW = 200_000

_COLUMNS = (
    "configuration_id",
    "alert_id",
    "grouping_key",
    "evaluation_key",
    "kind",
    "previous_state",
    "state",
    "muted_notification",
    "error_message",
    "occurred_at",
)

# `LIMIT 1 BY` deduplicates on the pair the writer names, because the insert token only covers a
# retry of the same batch and the engine remembers a bounded window of tokens.
_SELECT_SQL = f"""
SELECT {", ".join(_COLUMNS)}
FROM {PLATFORM_ALERT_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND configuration_id IN %(configuration_ids)s
  AND occurred_at >= %(since)s
  AND occurred_at < %(until)s
ORDER BY occurred_at, alert_id, evaluation_key
LIMIT 1 BY alert_id, evaluation_key
LIMIT %(limit)s
"""


class ComparisonWindowTooLarge(Exception):
    """The window holds more checks than one read will return."""


def read_platform_checks(
    *,
    team_id: int,
    source: SourceKind,
    since: datetime,
    until: datetime,
) -> Sequence[PlatformCheck]:
    """Every check the platform recorded for one source and team in `[since, until)`.

    A window wider than the shorter of the two retentions is not available: the platform's rows
    expire on a 90-day ClickHouse TTL, and each source ages its own history on its own schedule.
    """
    legacy_ids: dict[UUID, UUID | None] = dict(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(source_kind=source.value)
        .values_list("id", "legacy_configuration_id")
    )
    if not legacy_ids:
        return ()

    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = sync_execute(
        _SELECT_SQL,
        {
            "team_id": team_id,
            "configuration_ids": list(legacy_ids),
            "since": since,
            "until": until,
            "limit": MAX_CHECKS_PER_WINDOW + 1,
        },
        team_id=team_id,
    )
    if len(rows) > MAX_CHECKS_PER_WINDOW:
        raise ComparisonWindowTooLarge(
            f"{since.isoformat()} to {until.isoformat()} holds over {MAX_CHECKS_PER_WINDOW} checks; narrow it"
        )

    # Bound by name, because `previous_state` and `state` are adjacent columns of one type and a
    # reordering of `_COLUMNS` would swap them silently.
    checks = (dict(zip(_COLUMNS, row, strict=True)) for row in rows)
    return tuple(
        PlatformCheck(
            team_id=team_id,
            legacy_configuration_id=legacy_ids[check["configuration_id"]],
            **check,
        )
        for check in checks
    )
