import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { SessionRecord } from '../domain/types'
import { SessionDeleteButton } from './SessionInfoButtons'

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
