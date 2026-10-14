const fallbackFont = 'Aptos, "IBM Plex Sans", "Segoe UI", sans-serif'

/** CSS-pixel font shared by canvas and uPlot axes, using the UI tokens. */
export function chartAxisFont() {
  const style = typeof document !== 'undefined' && typeof getComputedStyle !== 'undefined'
    ? getComputedStyle(document.documentElement) : null
  const size = style?.getPropertyValue('--text-chart-axis').trim() || '11px'
  const family = style?.getPropertyValue('--font-ui').trim() || fallbackFont
  return `${size} ${family}`
}
