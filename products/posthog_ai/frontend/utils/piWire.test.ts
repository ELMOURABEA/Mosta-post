import { buildPiPermissionCommand, PI_EXTENSION_UI_META_KEY, translatePiWireEntry, withPiOneShotAllow } from './piWire'

describe('piWire', () => {
    test.each([
        {
            caseName: 'user message',
            event: { type: 'user_message', id: 'u1', timestamp: 1, content: [{ type: 'text', text: 'hi' }] },
            expected: { method: '_posthog/user_message', params: { content: [{ type: 'text', text: 'hi' }] } },
        },
        {
            caseName: 'assistant chunk',
            event: { type: 'assistant_message_chunk', timestamp: 1, content: { type: 'text', text: 'yo' } },
            expected: {
                method: 'session/update',
                params: { update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'yo' } } },
            },
        },
        {
            caseName: 'built-in tool start maps to the Claude renderer name and file_path',
            event: {
                type: 'tool_call_started',
                timestamp: 1,
                toolCall: {
                    id: 't1',
                    name: 'read',
                    title: 'read',
                    kind: 'read',
                    status: 'pending',
                    rawInput: { path: 'a.ts' },
                },
            },
            expected: {
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        kind: 'read',
                        status: 'pending',
                        rawInput: { path: 'a.ts', file_path: 'a.ts' },
                        _meta: { posthog: { toolName: 'Read' } },
                    },
                },
            },
        },
        {
            caseName: 'PostHog exec tool start keeps the MCP identity',
            event: {
                type: 'tool_call_started',
                timestamp: 1,
                toolCall: { id: 't2', name: 'posthog_exec', title: 'posthog_exec', rawInput: { command: 'tools' } },
            },
            expected: {
                method: 'session/update',
                params: {
                    update: {
                        sessionUpdate: 'tool_call',
                        toolCallId: 't2',
                        title: 'posthog_exec',
                        rawInput: { command: 'tools' },
                        _meta: {
                            posthog: { toolName: 'mcp__posthog__exec', mcp: { server: 'posthog', tool: 'exec' } },
                        },
                    },
                },
            },
        },
        {
            caseName: 'tool update',
            event: { type: 'tool_call_updated', timestamp: 1, toolCall: { id: 't1', status: 'completed' } },
            expected: {
                method: 'session/update',
                params: { update: { sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' } },
            },
        },
        {
            caseName: 'legacy aborted turn',
            event: { type: 'turn_completed', timestamp: 1, stopReason: 'aborted' },
            expected: { method: '_posthog/turn_complete', params: { stopReason: 'cancelled' } },
        },
        {
            caseName: 'runtime error',
            event: { type: 'runtime_error', timestamp: 1, errorType: 'pi_runtime', message: 'boom' },
            expected: { method: '_posthog/error', params: { message: 'boom', errorType: 'pi_runtime' } },
        },
        {
            caseName: 'retry status',
            event: { type: 'runtime_status', timestamp: 1, status: 'retrying' },
            expected: { method: '_posthog/status', params: { status: 'retrying', isComplete: false } },
        },
    ])('translates a Pi $caseName event', ({ event, expected }) => {
        expect(
            translatePiWireEntry({
                type: 'pi_event',
                event,
                event_id: 'boot-3',
                timestamp: '2026-01-01T00:00:00Z',
                covered_event_ids: ['boot-1', 'boot-2'],
            })
        ).toEqual({
            type: 'notification',
            event_id: 'boot-3',
            timestamp: '2026-01-01T00:00:00Z',
            covered_event_ids: ['boot-1', 'boot-2'],
            notification: expected,
        })
    })

    test.each([
        {
            caseName: 'persisted extension request',
            entry: {
                type: 'pi_extension_event',
                notification: {
                    method: '_posthog/pi_extension_event',
                    params: {
                        type: 'extension_ui_request',
                        id: 'e1',
                        method: 'select',
                        title: 'Pick',
                        options: ['A', 'B'],
                    },
                },
            },
            method: '_posthog/permission_request',
        },
        {
            caseName: 'live extension response',
            entry: { type: 'extension_ui_response', id: 'e1', value: 'A' },
            method: '_posthog/permission_resolved',
        },
        {
            caseName: 'run start marker',
            entry: { type: 'pi_run_started', runId: 'run-1', taskId: 'task-1' },
            method: '_posthog/run_started',
        },
        {
            caseName: 'fire-and-forget notify',
            entry: { type: 'extension_ui_request', id: 'e2', method: 'notify', message: 'Saved' },
            method: '_posthog/console',
        },
    ])('translates a $caseName into $method', ({ entry, method }) => {
        expect(translatePiWireEntry(entry)?.notification.method).toBe(method)
    })

    it('ignores entries that are not Pi wire entries', () => {
        expect(translatePiWireEntry({ type: 'notification', notification: { method: 'session/update' } })).toBeNull()
    })

    it('offers a one-shot allow on a Pi MCP permission request', () => {
        const frame = withPiOneShotAllow({
            type: 'permission_request',
            requestId: 'r1',
            options: [
                { optionId: 'allow_always', name: 'Always allow', kind: 'allow_always' },
                { optionId: 'reject', name: 'Reject', kind: 'reject_once' },
            ],
        })
        expect(frame.options?.map((option) => option.optionId)).toEqual(['allow', 'allow_always', 'reject'])
    })

    test.each([
        {
            caseName: 'an MCP approval',
            meta: { posthog: { toolName: 'mcp__linear__create_issue' } },
            response: { optionId: 'allow' },
            expected: { id: 'cmd-1', type: 'mcp_permission_response', requestId: 'r1', decision: 'allow' },
        },
        {
            caseName: 'a confirmed extension prompt',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'confirm' } },
            response: { optionId: 'confirm' },
            expected: { type: 'extension_ui_response', id: 'e1', confirmed: true },
        },
        {
            caseName: 'a cancelled extension prompt',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'confirm' } },
            response: { optionId: 'cancel' },
            expected: { type: 'extension_ui_response', id: 'e1', cancelled: true },
        },
        {
            caseName: 'an answered extension question',
            meta: { [PI_EXTENSION_UI_META_KEY]: { id: 'e1', method: 'input' } },
            response: { optionId: 'option_0', answers: { 'Branch name?': 'feat/x' } },
            expected: { type: 'extension_ui_response', id: 'e1', value: 'feat/x' },
        },
    ])('builds the Pi command for $caseName', ({ meta, response, expected }) => {
        expect(buildPiPermissionCommand({ requestId: 'r1', meta, options: [] }, response, 'cmd-1')).toEqual(expected)
    })
})
