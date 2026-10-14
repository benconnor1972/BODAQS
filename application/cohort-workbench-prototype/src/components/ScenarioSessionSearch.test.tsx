import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { fixtureSessions } from '../data/fixtures'
import { emptyScenario } from '../domain/scenarios'
import { sessionRefId, sessionToStudyRef } from '../domain/studySets'
import { ScenarioSessionSearch } from './ScenarioSessionSearch'

afterEach(cleanup)

const scenarios = [
  { ...emptyScenario(), id: 'first', revision: 1, displayName: 'Fast riding' },
  { ...emptyScenario(), id: 'second', revision: 2, displayName: 'Slow riding' },
]
const completed = { queryId: 'query', status: 'completed', candidateSessionCount: 1, processedSessionCount: 1, matchedSessionCount: 1, unavailableSessionCount: 0, partialSessionCount: 0, error: null }
function source(overrides = {}) {
  return {
    listScenarios: vi.fn().mockResolvedValue(scenarios),
    createScenarioSessionQuery: vi.fn().mockResolvedValue(completed),
    loadScenarioSessionQuery: vi.fn().mockResolvedValue(completed),
    loadScenarioSessionQueryResults: vi.fn().mockResolvedValue({ results: [{ sessionRef: sessionToStudyRef(fixtureSessions[0]), matchedDurationS: 12 }], resultCount: 1, nextOffset: null }),
    cancelScenarioSessionQuery: vi.fn().mockResolvedValue({ ...completed, status: 'cancelled' }),
    ...overrides,
  } as unknown as LibraryDataSource
}

it('offers single selection without checkboxes and sends the total-duration threshold', async () => {
  const user = userEvent.setup()
  const dataSource = source()
  const onFilter = vi.fn()
  const onAttach = vi.fn()
  render(<ScenarioSessionSearch dataSource={dataSource} sessions={[fixtureSessions[0]]} refreshToken={false} onManage={vi.fn()} onFilter={onFilter} onAttachSession={onAttach} />)
  await user.click(await screen.findByRole('option', { name: 'Fast riding' }))
  await user.click(screen.getByRole('option', { name: 'Slow riding' }))
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.getByRole('option', { name: 'Fast riding' })).toHaveAttribute('aria-selected', 'false')
  expect(screen.getByRole('option', { name: 'Slow riding' })).toHaveAttribute('aria-selected', 'true')
  const input = screen.getByRole('spinbutton', { name: 'Minimum total duration (s)' })
  await user.clear(input)
  await user.type(input, '8.5')
  await user.click(screen.getByRole('button', { name: 'Find matching sessions' }))
  await screen.findByText('12.00 s matching')
  expect(dataSource.createScenarioSessionQuery).toHaveBeenCalledWith(scenarios[1], [sessionToStudyRef(fixtureSessions[0])], 8.5)
  const toggle = screen.getByRole('button', { name: 'Apply scenario filter' })
  expect(toggle.closest('.scenario-search-results')).toBeNull()
  expect(toggle).toHaveAttribute('aria-pressed', 'false')
  await user.click(toggle)
  await waitFor(() => expect(onFilter).toHaveBeenLastCalledWith([sessionRefId(sessionToStudyRef(fixtureSessions[0]))]))
  await user.click(screen.getByRole('button', { name: 'Add session to Study Set' }))
  expect(onAttach).toHaveBeenCalledWith(sessionToStudyRef(fixtureSessions[0]))
  expect(screen.getByRole('button', { name: 'Clear scenario filter' })).toBe(toggle)
  expect(toggle).toHaveAttribute('aria-pressed', 'true')
  await user.click(toggle)
  expect(onFilter).toHaveBeenLastCalledWith(null)
  expect(toggle).toHaveTextContent('Apply scenario filter')
  expect(toggle).toHaveAttribute('aria-pressed', 'false')
})

it('includes all result pages in the applied filter', async () => {
  const user = userEvent.setup()
  const page = vi.fn().mockResolvedValueOnce({ results: [], nextOffset: 100, resultCount: 1 }).mockResolvedValueOnce({ results: [{ sessionRef: sessionToStudyRef(fixtureSessions[1]), matchedDurationS: 20 }], nextOffset: null, resultCount: 1 })
  const onFilter = vi.fn()
  render(<ScenarioSessionSearch dataSource={source({ loadScenarioSessionQueryResults: page })} sessions={fixtureSessions} refreshToken={false} onManage={vi.fn()} onFilter={onFilter} onAttachSession={vi.fn()} />)
  await user.click(await screen.findByRole('option', { name: 'Fast riding' }))
  await user.click(screen.getByRole('button', { name: 'Find matching sessions' }))
  await user.click(await screen.findByRole('button', { name: 'Apply scenario filter' }))
  await waitFor(() => expect(onFilter).toHaveBeenLastCalledWith([sessionRefId(sessionToStudyRef(fixtureSessions[1]))]))
  expect(page).toHaveBeenLastCalledWith('query', 100)
})

it('cancels a running search and shows incomplete/unavailable counts separately', async () => {
  const user = userEvent.setup()
  const dataSource = source({ createScenarioSessionQuery: vi.fn().mockResolvedValue({ ...completed, status: 'running', unavailableSessionCount: 2, partialSessionCount: 3 }) })
  render(<ScenarioSessionSearch dataSource={dataSource} sessions={fixtureSessions} refreshToken={false} onManage={vi.fn()} onFilter={vi.fn()} onAttachSession={vi.fn()} />)
  await user.click(await screen.findByRole('option', { name: 'Fast riding' }))
  await user.click(screen.getByRole('button', { name: 'Find matching sessions' }))
  await screen.findByText(/2 unavailable; 3 incomplete/)
  await user.click(screen.getByRole('button', { name: 'Cancel' }))
  await waitFor(() => expect(dataSource.cancelScenarioSessionQuery).toHaveBeenCalledWith('query'))
  expect(dataSource.loadScenarioSessionQueryResults).not.toHaveBeenCalled()
})

it('does not offer search where the data source lacks query support', async () => {
  render(<ScenarioSessionSearch dataSource={source({ createScenarioSessionQuery: undefined })} sessions={fixtureSessions} refreshToken={false} onManage={vi.fn()} onFilter={vi.fn()} onAttachSession={vi.fn()} />)
  expect(screen.getByRole('button', { name: 'Find matching sessions' })).toBeDisabled()
  expect(screen.getByText('Scenario search is unavailable in this data source.')).toBeInTheDocument()
})

it('applies an empty filter when there are no matching sessions', async () => {
  const user = userEvent.setup()
  const onFilter = vi.fn()
  const dataSource = source({ loadScenarioSessionQueryResults: vi.fn().mockResolvedValue({ results: [], nextOffset: null, resultCount: 0 }) })
  render(<ScenarioSessionSearch dataSource={dataSource} sessions={fixtureSessions} refreshToken={false} onManage={vi.fn()} onFilter={onFilter} onAttachSession={vi.fn()} />)
  await user.click(await screen.findByRole('option', { name: 'Fast riding' }))
  await user.click(screen.getByRole('button', { name: 'Find matching sessions' }))
  await user.click(await screen.findByRole('button', { name: 'Apply scenario filter' }))
  await waitFor(() => expect(onFilter).toHaveBeenLastCalledWith([]))
})
