"""The platform half of a comparison: the checks the platform recorded in a window.

Deliberately unimplemented. Two things have to land before a read here can return anything a
comparison can use:

- Nothing writes `platform_alert_events`. The table and its TTL exist, and the activity that
  records a row for every check does not, so the table is empty in every deployment.
- The row carries no `source_kind`, so a per-source read cannot be expressed in ClickHouse alone.
  The configuration join is needed regardless, because `legacy_configuration_id` lives on
  `PlatformAlertConfiguration` in Postgres rather than on the row, and that column is the source
  side of every correspondence.

Implement `read_platform_checks` once the writer is deployed. The contract above it is what a
source adapter is already written against, so the sources need no change when it arrives.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from products.alerts.backend.comparison.contracts import PlatformCheck
from products.alerts.backend.facade.contracts import SourceKind


class PlatformHistoryUnavailable(Exception):
    """The platform's check history cannot answer a comparison yet."""


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
    raise PlatformHistoryUnavailable(
        "platform_alert_events has no writer, and the row carries no source_kind to read by"
    )
