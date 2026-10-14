import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fixtureSessions } from '../data/fixtures'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { emptySessionAnnotations } from '../domain/sessionAnnotations'
import { SessionAnnotationEditor } from './SessionAnnotationEditor'

afterEach(cleanup)
const session = fixtureSessions[0]
function setup(canWrite = true, failure = false) {
  const record = { ...emptySessionAnnotations(session), revision: 3, tags: ['wet'], qaIssue: { flagged: true, explanation: 'Noisy' } }
  const save = failure ? vi.fn().mockRejectedValue(new Error('Revision conflict')) : vi.fn().mockImplementation(async (value) => ({ ...value, revision: 4 }))
  const source = { loadSessionUserAnnotations: vi.fn().mockResolvedValue(record), saveSessionUserAnnotations: save } as unknown as LibraryDataSource
  const onSaved = vi.fn(), onClose = vi.fn()
  render(<SessionAnnotationEditor session={session} dataSource={source} canWrite={canWrite} knownTags={['wet', 'dry']} onSaved={onSaved} onClose={onClose} />)
  return { save, onSaved, onClose }
}
describe('Session annotation editing', () => {
  it('flags, explains and tags while preserving the other issue and revision', async () => {
    const { save, onSaved } = setup()
    const checkbox = await screen.findByLabelText('Flag GPS issue')
    expect(checkbox).not.toBeChecked()
    fireEvent.click(checkbox)
    fireEvent.change(screen.getByLabelText('GPS issue explanation (optional)'), { target: { value: 'Wrong trail' } })
    fireEvent.change(screen.getByLabelText('New tag'), { target: { value: ' DRY ' } })
    fireEvent.click(screen.getByText('Add tag'))
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
    expect(save.mock.calls[0][0]).toMatchObject({ revision: 3, tags: ['dry', 'wet'], gpsIssue: { flagged: true, explanation: 'Wrong trail' }, qaIssue: { flagged: true, explanation: 'Noisy' } })
  })
  it('allows clearing an issue and retains edits after failed save', async () => {
    const { onClose } = setup(true, true)
    expect(await screen.findByLabelText('Flag GPS issue')).not.toBeChecked()
    fireEvent.change(screen.getByLabelText('GPS issue explanation (optional)'), { target: { value: 'My explanation' } })
    fireEvent.click(screen.getByText('Save'))
    expect(await screen.findByText(/Revision conflict/)).toBeInTheDocument()
    expect(screen.getByLabelText('Flag GPS issue')).not.toBeChecked()
    expect(screen.getByDisplayValue('My explanation')).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('Reload saved annotations'))
    expect(await screen.findByLabelText('Flag GPS issue')).not.toBeChecked()
    expect(screen.getByLabelText('GPS issue explanation (optional)')).toHaveValue('')
  })
  it('disables editing without changing the displayed flag in read-only mode', async () => {
    setup(false)
    expect(await screen.findByLabelText('Flag GPS issue')).not.toBeChecked()
    expect(screen.getByLabelText('Flag GPS issue')).toBeDisabled()
    expect(screen.getByText('Save')).toBeDisabled()
  })
})
