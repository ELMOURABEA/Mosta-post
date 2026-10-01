"""What drives a comparison: choose a window, read both sides, classify every pair.

Unimplemented. This module exists to hold the decisions the implementation has to make, so the
next person starts from them rather than rediscovering them.

## How a pair is chosen

The join is one-directional, so there is no set-matching problem to solve. `read_platform_checks`
returns platform checks, and each one asks the source what state it held at that check's
`occurred_at`. The source side is not a set of checks at all: it is a state reconstruction that
answers for any instant. Five platform checks against three source checks in one window gives five
comparisons, not an alignment problem.

Two joins, both exact. `legacy_configuration_id` names the alert. `occurred_at` names the moment.

## The decision this forces

Neither join handles phase skew between the two cadences. The only defense is `SourceCoverage`
`BEHIND`, which asks whether the source had *seen* the data, by testing its own last check against
the window end in the evaluation key. It does not ask whether the source has had a check *since*
that data, so two stacks a few minutes out of phase produce a false `REAL`:

- The platform checks at 12:00 over a window ending 11:59, sees a breach, goes firing.
- Production logs last checked at 11:59, so the `BEHIND` test passes and coverage reads `EVALUATED`.
- Its own next check is 12:04, so at 12:00 it is still not firing.
- The states differ under `EVALUATED` coverage, which classifies as `REAL`.

The N-of-M window is a second route to the same false positive, independent of scheduling: each
stack builds its recent-breach history from its own rows, so two stacks reading the same data can
sit at different points in their own counts.

Three ways to answer it, and the choice belongs before anyone reads an agreement rate:

1. Compare only where both stacks have settled, skipping a platform check that falls within one
   source check-interval of a source transition.
2. Widen `BEHIND` to "the source has had a check since this data", testing its last check against
   the window end plus its check interval.
3. Take the noise in the first run, measure it, then choose. Preferred: the first two both discard
   comparisons to buy precision, and the real rate is unknown.

## What a run cannot see

Every comparison starts from a platform row, so a check the source made and the platform never did
is invisible. The harness measures what the platform decided and whether the source agreed, not
whether the two made the same checks.

## What else the implementation owes

- A sweep is per team, because `read_platform_checks` takes one `team_id`.
- Coverage measures the backfill as much as agreement: an alert the backfill never copied has no
  `legacy_configuration_id` and reads as `UNKNOWN`. Report it apart from the agreement rate, or the
  rate flatters itself.
- A correspondence must answer every ref it is given. The contract says so and nothing enforces it;
  this is the first caller that holds every correspondence, so the check belongs here.
- The ratchet in `test_divergence.py` iterates a hand-written list of correspondences, so a source
  that implements one and is not listed gets no coverage. A registry here is what closes it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from products.alerts.backend.comparison.contracts import SourceCorrespondence
from products.alerts.backend.comparison.divergence import Comparison


def run_comparison(
    *,
    team_ids: Sequence[int],
    correspondence: SourceCorrespondence,
    since: datetime,
    until: datetime,
) -> Sequence[Comparison]:
    """Every platform check in the window, set against what the source held at the same moment."""
    raise NotImplementedError("the comparison harness has no driver yet; see this module's docstring")
