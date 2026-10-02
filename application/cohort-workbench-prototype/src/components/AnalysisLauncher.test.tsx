import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { AnalysisAdequacyResult, AnalysisViewRecord, StudySet } from '../domain/types'
import { AnalysisLauncher } from './AnalysisLauncher'

const views: AnalysisViewRecord[] = [
  analysisView('simple-suspension', 'Simple Suspension Analysis'),
  analysisView('suspension-phase-diagram', 'Suspension Phase Diagram'),
]

const studySet: StudySet = {
  id: 'test-study',
  displayName: 'Test study',
  revision: 1,
  saved: true,
  sessions: [],
  groupings: [],
  trackIds: [],
  provenance: 'test',
}

describe('AnalysisLauncher', () => {
  it('sends every selected view to the bulk launcher and waits for completion', async () => {
    const user = userEvent.setup()
    const onOpenAnalyses = vi.fn().mockResolvedValue([])
    const onClose = vi.fn()
    const dataSource = {
      listAnalysisViews: async () => views,
      evaluateAnalysisAdequacy: async (viewId: string) => readyAdequacy(viewId),
    } as unknown as LibraryDataSource

    render(
      <AnalysisLauncher
        dataSource={dataSource}
        onClose={onClose}
        onOpenAnalyses={onOpenAnalyses}
        onOpenAnalysis={vi.fn()}
        studySet={studySet}
        tracks={[]}
      />,
    )

    await user.click(await screen.findByRole('checkbox', { name: 'Select Simple Suspension Analysis' }))
    await user.click(screen.getByRole('checkbox', { name: 'Select Suspension Phase Diagram' }))
    await user.click(screen.getByRole('button', { name: 'Open all selected' }))

    await waitFor(() => expect(onOpenAnalyses).toHaveBeenCalledWith(
      ['simple-suspension', 'suspension-phase-diagram'],
      studySet,
    ))
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce())
  })
})

function analysisView(id: string, displayName: string): AnalysisViewRecord {
  return {
    id,
    displayName,
    category: 'Suspension',
    description: `${displayName} description`,
    route: id,
    adequacyPolicy: 'partial',
    requirements: { required: [], recommended: [], optional: [] },
  }
}

function readyAdequacy(viewId: string): AnalysisAdequacyResult {
  return {
    viewId,
    displayName: views.find((view) => view.id === viewId)?.displayName ?? viewId,
    status: 'ready',
    policy: 'partial',
    summary: 'Ready',
    totalSessionCount: 0,
    usableSessionCount: 0,
    blockedSessionCount: 0,
    messages: [],
    sessionResults: [],
    scopeCriteria: [],
  }
}
