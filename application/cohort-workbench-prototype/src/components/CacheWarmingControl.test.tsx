import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { CacheWarmingControl } from './CacheWarmingControl'

afterEach(cleanup)
const status = { enabled: true, read_only: false, state: 'idle', current: null, completed_units: 0, failed_units: 0, last_error: null }

it('pauses and enables warming and updates the status', async () => {
  const user = userEvent.setup()
  const source = {
    loadCacheWarmingStatus: vi.fn().mockResolvedValue(status),
    setCacheWarmingEnabled: vi.fn().mockImplementation(async (enabled) => ({ ...status, enabled, state: enabled ? 'idle' : 'disabled' })),
  } as unknown as LibraryDataSource
  render(<CacheWarmingControl dataSource={source} />)
  await user.click(await screen.findByRole('button', { name: 'Pause' }))
  expect(source.setCacheWarmingEnabled).toHaveBeenCalledWith(false)
  await screen.findByText('Cache warming: disabled')
  await user.click(screen.getByRole('button', { name: 'Enable' }))
  expect(source.setCacheWarmingEnabled).toHaveBeenLastCalledWith(true)
  await screen.findByText('Cache warming: idle')
})

it('does not expose enable controls for read-only services', async () => {
  render(<CacheWarmingControl dataSource={{ loadCacheWarmingStatus: vi.fn().mockResolvedValue({ ...status, enabled: false, read_only: true, state: 'disabled' }) } as unknown as LibraryDataSource} />)
  await screen.findByText('Cache warming: disabled')
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('hides the optional control when an older service does not support it', async () => {
  const load = vi.fn().mockRejectedValue(new Error('Not found'))
  const { container } = render(<CacheWarmingControl dataSource={{ loadCacheWarmingStatus: load } as unknown as LibraryDataSource} />)
  await waitFor(() => expect(load).toHaveBeenCalledOnce())
  expect(container).toBeEmptyDOMElement()
})
