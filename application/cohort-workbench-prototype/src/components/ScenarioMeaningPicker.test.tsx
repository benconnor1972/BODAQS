import { useState } from 'react'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { LibrarySignalCatalog } from '../data/LibraryDataSource'
import { ScenarioMeaningPicker } from './ScenarioMeaningPicker'
import { meaningMatches } from '../domain/scenarioSignalCatalog'

afterEach(cleanup)

const catalog: LibrarySignalCatalog = { libraryId: 'test', sessionCount: 10, signals: [{
  entryId: 'a', streamName: 'imu_native', column: 'gx', unit: 'deg/s', displayName: 'Gyro X', displayNames: [], sessionCount: 5, sessionFraction: 0.5,
  metadata: { domain: 'motion', quantity: 'angular_velocity', component: 'x' },
  metadataVariants: [{ metadata: { domain: 'motion', quantity: 'angular_velocity', component: 'x', end: 'front' }, sessionCount: 5, sessionFraction: 0.5 }],
}] }

function Picker({ initial = {} }: { initial?: Record<string, string> }) {
  const [reference, setReference] = useState({ streamName: 'imu_native', selector: initial })
  return <><ScenarioMeaningPicker {...reference} catalog={catalog} onChange={setReference} /><output>{JSON.stringify(reference)}</output></>
}

describe('ScenarioMeaningPicker', () => {
  it('offers metadata suggestions and removes blank constraints', async () => {
    const user = userEvent.setup()
    render(<Picker />)
    const domain = screen.getByRole('combobox', { name: 'Domain' })
    expect(document.getElementById(domain.getAttribute('list')!)?.textContent).toBe('')
    expect(document.getElementById(domain.getAttribute('list')!)?.querySelector('option')?.value).toBe('motion')
    await user.type(domain, 'motion')
    await user.type(screen.getByRole('combobox', { name: 'Component' }), 'x')
    expect(screen.getByText(/Matching catalog entries: gx/)).toBeInTheDocument()
    await user.clear(domain)
    expect(screen.getByRole('status')).toHaveTextContent('"selector":{"component":"x"}')
  })

  it('preserves metadata attributes absent from the library catalog', () => {
    render(<Picker initial={{ domain: 'control', control: 'rear_brake' }} />)
    expect(screen.getByRole('combobox', { name: 'control' })).toHaveValue('rear_brake')
    expect(screen.getByText(/No matching metadata/)).toBeInTheDocument()
  })

  it('uses metadata variants for suggestions without claiming unique resolution', () => {
    expect(meaningMatches(catalog.signals[0], { end: ' FRONT ', unit: 'deg/s' })).toBe(true)
    expect(meaningMatches(catalog.signals[0], { end: 'rear' })).toBe(false)
    expect(meaningMatches(catalog.signals[0], { unit: 'rad/s' })).toBe(false)
  })
})
