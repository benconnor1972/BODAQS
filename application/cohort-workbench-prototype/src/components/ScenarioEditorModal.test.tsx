import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LibraryDataSource, LibrarySignalCatalog } from '../data/LibraryDataSource'
import { emptyScenario } from '../domain/scenarios'
import { scenarioBuilderFromPredicate, scenarioPredicateFromBuilder } from '../domain/scenarioPredicateBuilder'
import type { ScenarioRecord } from '../domain/types'
import { ScenarioEditorModal } from './ScenarioEditorModal'

afterEach(cleanup)

const catalog: LibrarySignalCatalog = {
  libraryId: 'test', sessionCount: 10,
  signals: [{ entryId: 'gyro', streamName: 'imu_native', column: 'gx', unit: 'deg/s', displayName: 'Gyroscope X', displayNames: [], sessionCount: 8, sessionFraction: 0.8 }],
}

function source(overrides = {}) {
  return {
    listLibraries: vi.fn().mockResolvedValue([{ id: 'test', name: 'Test library' }]),
    loadLibrarySignalCatalog: vi.fn().mockResolvedValue(catalog),
    saveScenario: vi.fn().mockImplementation(async (scenario) => ({ ...scenario, id: 'saved', revision: 1 })),
    ...overrides,
  } as unknown as LibraryDataSource
}

