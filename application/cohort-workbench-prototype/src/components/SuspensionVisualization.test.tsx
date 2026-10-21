import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { SignalQueryRequest, StudySessionRef, StudySet, TableQueryRow } from '../domain/types'
import { ALL_STROKE_EVENT_TYPES } from '../domain/strokeDefinitions'
import { SuspensionVisualization } from './SuspensionVisualization'

afterEach(() => { cleanup(); window.localStorage.clear(); vi.restoreAllMocks() })

const session: StudySessionRef = { libraryId: 'library', runId: 'run', sessionId: 'session', sessionKey: 'run::session', label: 'Practice' }
function study(id: string): StudySet {
  return { id, displayName: id, revision: 1, saved: true, sessions: [session], groupings: [], trackIds: [], provenance: 'test' }
}

function source(includeByb = true) {
  const rows: TableQueryRow[] = ALL_STROKE_EVENT_TYPES.filter((type) => includeByb || !type.endsWith('_byb')).flatMap((type) =>
    (['front', 'rear'] as const).map((end) => ({
      sessionRef: session, setId: type, rowIndex: 0, eventType: type, signalRole: end,
      fields: { event_id: `${type}:${end}:0`, trigger_time_s: 2, m_interval_vel_max: type.endsWith('_byb') ? 1200 : 800,
        m_interval_vel_min: type.endsWith('_byb') ? -600 : -400, m_stroke_disp_max: 50, m_stroke_disp_range: type.endsWith('_byb') ? 12 : 32 },
    })),
  )
  return {
    querySignals: vi.fn(async (_library: string, request: SignalQueryRequest) => ({
      sessions: [{ sessionRef: session, time: { column: 'time_s', unit: 's', values: [0, 1, 2, 3, 4] },
        sampling: { mode: 'native', sourcePoints: 5, returnedPoints: 5, distributionCorrect: true },
        signals: request.signals.map((signal) => ({ ...signal.selector, role: signal.role, column: signal.role,
          signalId: signal.role, values: signal.role === 'active_mask_qc' ? [1, 1, 1, 1, 1] : [0, .2, .4, .2, 0] })) }], warnings: [],
    })),
    queryEvents: vi.fn(async () => ({ rows, warnings: [] })),
    queryMetrics: vi.fn(async () => ({ rows, warnings: [] })),
  } as unknown as LibraryDataSource
}

it('defaults to BYB strokes and switches cached metrics, stroke lengths and balance points together', async () => {
  const dataSource = source()
  const studySet = study('stroke-switch')
  const user = userEvent.setup()
  const props = { studySet, dataSource, sessions: [], tracks: [] }
  const view = render(<SuspensionVisualization {...props} />)
  await screen.findAllByText('max 1200 mm/s')
  expect(screen.queryByText('max 800 mm/s')).not.toBeInTheDocument()
  expect(screen.getAllByText('max 12.0 mm').length).toBeGreaterThan(0)
  expect(view.container.querySelector('svg[aria-label$="Compression velocity (mm/s)"] circle title')?.textContent).toContain('1200')
  expect(dataSource.queryMetrics).toHaveBeenCalledWith('library', expect.objectContaining({ eventTypes: ALL_STROKE_EVENT_TYPES }))
  await user.click(screen.getByRole('button', { name: 'Select and filter' }))
  const checkbox = screen.getByRole('checkbox', { name: 'Use BYB stroke definition' })
  expect(checkbox).toBeChecked()
  expect(screen.getByText('Compatibility')).toBeInTheDocument()
  await user.click(checkbox)
  await screen.findAllByText('max 800 mm/s')
  expect(screen.queryByText('max 1200 mm/s')).not.toBeInTheDocument()
  expect(screen.getAllByText('max 32.0 mm').length).toBeGreaterThan(0)
  expect(view.container.querySelector('svg[aria-label$="Compression velocity (mm/s)"] circle title')?.textContent).toContain('800')
  expect(dataSource.queryMetrics).toHaveBeenCalledOnce()
  view.unmount()
  render(<SuspensionVisualization {...props} />)
  await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Use BYB stroke definition' })).not.toBeChecked())
  await screen.findAllByText('max 800 mm/s')
  expect(dataSource.queryMetrics).toHaveBeenCalledOnce()
})

it('explains missing BYB metrics in older sessions without substituting BODAQS strokes', async () => {
  const user = userEvent.setup()
  render(<SuspensionVisualization studySet={study('legacy-strokes')} sessions={[]} tracks={[]} dataSource={source(false)} />)
  await screen.findByText(/BYB-style stroke metrics are missing/)
  expect(screen.queryByText('max 800 mm/s')).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Select and filter' }))
  await user.click(screen.getByRole('checkbox', { name: 'Use BYB stroke definition' }))
  await screen.findAllByText('max 800 mm/s')
  expect(screen.queryByText(/stroke metrics are missing/)).not.toBeInTheDocument()
})

it('keeps the phase diagram on continuous signals without requesting stroke metrics', async () => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  const dataSource = source()
  render(<SuspensionVisualization studySet={study('phase-strokes')} sessions={[]} tracks={[]} dataSource={dataSource} mode="phase" />)
  await waitFor(() => expect(dataSource.querySignals).toHaveBeenCalled())
  expect(dataSource.queryMetrics).not.toHaveBeenCalled()
  expect(dataSource.queryEvents).not.toHaveBeenCalled()
  expect(screen.queryByRole('checkbox', { name: 'Use BYB stroke definition' })).not.toBeInTheDocument()
})
