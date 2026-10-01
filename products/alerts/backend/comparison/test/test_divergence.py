from datetime import UTC, datetime
from uuid import uuid4

from unittest import TestCase

from parameterized import parameterized

from products.alerts.backend.comparison.contracts import PlatformCheck, SourceCoverage, SourceVerdict, SuppressionReason
from products.alerts.backend.comparison.divergence import Agreement, DivergenceClass, compare, diverging_policy_flags
from products.logs.backend.alert_comparison import LogsCorrespondence

# A source that implements a correspondence and is not listed here gets no ratchet coverage.
CORRESPONDENCES = (LogsCorrespondence(),)

AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _check(state: str, muted_notification: str = "none") -> PlatformCheck:
    return PlatformCheck(
        team_id=1,
        configuration_id=uuid4(),
        legacy_configuration_id=uuid4(),
        alert_id=uuid4(),
        grouping_key="",
        evaluation_key="window:2026-09-30T11:55:00+00:00",
        previous_state="not_firing",
        state=state,
        kind="check",
        muted_notification=muted_notification,
        error_message="",
        occurred_at=AT,
    )


class TestDivergenceClassification(TestCase):
    @parameterized.expand(
        [
            (
                "agreed",
                _check("firing"),
                SourceVerdict(coverage=SourceCoverage.EVALUATED, state="firing"),
                Agreement.AGREED,
                None,
            ),
            (
                "differing verdicts on an evaluated check",
                _check("firing"),
                SourceVerdict(coverage=SourceCoverage.EVALUATED, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the source made no check because it was muted",
                _check("firing"),
                SourceVerdict(
                    coverage=SourceCoverage.SUPPRESSED,
                    state="snoozed",
                    suppressed_by=SuppressionReason.MUTED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.INTENTIONAL,
            ),
            (
                "the platform held an announcement while the source fell behind",
                _check("firing", muted_notification="fire"),
                SourceVerdict(coverage=SourceCoverage.BEHIND, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.INTENTIONAL,
            ),
            (
                "the platform held an announcement the source was not muted for",
                _check("firing", muted_notification="fire"),
                SourceVerdict(coverage=SourceCoverage.EVALUATED, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the platform held an announcement for an alert the source had disabled",
                _check("firing", muted_notification="fire"),
                SourceVerdict(
                    coverage=SourceCoverage.SUPPRESSED,
                    state="not_firing",
                    suppressed_by=SuppressionReason.DISABLED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the source has not reached this check",
                _check("firing"),
                SourceVerdict(coverage=SourceCoverage.BEHIND, state="not_firing"),
                Agreement.DIVERGED,
                DivergenceClass.TIMING,
            ),
            (
                "the platform checked an alert the source had disabled",
                _check("firing"),
                SourceVerdict(
                    coverage=SourceCoverage.SUPPRESSED,
                    state="not_firing",
                    suppressed_by=SuppressionReason.DISABLED,
                ),
                Agreement.DIVERGED,
                DivergenceClass.REAL,
            ),
            (
                "the source cannot say",
                _check("firing"),
                SourceVerdict(coverage=SourceCoverage.UNKNOWN, state=None, detail="no such alert"),
                Agreement.UNCOMPARABLE,
                None,
            ),
            (
                "a lagging source that happens to hold the same verdict",
                _check("firing"),
                SourceVerdict(coverage=SourceCoverage.BEHIND, state="firing"),
                Agreement.AGREED,
                None,
            ),
        ]
    )
    def test_classification(
        self,
        _name: str,
        check: PlatformCheck,
        verdict: SourceVerdict,
        agreement: Agreement,
        divergence: DivergenceClass | None,
    ) -> None:
        comparison = compare(check, verdict, correspondence=LogsCorrespondence())

        assert comparison.agreement == agreement
        assert comparison.divergence == divergence

    @parameterized.expand([(c.source.value, c) for c in CORRESPONDENCES])
    def test_every_policy_divergence_is_declared(self, _name: str, correspondence) -> None:
        declared = {divergence.policy_flag for divergence in correspondence.intentional_divergences}

        assert diverging_policy_flags(correspondence.production_policy, correspondence.platform_policy) == declared
