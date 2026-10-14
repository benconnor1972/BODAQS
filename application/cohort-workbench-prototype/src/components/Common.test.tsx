import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { InfoTip } from './Common'

afterEach(cleanup)

it('gives keyboard users a focusable marker with its help description', () => {
  render(<InfoTip label="About units" text="Values use the recorded units." />)
  const marker = screen.getByRole('img', { name: 'About units' })
  expect(marker).toHaveAttribute('tabindex', '0')
  expect(document.getElementById(marker.getAttribute('aria-describedby')!)).toHaveTextContent('Values use the recorded units.')
  marker.focus()
  expect(marker).toHaveFocus()
})

it('does not toggle an enclosing checkbox when its help marker is clicked', () => {
  render(<label><input type="checkbox" aria-label="Include" />Include <InfoTip text="Help for this option." /></label>)
  fireEvent.click(screen.getByRole('img', { name: 'More information' }))
  expect(screen.getByRole('checkbox', { name: 'Include' })).not.toBeChecked()
})
