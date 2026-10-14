import { afterEach, describe, expect, it } from 'vitest'
import { chartAxisFont } from './chartTypography'
import { analysisHeading } from './headingTypography'

afterEach(() => {
  document.documentElement.style.removeProperty('--font-ui')
  document.documentElement.style.removeProperty('--text-chart-axis')
})

describe('Chart and heading typography', () => {
  it('uses the UI token stack for canvas/uPlot axes', () => {
    document.documentElement.style.setProperty('--font-ui', 'Aptos, "Segoe UI", sans-serif')
    document.documentElement.style.setProperty('--text-chart-axis', '11px')
    expect(chartAxisFont()).toBe('11px Aptos, "Segoe UI", sans-serif')
  })
  it('keeps a consistent fallback when CSS tokens are unavailable', () => {
    expect(chartAxisFont()).toBe('11px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif')
  })
  it('normalizes built-in analysis names and preserves record names/acronyms', () => {
    expect(analysisHeading('Simple Suspension Analysis')).toBe('Simple suspension analysis')
    expect(analysisHeading('Event Browser')).toBe('Event browser (beta)')
    expect(analysisHeading('BMI270 QA at Maydena')).toBe('BMI270 QA at Maydena')
  })
})
