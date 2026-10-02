import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { EventAnnotationRecord, EventReference, EventSegment, StudySessionRef, StudySet, TableQueryRow } from '../domain/types'
import { EventBrowser } from './EventBrowser'

const session: StudySessionRef = {
  libraryId: 'library-1',
  runId: 'run-1',
  sessionId: 'session-1',
  sessionKey: 'run-1::session-1',
  label: 'Practice run',
}

const studySet: StudySet = {
  id: 'study-1',
  displayName: 'Suspension setup',
  revision: 1,
  saved: true,
  sessions: [session],
  groupings: [],
  trackIds: [],
  provenance: 'test',
}

function eventRow(eventId: string, triggerTimeS: number, rowIndex: number, tags = ['compression']): TableQueryRow {
  return {
    sessionRef: session,
    setId: 'compression',
    rowIndex,
    eventType: 'compression',
    signalRole: 'front',
    fields: {
      event_id: eventId,
      schema_id: 'compression',
      schema_version: '1',
      trigger_time_s: triggerTimeS,
      compression_start_time_s: triggerTimeS - 0.2,
      params_hash: 'params-hash',
      score: 0.9,
      tags,
    },
  }
}

function eventRef(eventId: string, triggerTimeS: number): EventReference {
  return { ...session, eventSetId: 'compression', eventId, schemaId: 'compression', schemaVersion: '1', schemaDigest: 'sha256:schema-hash', paramsHash: 'params-hash', triggerTimeS }
}

function annotation(eventId: string, triggerTimeS: number, tags: string[]): EventAnnotationRecord {
  return { id: `annotation-${eventId}`, revision: 1, eventRef: eventRef(eventId, triggerTimeS), tags, createdAtUtc: '2026-09-15T00:00:00Z', updatedAtUtc: '2026-09-15T00:00:00Z' }
}

function browserDataSource(rows: TableQueryRow[], metricValues: Array<number | null>, annotations: EventAnnotationRecord[] = []) {
  return {
    queryEventDefinitions: vi.fn(async () => ({
      definitions: [{
        definitionKey: 'digest:compression', schemaId: 'compression', schemaVersion: '1', schemaDigest: 'sha256:schema-hash', displayName: 'Compression', schemaTags: ['compression'], eventSetIds: ['compression'], availableEnds: ['front'], primaryTrigger: { id: 'compression_end' }, secondaryTriggers: [{ id: 'compression_start' }], defaultWindow: { preS: 0.5, postS: 0.5, anchor: 'trigger_time_s' }, defaultRoles: [{ role: 'disp', selector: { quantity: 'disp' } }], metricFields: [{ column: 'm_peak', displayName: 'Peak', unit: 'mm' }], eventCount: rows.length, sessionRefIds: ['library-1|||run-1::session-1'], sessionCount: 1,
      }],
      warnings: [],
    })),
    queryEvents: vi.fn(async () => ({ rowKind: 'event' as const, rowCount: rows.length, rows, warnings: [] })),
    queryMetrics: vi.fn(async () => ({
      rowKind: 'metric' as const,
      rowCount: rows.length,
      rows: rows.map((row, index) => ({ ...row, fields: { event_id: row.fields.event_id, m_peak: metricValues[index] } })),
      warnings: [],
    })),
    queryEventSegments: vi.fn(async (_libraryId: string, request: { events: EventReference[] }) => ({ segments: request.events.map(segment), warnings: [] })),
    listEventAnnotations: vi.fn(async () => annotations),
    listScenarios: vi.fn(async () => []),
  } as unknown as LibraryDataSource
}

function segment(eventRef: EventReference): EventSegment {
  return {
    eventRef,
    window: { returnedStartRelS: -0.5, returnedEndRelS: 0.5 },
    timeRelS: [-0.5, 0, 0.5],
    signals: [{ role: 'disp', column: 'front_disp', displayName: 'Front displacement', end: 'front', domain: 'wheel', quantity: 'disp', unit: 'mm', values: [5, 15, 10] }],
    triggers: [{ id: 'compression_end', kind: 'primary', timeRelS: 0 }, { id: 'compression_start', kind: 'secondary', timeRelS: -0.2 }],
    metrics: { m_peak: 15 },
    qc: { flags: null, score: 0.9 },
    warnings: [],
  }
}

