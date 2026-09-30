import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock, IconTrends } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag, LemonTextArea, Tooltip } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { MetricThresholdConfigApi, ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { SignalReport } from '../../types'
import { asReportMetricSeriesQuery, formatReportMetricValue } from '../../utils/reportMetrics'
import { ReportCheckMetricChart } from './ReportCheckMetricChart'
import { ReportCheckRowData } from './reportCheckPresentation'

/**
 * One follow-up check on the report rail: what it claims, where it stands, and the one thing a
 * reader can still do about it. The Stop button appears on hover and confirms first, because a
 * cancelled check is terminal and its author has to write a new one to get the answer back.
 */
export function ReportCheckRow({
    row,
    report,
    reportUrl,
    cancelling,
    approving,
    onCancel,
    onApprove,
}: {
    row: ReportCheckRowData
    report: SignalReport
    reportUrl: string
    cancelling: boolean
    approving: boolean
    onCancel: (checkId: string) => void
    onApprove: (checkId: string) => void
}): JSX.Element {
    const { check, tag, detail, cancelled, cancellable } = row
    const [expanded, setExpanded] = useState(false)
    const [modalOpen, setModalOpen] = useState(false)
    const [description, setDescription] = useState('')
    const { openReportDiscussion, discussReport } = useActions(inboxTaskKickoffLogic)
    const { currentProjectId, aiConsentDisabledReason, isDiscussing, isCreatingPr } = useValues(inboxTaskKickoffLogic)
    const metricConfig: MetricThresholdConfigApi | null =
        check.kind === 'metric_threshold' && 'comparison' in check.config ? check.config : null
    const metric: ReportMetricApi | null = metricConfig
        ? {
              metric_id: metricConfig.metric_id ?? check.id,
              title: check.title,
              kind: metricConfig.metric_kind ?? 'custom',
              query: metricConfig.query,
              value_format: metricConfig.value_format,
              unit: metricConfig.unit,
              goal_value: metricConfig.comparison.operator === 'between' ? null : metricConfig.comparison.value,
          }
        : null
    const seriesQuery = metric ? asReportMetricSeriesQuery(metric) : null

    const suggest = (): void => {
        const request = description.trim()
        if (!request) {
            return
        }
        openReportDiscussion(report, reportUrl)
        discussReport(report, reportUrl, request, undefined, `check_metric:${check.id}`)
        setModalOpen(false)
    }

    return (
        <div
            className={`group flex flex-col gap-1 rounded border border-primary bg-surface-primary px-2.5 py-2 ${
                cancelled ? 'opacity-60' : ''
            }`}
        >
            <div className="flex items-start gap-2 min-w-0">
                <span className="mt-0.5 shrink-0 text-tertiary [&_svg]:size-3.5">
                    {check.kind === 'agent' ? <IconClock /> : <IconTrends />}
                </span>
                <Tooltip title={check.rationale || undefined}>
                    <span
                        className={`min-w-0 flex-1 text-xs leading-snug text-default line-clamp-2 ${
                            cancelled ? 'line-through' : ''
                        }`}
                    >
                        {check.title}
                    </span>
                </Tooltip>
                <LemonTag size="small" type={tag.type} className="shrink-0">
                    {tag.label}
                </LemonTag>
            </div>
            <div className="flex items-end gap-2 min-w-0 pl-[1.375rem]">
                <span className="min-w-0 flex-1 text-xs leading-snug text-tertiary">{detail}</span>
                {cancellable && (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        status="danger"
                        loading={cancelling}
                        disabledReason={cancelling ? 'Stopping this check' : undefined}
                        data-attr="signals-report-check-stop"
                        className="shrink-0 opacity-0 transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
                        onClick={() =>
                            LemonDialog.open({
                                title: 'Stop this check?',
                                description: `"${check.title}" will not run, and nothing will report back on it. Results it already recorded stay on this report.`,
                                primaryButton: {
                                    children: 'Stop check',
                                    status: 'danger',
                                    onClick: () => onCancel(check.id),
                                },
                                secondaryButton: { children: 'Keep it' },
                            })
                        }
                    >
                        Stop
                    </LemonButton>
                )}
            </div>
            <div className="flex flex-wrap items-center gap-1 pl-[1.375rem]">
                {check.approved_at ? (
                    <LemonTag size="small" type="success">
                        Looks good
                    </LemonTag>
                ) : cancellable ? (
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        loading={approving}
                        data-attr="signals-report-check-approve"
                        disabledReason={
                            currentProjectId == null
                                ? 'Select a project to approve this check.'
                                : metricConfig && metricConfig.query == null
                                  ? 'The measurement query is not available to you.'
                                  : undefined
                        }
                        onClick={() => onApprove(check.id)}
                    >
                        Looks good
                    </LemonButton>
                ) : null}
                {metricConfig && (
                    <>
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            data-attr="signals-report-check-view-measurement"
                            onClick={() => setExpanded(!expanded)}
                        >
                            {expanded ? 'Hide measurement' : 'View measurement'}
                        </LemonButton>
                        {cancellable && (
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                data-attr="signals-report-check-suggest-metrics"
                                onClick={() => setModalOpen(true)}
                            >
                                Suggest different metrics
                            </LemonButton>
                        )}
                    </>
                )}
            </div>
            {expanded && metricConfig && (
                <div className="flex flex-col gap-2 pl-[1.375rem] text-xs">
                    <p className="m-0 text-secondary">
                        {metricConfig.comparison.operator === 'between'
                            ? `Goal: between ${metricConfig.comparison.bounds?.lower} and ${metricConfig.comparison.bounds?.upper}`
                            : `Goal: ${metricConfig.comparison.operator === 'lte' ? 'at most' : 'at least'} ${
                                  metric && metricConfig.comparison.value != null
                                      ? (formatReportMetricValue(metric, metricConfig.comparison.value) ??
                                        metricConfig.comparison.value)
                                      : ''
                              }`}
                        {metricConfig.baseline_value != null && metric
                            ? ` · Baseline: ${formatReportMetricValue(metric, metricConfig.baseline_value) ?? metricConfig.baseline_value}`
                            : ''}
                    </p>
                    {metric && seriesQuery ? (
                        <ReportCheckMetricChart
                            reportId={report.id}
                            metric={metric}
                            query={seriesQuery.source}
                            goalGrain="whole_window"
                            version={check.id}
                        />
                    ) : (
                        <p className="m-0 text-tertiary">The measurement query is not available to you.</p>
                    )}
                    {metricConfig.query != null && (
                        <details>
                            <summary className="cursor-pointer">View measurement query</summary>
                            <pre className="max-h-64 overflow-auto rounded bg-surface-secondary p-2 text-xs">
                                {JSON.stringify(metricConfig.query, null, 2)}
                            </pre>
                        </details>
                    )}
                </div>
            )}
            <LemonModal
                isOpen={modalOpen}
                onClose={() => setModalOpen(false)}
                title="Describe a better metric"
                width={560}
                footer={
                    <>
                        <LemonButton type="secondary" onClick={() => setModalOpen(false)}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            data-attr="signals-report-check-ask-ai-update"
                            onClick={suggest}
                            loading={isDiscussing}
                            disabledReason={
                                aiConsentDisabledReason ??
                                (isCreatingPr ? 'An implementation is starting.' : undefined) ??
                                (!description.trim() ? 'Describe the outcome first.' : undefined)
                            }
                        >
                            Ask AI to update check
                        </LemonButton>
                    </>
                }
            >
                <LemonTextArea
                    value={description}
                    onChange={setDescription}
                    placeholder="For example, fewer users should see the not-found page within a week."
                    rows={4}
                    maxLength={2000}
                />
            </LemonModal>
        </div>
    )
}
