import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { fixtureSessions } from '../data/fixtures'
import { SessionVideoInfo } from './SessionVideoInfo'
import { SignalInspector } from './SignalInspector'
import { SessionTable } from './SessionTable'

vi.mock('uplot', () => ({ default: class {} }))
vi.mock('./MapRoutePreview', () => ({ MapRoutePreview: () => null }))

afterEach(() => { cleanup(); localStorage.clear() })
const session = { ...fixtureSessions[0], availableSignals: [], signals: [] }
const emptyVideos = { sessionRef: { libraryId: session.libraryId, runId: session.runId, sessionId: session.sessionId }, present: false, revision: 0, attachments: [], createdAtUtc: '', updatedAtUtc: '' }

describe('Session video actions', () => {
  it('shows attachment details and opens management', async () => {
    const onOpenInspector = vi.fn()
    const source = { loadSessionVideoAttachments: vi.fn().mockResolvedValue({ ...emptyVideos, attachments: [
      { attachmentId: 'v1', displayName: 'Helmet clip', cameraLabel: 'Helmet', enabled: false, path: 'C:/clips/ride.mp4', sessionTimeAtVideoZeroS: -12, mediaType: 'video/mp4' },
    ] }) } as unknown as LibraryDataSource
    render(<SessionVideoInfo session={session} dataSource={source} onOpenInspector={onOpenInspector} />)
    expect(await screen.findByText('Helmet clip')).toBeInTheDocument()
    expect(screen.getByText('Disabled')).toBeInTheDocument()
    expect(screen.getByText('-12 s')).toBeInTheDocument()
    expect(screen.getByText('C:/clips/ride.mp4')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Manage video in Signal Inspector'))
    expect(onOpenInspector).toHaveBeenCalledOnce()
  })

  it('opens Browse once, even in StrictMode, and retains the selected path', async () => {
    const browse = vi.fn().mockResolvedValue({ selected: true, path: 'C:/clips/ride.mp4', fileName: 'ride.mp4' })
    const source = {
      loadSessionVideoAttachments: vi.fn().mockResolvedValue(emptyVideos),
      saveSessionVideoAttachments: vi.fn(), selectLocalVideoFile: browse,
    } as unknown as LibraryDataSource
    render(<StrictMode><SignalInspector session={session} dataSource={source} browseVideoOnOpen /></StrictMode>)
    await waitFor(() => expect(browse).toHaveBeenCalledOnce())
    expect(await screen.findByDisplayValue('C:/clips/ride.mp4')).toBeInTheDocument()
    expect(screen.getByText('New video attachment')).toBeInTheDocument()
  })

  it.each([true, false])('offers video and edit-note context actions, present=%s', (present) => {
    const onInspect = vi.fn()
    const item = { ...session, videoSummary: { ...session.videoSummary, present } }
    render(<SessionTable sessions={[item]} filterBaseSessions={[item]} libraries={[]} visibleColumns={['name']} columnWidths={{}} tableColumnFilters={[]} selectedIds={[]} primaryId={null} sortColumn="name" sortDirection="asc" onTableColumnFilterChange={vi.fn()} onClearTableColumnFilter={vi.fn()} onColumnWidthsChange={vi.fn()} onSort={vi.fn()} onSelect={vi.fn()} onInspect={onInspect} />)
    fireEvent.contextMenu(screen.getByText(item.name))
    fireEvent.click(screen.getByText(present ? 'View video info' : 'Add video'))
    expect(onInspect).toHaveBeenLastCalledWith(item, 'video')
    fireEvent.contextMenu(screen.getByText(item.name))
    fireEvent.click(screen.getByText('Edit note'))
    expect(onInspect).toHaveBeenLastCalledWith(item, 'note')
    fireEvent.contextMenu(screen.getByText(item.name))
    fireEvent.click(screen.getByText('Flag and tag...'))
    expect(onInspect).toHaveBeenLastCalledWith(item, 'annotations')
  })
})