describe('Event Browser', () => {
  beforeEach(() => { cleanup(); window.localStorage.clear() })

  it('navigates with arrow keys, renders schema triggers, prefetches adjacent Events, and opens Signal Inspector', async () => {
    const rows = [eventRow('event-1', 1, 0), eventRow('event-2', 2, 1)]
    const queryEventSegments = vi.fn(async (_libraryId: string, request: { events: EventReference[] }) => ({
      segments: request.events.map(segment),
      warnings: [],
    }))
    const dataSource = {
      queryEventDefinitions: vi.fn(async () => ({
        definitions: [{
          definitionKey: 'digest:compression', schemaId: 'compression', schemaVersion: '1', schemaDigest: 'sha256:schema-hash', displayName: 'Compression', schemaTags: ['compression'], eventSetIds: ['compression'], availableEnds: ['front'], primaryTrigger: { id: 'compression_end' }, secondaryTriggers: [{ id: 'compression_start' }], defaultWindow: { preS: 0.5, postS: 0.5, anchor: 'trigger_time_s' }, defaultRoles: [{ role: 'disp', selector: { quantity: 'disp' } }], metricFields: [{ column: 'm_peak', displayName: 'Peak', unit: 'mm' }], eventCount: 2, sessionRefIds: ['library-1|||run-1::session-1'], sessionCount: 1,
        }],
        warnings: [],
      })),
      queryEvents: vi.fn(async () => ({ rowKind: 'event' as const, rowCount: rows.length, rows, warnings: [] })),
      queryMetrics: vi.fn(async () => ({
        rowKind: 'metric' as const,
        rowCount: 2,
        rows: rows.map((row, index) => ({ ...row, fields: { event_id: row.fields.event_id, m_peak: 15 + index } })),
        warnings: [],
      })),
      queryEventSegments,
      listScenarios: vi.fn(async () => [{
        id: 'scenario-1', revision: 1, displayName: 'First interval', description: '', category: 'test',
        predicate: { criterionId: 'one', series: { streamName: 'primary', column: 'front_disp' }, op: 'present' as const },
        episodePolicy: { minimumDurationS: 0, minimumDistanceM: null, bridgeGapS: 0, bridgeGapM: null }, eligibilityPolicy: { activity: 'ignore' as const },
      }, {
        id: 'scenario-2', revision: 1, displayName: 'Second interval', description: '', category: 'test',
        predicate: { criterionId: 'two', series: { streamName: 'primary', column: 'front_disp' }, op: 'present' as const },
        episodePolicy: { minimumDurationS: 0, minimumDistanceM: null, bridgeGapS: 0, bridgeGapM: null }, eligibilityPolicy: { activity: 'ignore' as const },
      }]),
      evaluateScenario: vi.fn(async (request) => {
        const first = request.scenarioRef?.scenarioId === 'scenario-1'
        return {
          evaluationId: `evaluation-${request.scenarioRef?.scenarioId}`, status: 'succeeded', scenario: { scenarioId: request.scenarioRef?.scenarioId ?? null, revision: 1, displayName: first ? 'First interval' : 'Second interval' }, algorithmVersion: 1,
          sessions: [{ sessionRef: session, status: 'succeeded', episodeCount: 1, matchedDurationS: 1, matchedDistanceM: null, episodes: [{ episodeId: 'episode', ordinal: 0, startTimeS: first ? 0.5 : 1.5, endTimeS: first ? 1.5 : 2.5, durationS: 1, startDistanceM: null, endDistanceM: null, distanceM: null, continuity: {} }], criteria: [], warnings: [] }],
          summary: { requestedSessionCount: 1, evaluatedSessionCount: 1, matchedSessionCount: 1, episodeCount: 1, matchedDurationS: 1, matchedDistanceM: null }, provenance: {}, warnings: [],
        }
      }),
    } as unknown as LibraryDataSource
    const onInspectSignals = vi.fn()
    const user = userEvent.setup()
    render(<EventBrowser studySet={studySet} sessions={[]} dataSource={dataSource} onInspectSignals={onInspectSignals} />)

    expect(await screen.findByText('Event 1 of 2')).toBeInTheDocument()
    expect(await screen.findByText('compression_start')).toBeInTheDocument()
    await waitFor(() => expect(queryEventSegments).toHaveBeenCalled())
    expect(queryEventSegments.mock.calls[0]?.[1].events.map((event) => event.eventId)).toEqual(['event-1', 'event-2'])

    await user.click(document.body)
    await user.keyboard('{ArrowRight}')
    expect(await screen.findByText('Event 2 of 2')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Open in Signal Inspector' }))
    expect(onInspectSignals).toHaveBeenCalledWith(expect.objectContaining({ eventId: 'event-2' }), { startS: 1.5, endS: 2.5 })

    await user.click(await screen.findByRole('checkbox', { name: 'Include First interval (r1)' }))
    expect(await screen.findByText('Compression · 1 of 2 instances')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Include Second interval (r1)' }))
    expect(await screen.findByText('Compression · 2 of 2 instances')).toBeInTheDocument()
  })

  it('filters schema and user tags independently, sorts metrics, pins tagged Events, and restores Study Set settings', async () => {
    const rows = [
      eventRow('event-1', 1, 0, ['compression', 'high-load']),
      eventRow('event-2', 2, 1, ['compression', 'low-load']),
      eventRow('event-3', 3, 2, ['compression', 'high-load']),
    ]
    const annotations = [annotation('event-1', 1, ['interesting']), annotation('event-2', 2, ['interesting']), annotation('event-3', 3, ['outlier'])]
    const dataSource = browserDataSource(rows, [10, 20, null], annotations)
    const user = userEvent.setup()
    const rendered = render(<EventBrowser studySet={studySet} sessions={[]} dataSource={dataSource} />)

    expect(await screen.findByText('Compression · 3 of 3 instances')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Filter schema tag high-load' }))
    expect(await screen.findByText('Compression · 2 of 3 instances')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Filter user tag interesting' }))
    expect(await screen.findByText('Compression · 1 of 3 instances')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Filter schema tag high-load' }))
    expect(await screen.findByText('Compression · 2 of 3 instances')).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Filter user tag interesting' }))

    await user.selectOptions(screen.getByLabelText('Metric filter'), 'm_peak')
    expect(await screen.findByText('1 Event excluded because this metric is missing.')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Sort Events by'), 'm_peak')
    await user.selectOptions(screen.getByLabelText('Sort direction'), 'desc')
    expect(await screen.findByText(/primary trigger at 2\.000 s/)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Pin current' }))
    expect(await screen.findByText(/1 pinned/)).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Tagged Events to add'), 'interesting')
    await user.click(screen.getByRole('button', { name: 'Add filtered matches' }))
    expect(await screen.findByText(/2 pinned/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove event-1 from comparison' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove event-2 from comparison' })).toBeInTheDocument()

    await waitFor(() => {
      const saved = window.localStorage.getItem('bodaqs.event-browser.settings.v1.study-1.r1')
      expect(saved).toContain('"direction":"desc"')
      expect(saved).toContain('event-1')
      expect(saved).toContain('event-2')
    })

    rendered.unmount()
    render(<EventBrowser studySet={studySet} sessions={[]} dataSource={browserDataSource(rows, [10, 20, null], annotations)} />)
    expect(await screen.findByText(/2 pinned/)).toBeInTheDocument()
    expect(screen.getByLabelText('Sort Events by')).toHaveValue('m_peak')
    expect(screen.getByLabelText('Sort direction')).toHaveValue('desc')
  })

  it('caps bulk tagged comparisons at twelve pinned Events', async () => {
    const rows = Array.from({ length: 13 }, (_, index) => eventRow(`event-${index + 1}`, index + 1, index))
    const annotations = rows.map((_, index) => annotation(`event-${index + 1}`, index + 1, ['batch']))
    const user = userEvent.setup()
    render(<EventBrowser studySet={studySet} sessions={[]} dataSource={browserDataSource(rows, rows.map((_, index) => index), annotations)} />)

    expect(await screen.findByText('Compression · 13 of 13 instances')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('Tagged Events to add'), 'batch')
    await user.click(screen.getByRole('button', { name: 'Add filtered matches' }))
    expect(await screen.findByText(/Added 12 tagged Events; 1 omitted by the 12-pin limit/)).toBeInTheDocument()
    expect(screen.getByText(/12 pinned/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove event-13 from comparison' })).not.toBeInTheDocument()
  })
})
