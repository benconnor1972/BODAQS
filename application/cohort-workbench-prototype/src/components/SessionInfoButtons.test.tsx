import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionRecord } from '../domain/types'
import { SessionDeleteButton, SessionInfoButtons } from './SessionInfoButtons'

afterEach(cleanup)

describe('Video glyph', () => {
  it.each([true, false])('opens video action when present=%s', (present) => {
    const onInspect = vi.fn()
    const session = { videoSummary: { present, attachmentCount: present ? 2 : 0, enabledCount: 1 } } as SessionRecord
    render(<SessionInfoButtons session={session} actions={['video']} onInspect={onInspect} />)
    const button = screen.getByRole('button')
    expect(button).toBeEnabled()
    fireEvent.click(button)
    expect(onInspect).toHaveBeenCalledWith(session, 'video')
  })
})

describe('SessionDeleteButton', () => {
  it('shows and disables the pending delete state', () => {
    render(
      <SessionDeleteButton
        session={{ name: 'Test session' } as SessionRecord}
        onDelete={vi.fn()}
        pending
      />,
    )

    expect(screen.getByRole('button', { name: 'Deleting session' })).toBeDisabled()
  })
})
