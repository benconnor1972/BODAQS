import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { AnalysisControlDrawer, AnalysisEndPicker, AnalysisEntityPicker, AnalysisScenarioPicker } from './AnalysisControls'

describe('shared analysis controls', () => {
  it('provides the common drawer, entity, end, and Scenario interactions', async () => {
    const user = userEvent.setup()
    const onDrawerToggle = vi.fn()
    const onEntityToggle = vi.fn()
    const onEndToggle = vi.fn()
    const onScenarioToggle = vi.fn()
    render(
      <AnalysisControlDrawer collapsed={false} summary="2 sessions · 4 Events" infoText="Shared controls" onToggle={onDrawerToggle}>
        <AnalysisEntityPicker
          entities={[{ id: 'session-1', kind: 'session', label: 'Practice run' }, { id: 'group-1', kind: 'grouping', label: 'Baseline', memberCount: 2 }]}
          selectedIds={['session-1']}
          onToggle={onEntityToggle}
        />
        <AnalysisEndPicker ends={[{ id: 'front', label: 'Front', color: '#008c95' }]} selectedIds={['front']} onToggle={onEndToggle} />
        <AnalysisScenarioPicker options={[{ id: 'rough', label: 'Rough trail' }]} selectedIds={[]} onToggle={onScenarioToggle} />
      </AnalysisControlDrawer>,
    )

    await user.click(screen.getByRole('button', { name: 'Practice run' }))
    await user.click(screen.getByRole('button', { name: 'Front' }))
    await user.click(screen.getByRole('checkbox', { name: 'Include Rough trail' }))
    await user.click(screen.getByRole('button', { name: /Select and Filter/i }))

    expect(onEntityToggle).toHaveBeenCalledWith('session-1')
    expect(onEndToggle).toHaveBeenCalledWith('front')
    expect(onScenarioToggle).toHaveBeenCalledWith('rough', true)
    expect(onDrawerToggle).toHaveBeenCalledOnce()
  })
})
