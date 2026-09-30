import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { reportMetricsFixture } from '../../__mocks__/reportMetricMocks'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { buildReportCheckRows } from './reportCheckPresentation'
import { ReportCheckRow } from './ReportCheckRow'

jest.mock('./ReportCheckMetricChart', () => ({ ReportCheckMetricChart: () => <div>Chart</div> }))

const report: SignalReport = {
    id: 'report-1',
    title: 'Checkout errors',
    summary: 'Checkout sometimes fails.',
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 1,
    artefact_count: 0,
    is_suggested_reviewer: false,
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
}

const check: SignalReportCheckApi = {
    id: 'check-1',
    title: 'Checkout errors stay below 5',
    rationale: 'The fix should reduce failures.',
    kind: 'metric_threshold',
    status: 'pending',
    config: {
        metric_id: reportMetricsFixture[0].metric_id,
        query: reportMetricsFixture[0].query as Record<string, unknown>,
        comparison: { operator: 'lte', value: 5 },
        baseline_value: 20,
    },
    approved_at: null,
    next_run_at: '2026-10-13T00:00:00Z',
    soak_minutes: 20160,
    run_interval_minutes: null,
    runs_remaining: 1,
    expires_at: '2026-11-13T00:00:00Z',
    last_run_at: null,
    last_outcome: null,
    dispatched_at: null,
    consecutive_errors: 0,
    created_at: '2026-09-29T00:00:00Z',
    updated_at: '2026-09-29T00:00:00Z',
}

describe('ReportCheckRow', () => {
    beforeEach(() => {
        initKeaTests()
        inboxTaskKickoffLogic.mount()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    function renderRow(onApprove = jest.fn(), shownCheck = check): void {
        render(
            <ReportCheckRow
                row={buildReportCheckRows([shownCheck], new Map())[0]}
                report={report}
                reportUrl="https://example.com/report-1"
                cancelling={false}
                approving={false}
                onCancel={jest.fn()}
                onApprove={onApprove}
            />
        )
    }

    it('requests approval for an open check', async () => {
        const onApprove = jest.fn()
        renderRow(onApprove)

        await userEvent.setup().click(screen.getByText('Looks good'))

        expect(onApprove).toHaveBeenCalledWith(check.id)
    })

    it('keeps the metric suggestion and chart controls on the check', async () => {
        renderRow()
        const user = userEvent.setup()

        await user.click(screen.getByText('View measurement'))
        expect(screen.getByText('Chart')).toBeInTheDocument()
        await user.click(screen.getByText('Suggest different metrics'))
        expect(screen.getByText('Describe a better metric')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Ask AI to update check' })).toHaveAttribute('aria-disabled', 'true')
    })

    it('does not offer approval after a check finishes', () => {
        renderRow(jest.fn(), { ...check, status: 'failed' })

        expect(screen.queryByText('Looks good')).not.toBeInTheDocument()
    })
})