describe('ScenarioEditorModal column discovery', () => {
  it('creates a meaning selector from a chosen catalog signal', async () => {
    const user = userEvent.setup()
    const dataSource = source({ loadLibrarySignalCatalog: vi.fn().mockResolvedValue({
      ...catalog, signals: [{ ...catalog.signals[0], metadata: { domain: 'motion', quantity: 'angular_velocity', component: 'x' } }],
    }) })
    render(<ScenarioEditorModal dataSource={dataSource} canWrite onClose={vi.fn()} />)
    await screen.findByText(/10 sessions in the suggestion catalog/)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Metric' }), 'custom')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Stream' }), 'imu_native')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Column' }), 'gx')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Metric' }), 'meaning')
    expect(screen.getByRole('combobox', { name: 'Domain' })).toHaveValue('motion')
    expect(screen.getByRole('combobox', { name: 'Unit' })).toHaveValue('deg/s')
    await user.click(screen.getByRole('button', { name: 'Advanced JSON' }))
    expect(JSON.parse((screen.getByRole('textbox', { name: 'Advanced definition JSON' }) as HTMLTextAreaElement).value).predicate.series).toEqual({
      stream_name: 'imu_native', selector: { domain: 'motion', quantity: 'angular_velocity', component: 'x', unit: 'deg/s' },
    })
  })

  it('offers Choose by meaning below Custom column and saves a semantic selector', async () => {
    const user = userEvent.setup()
    const dataSource = source()
    const scenario: ScenarioRecord = { ...emptyScenario(), displayName: 'Rear wheel', predicate: {
      criterionId: 'rear', series: { streamName: 'primary', selector: { domain: 'wheel', quantity: 'disp_norm', end: 'rear', unit: '1' } }, op: 'gte', value: 0.5,
    } }
    render(<ScenarioEditorModal initialScenario={scenario} dataSource={dataSource} canWrite onClose={vi.fn()} />)
    await screen.findByText(/10 sessions in the suggestion catalog/)
    const metric = screen.getByRole('combobox', { name: 'Metric' })
    expect(metric).toHaveValue('meaning')
    const choices = [...(metric as HTMLSelectElement).options].map((option) => option.text)
    expect(choices[choices.indexOf('Custom column') + 1]).toBe('Choose by meaning')
    expect(screen.getByRole('combobox', { name: 'Front / rear' })).toHaveValue('rear')
    await user.clear(screen.getByRole('combobox', { name: 'Front / rear' }))
    await user.type(screen.getByRole('combobox', { name: 'Front / rear' }), 'front')
    await user.click(screen.getByRole('button', { name: 'Advanced JSON' }))
    expect(JSON.parse((screen.getByRole('textbox', { name: 'Advanced definition JSON' }) as HTMLTextAreaElement).value).predicate.series).toEqual({
      stream_name: 'primary', selector: { domain: 'wheel', quantity: 'disp_norm', end: 'front', unit: '1' },
    })
    await user.click(screen.getByRole('button', { name: 'Try visual builder' }))
    await user.click(screen.getByRole('button', { name: 'Save persisted' }))
    await waitFor(() => expect(dataSource.saveScenario).toHaveBeenCalled())
    const saved = vi.mocked(dataSource.saveScenario!).mock.calls[0][0]
    expect(saved.predicate).toMatchObject({ series: { streamName: 'primary', selector: { domain: 'wheel', end: 'front' } } })
    expect('children' in saved.predicate ? saved.predicate : saved.predicate.series).not.toHaveProperty('column')
  })

  it('loads the library catalog and saves a native stream reference without binding a library', async () => {
    const user = userEvent.setup()
    const dataSource = source()
    render(<ScenarioEditorModal dataSource={dataSource} canWrite onClose={vi.fn()} />)
    await screen.findByText(/10 sessions in the suggestion catalog/)
    expect(dataSource.loadLibrarySignalCatalog).toHaveBeenCalledWith('test')
    await user.type(screen.getByRole('textbox', { name: 'Name' }), 'Fast rotation')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Metric' }), 'custom')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Stream' }), 'imu_native')
    await user.selectOptions(screen.getByRole('combobox', { name: 'Column' }), 'gx')
    await user.clear(screen.getByRole('textbox', { name: 'Value (deg/s)' }))
    await user.type(screen.getByRole('textbox', { name: 'Value (deg/s)' }), '20')
    await user.click(screen.getByRole('button', { name: 'Advanced JSON' }))
    const definition = screen.getByRole('textbox', { name: 'Advanced definition JSON' })
    expect(JSON.parse((definition as HTMLTextAreaElement).value).predicate.series).toEqual({ stream_name: 'imu_native', column: 'gx' })
    await user.click(screen.getByRole('button', { name: 'Try visual builder' }))
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('gx')
    await user.click(screen.getByRole('button', { name: 'Save persisted' }))
    await waitFor(() => expect(dataSource.saveScenario).toHaveBeenCalled())
    const saved = vi.mocked(dataSource.saveScenario!).mock.calls[0][0]
    expect(saved.predicate).toMatchObject({ series: { streamName: 'imu_native', column: 'gx' }, value: 20 })
    expect(saved).not.toHaveProperty('libraryId')
  })

  it('keeps existing native references when catalog loading fails', async () => {
    const scenario: ScenarioRecord = { ...emptyScenario(), displayName: 'Old scenario', predicate: { criterionId: 'old', series: { streamName: 'old_imu', column: 'gyro_z' }, op: 'gte', value: 3 } }
    render(<ScenarioEditorModal initialScenario={scenario} dataSource={source({ loadLibrarySignalCatalog: vi.fn().mockRejectedValue(new Error('Offline')) })} canWrite onClose={vi.fn()} />)
    await screen.findByText(/Could not load column suggestions: Offline/)
    expect(screen.getByRole('combobox', { name: 'Stream' })).toHaveValue('old_imu')
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('gyro_z')
    expect(scenarioPredicateFromBuilder(scenarioBuilderFromPredicate(scenario.predicate)!)).toEqual(scenario.predicate)
  })

  it('ignores a late catalog response after switching the suggestion library', async () => {
    const user = userEvent.setup()
    let resolveFirst!: (data: LibrarySignalCatalog) => void
    const dataSource = source({
      listLibraries: vi.fn().mockResolvedValue([{ id: 'test', name: 'First library' }, { id: 'second', name: 'Second library' }]),
      loadLibrarySignalCatalog: vi.fn().mockImplementation((id: string) => id === 'test'
        ? new Promise<LibrarySignalCatalog>((resolve) => { resolveFirst = resolve })
        : Promise.resolve({ ...catalog, libraryId: 'second', sessionCount: 2 })),
    })
    render(<ScenarioEditorModal dataSource={dataSource} canWrite onClose={vi.fn()} />)
    await waitFor(() => expect(dataSource.loadLibrarySignalCatalog).toHaveBeenCalledWith('test'))
    await user.selectOptions(screen.getByRole('combobox', { name: 'Signal catalog library' }), 'second')
    await screen.findByText(/2 sessions in the suggestion catalog/)
    resolveFirst(catalog)
    await waitFor(() => expect(screen.queryByText(/10 sessions in the suggestion catalog/)).not.toBeInTheDocument())
  })
})
