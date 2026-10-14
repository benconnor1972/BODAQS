import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { SavedSessionFilterRecord } from '../domain/sessionFilters'
import { FilterManagerModal } from './FilterManagerModal'
afterEach(cleanup)

it('edits tag lists without splitting commas inside names and saves all matching', async () => {
  const initialDraft: SavedSessionFilterRecord = { id: '', displayName: 'Tags', description: '', category: 'custom', origin: 'api_saved', revision: 0, predicate: { field: 'tags', op: 'all', value: ['wet', 'test, one'] } }
  const onSave = vi.fn().mockImplementation(async (value) => ({ ...value, id: 'saved', revision: 1 }))
  render(<FilterManagerModal filters={[]} tracks={[]} canWrite initialDraft={initialDraft} onClose={vi.fn()} onSave={onSave} onDelete={vi.fn()} />)
  expect(screen.getByLabelText('Tag names (one per line)')).toHaveValue('wet\ntest, one')
  fireEvent.change(screen.getByLabelText('Tag names (one per line)'), { target: { value: 'dry\ntest, two' } })
  fireEvent.click(screen.getByText('Save persisted copy'))
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
  expect(onSave.mock.calls[0][0].predicate).toEqual({ field: 'tags', op: 'all', value: ['dry', 'test, two'] })
})

it('offers user issue flags in the visual builder', async () => {
  const initialDraft: SavedSessionFilterRecord = { id: '', displayName: 'Issues', description: '', category: 'custom', origin: 'api_saved', revision: 0, predicate: { field: 'user.gps_issue', op: 'eq', value: true } }
  const onSave = vi.fn().mockImplementation(async (value) => ({ ...value, id: 'saved', revision: 1 }))
  render(<FilterManagerModal filters={[]} tracks={[]} canWrite initialDraft={initialDraft} onClose={vi.fn()} onSave={onSave} onDelete={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'false' } })
  fireEvent.click(screen.getByText('Save persisted copy'))
  await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
  expect(onSave.mock.calls[0][0].predicate).toEqual({ field: 'user.gps_issue', op: 'eq', value: 'false' })
})
