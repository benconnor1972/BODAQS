import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { LibrarySignalCatalog } from '../data/LibraryDataSource'
import { ScenarioColumnPicker } from './ScenarioColumnPicker'

afterEach(cleanup)

const catalog: LibrarySignalCatalog = {
  libraryId: 'test', sessionCount: 10,
  signals: [
    { entryId: 'gyro', streamName: 'imu_native', column: 'gx', unit: 'deg/s', displayName: 'Gyroscope X', displayNames: ['Gyroscope X', 'Roll rate'], sessionCount: 8, sessionFraction: 0.8 },
    { entryId: 'temp', streamName: 'imu_native', column: 'temp', unit: 'C', displayName: 'Temperature', displayNames: [], sessionCount: 5, sessionFraction: 0.5 },
    { entryId: 'primary', streamName: 'primary', column: 'gx', unit: 'rad/s', displayName: 'Primary gyro', displayNames: [], sessionCount: 10, sessionFraction: 1 },
  ],
}

function Picker({ initial = { streamName: 'primary', column: 'gx' }, data = catalog }) {
  const [reference, setReference] = useState(initial)
  return <><ScenarioColumnPicker {...reference} catalog={data} onChange={setReference} /><output>{JSON.stringify(reference)}</output></>
}

describe('ScenarioColumnPicker', () => {
  it('discovers native streams, selects stream-local columns, and shows coverage', async () => {
    const user = userEvent.setup()
    render(<Picker />)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Stream' }), 'imu_native')
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('')
    expect(screen.getByRole('option', { name: /Gyroscope X.*deg\/s.*8\/10 sessions \(80%\)/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Primary gyro/ })).not.toBeInTheDocument()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Column' }), 'gx')
    expect(screen.getByRole('status')).toHaveTextContent('"streamName":"imu_native","column":"gx"')
  })

  it('searches aliases and retains the selected column while filtering', async () => {
    const user = userEvent.setup()
    render(<Picker initial={{ streamName: 'imu_native', column: 'temp' }} />)
    await user.type(screen.getByRole('searchbox', { name: 'Find a column' }), 'roll rate')
    expect(screen.getByRole('option', { name: /Gyroscope X/ })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('temp')
  })

  it('preserves unavailable saved references and allows manual entry', async () => {
    const user = userEvent.setup()
    render(<Picker initial={{ streamName: 'old_sensor', column: 'old_column' }} />)
    expect(screen.getByRole('combobox', { name: 'Stream' })).toHaveValue('old_sensor')
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('old_column')
    expect(screen.getByText(/This reference is retained/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Enter column name' }))
    await user.clear(screen.getByRole('textbox', { name: 'Column' }))
    await user.type(screen.getByRole('textbox', { name: 'Column' }), 'future_column')
    await user.click(screen.getByRole('button', { name: 'Choose from catalog' }))
    expect(screen.getByRole('combobox', { name: 'Column' })).toHaveValue('future_column')
  })

  it('reports unit variants without adding overlapping session counts', () => {
    render(<Picker data={{ ...catalog, signals: [catalog.signals[2], { ...catalog.signals[2], entryId: 'other-unit', unit: 'deg/s', sessionCount: 4, sessionFraction: 0.4 }] }} />)
    expect(screen.getByRole('option', { name: /Primary gyro/ })).toHaveTextContent('rad/s · 10/10 sessions (100%); deg/s · 4/10 sessions (40%)')
    expect(screen.getByText(/Different units occur/)).toBeInTheDocument()
  })
})
