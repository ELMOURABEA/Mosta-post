from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.alerts.backend.comparison.contracts import PlatformCheck, SourceCoverage, SuppressionReason
from products.logs.backend.alert_comparison import LogsCorrespondence
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent

CHECKED_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
WINDOW_END = CHECKED_AT - timedelta(minutes=1)


class TestLogsCorrespondence(BaseTest):
    def _alert(self, **overrides) -> LogsAlertConfiguration:
        return LogsAlertConfiguration.objects.create(
            team=self.team,
            name="API errors",
            created_by=self.user,
            threshold_count=10,
            **{"last_checked_at": CHECKED_AT, **overrides},
        )

    def _event(self, alert: LogsAlertConfiguration, *, at: datetime, **overrides) -> LogsAlertEvent:
        event = LogsAlertEvent.objects.create(
            alert=alert,
            threshold_breached=False,
            state_before=overrides.pop("state_before", LogsAlertConfiguration.State.NOT_FIRING),
            state_after=overrides.pop("state_after", LogsAlertConfiguration.State.FIRING),
            **overrides,
        )
        LogsAlertEvent.objects.filter(pk=event.pk).update(created_at=at)
        event.refresh_from_db()
        return event

    def _check(self, alert: LogsAlertConfiguration) -> PlatformCheck:
        return PlatformCheck(
            team_id=self.team.id,
            configuration_id=uuid4(),
            legacy_configuration_id=alert.id,
            alert_id=uuid4(),
            grouping_key="",
            evaluation_key=f"{alert.id}:window:{WINDOW_END.isoformat()}",
            previous_state="not_firing",
            state="firing",
            held_notification="none",
            error_message="",
            occurred_at=CHECKED_AT,
        )

    def _verdict(self, alert: LogsAlertConfiguration):
        check = self._check(alert)
        return LogsCorrespondence().verdicts_for([check])[check.ref]

    def test_an_alert_that_never_transitioned_reports_its_current_state(self) -> None:
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)

        verdict = self._verdict(alert)

        assert verdict.state == LogsAlertConfiguration.State.FIRING
        assert verdict.coverage is SourceCoverage.EVALUATED

    def test_the_state_comes_from_the_transition_after_the_check(self) -> None:
        alert = self._alert(state=LogsAlertConfiguration.State.FIRING)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(minutes=5),
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.FIRING,
        )

        verdict = self._verdict(alert)

        assert verdict.state == LogsAlertConfiguration.State.NOT_FIRING
        assert verdict.observed_at == CHECKED_AT + timedelta(minutes=5)

    @parameterized.expand(
        [
            (
                "snoozed",
                {"state": LogsAlertConfiguration.State.SNOOZED},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.MUTED,
            ),
            (
                "broken",
                {"state": LogsAlertConfiguration.State.BROKEN},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.BROKEN,
            ),
            (
                "inside a schedule restriction",
                {"schedule_restriction": {"blocked_windows": [{"start": "11:00", "end": "13:00"}]}},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.MUTED,
            ),
            (
                "disabled",
                {"enabled": False},
                SourceCoverage.SUPPRESSED,
                SuppressionReason.DISABLED,
            ),
            (
                "never checked",
                {"last_checked_at": None},
                SourceCoverage.BEHIND,
                None,
            ),
            (
                "stalled before the window the platform answered for",
                {"last_checked_at": WINDOW_END - timedelta(minutes=1)},
                SourceCoverage.BEHIND,
                None,
            ),
        ]
    )
    def test_coverage(
        self,
        _name: str,
        overrides: dict,
        coverage: SourceCoverage,
        suppressed_by: SuppressionReason | None,
    ) -> None:
        alert = self._alert(**overrides)

        verdict = self._verdict(alert)

        assert verdict.coverage is coverage
        assert verdict.suppressed_by is suppressed_by

    def test_a_disable_after_the_check_means_the_alert_was_enabled_at_it(self) -> None:
        alert = self._alert(enabled=False)
        self._event(
            alert,
            at=CHECKED_AT + timedelta(minutes=5),
            kind=LogsAlertEvent.Kind.DISABLE,
            state_before=LogsAlertConfiguration.State.NOT_FIRING,
            state_after=LogsAlertConfiguration.State.NOT_FIRING,
        )

        verdict = self._verdict(alert)

        assert verdict.coverage is SourceCoverage.EVALUATED

    def test_one_flapping_alert_does_not_cost_the_batch_its_answers(self) -> None:
        flapping = self._alert()
        quiet = self._alert()
        for minute in range(3):
            self._event(flapping, at=CHECKED_AT + timedelta(minutes=minute + 1))
        checks = [self._check(flapping), self._check(quiet)]

        with patch("products.logs.backend.alert_comparison.MAX_EVENTS_PER_WINDOW", 2):
            verdicts = LogsCorrespondence().verdicts_for(checks)

        assert verdicts[checks[0].ref].coverage is SourceCoverage.UNKNOWN
        assert verdicts[checks[1].ref].coverage is SourceCoverage.EVALUATED

    def test_a_check_whose_configuration_names_no_logs_alert_cannot_be_answered(self) -> None:
        orphan = replace(self._check(self._alert()), legacy_configuration_id=None)

        verdicts = LogsCorrespondence().verdicts_for([orphan])

        assert verdicts[orphan.ref].coverage is SourceCoverage.UNKNOWN
