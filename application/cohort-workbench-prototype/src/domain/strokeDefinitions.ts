export const BODAQS_STROKE_EVENTS = { compression: 'compressions_all', rebound: 'rebounds_all' } as const
export const BYB_STROKE_EVENTS = { compression: 'compression_byb', rebound: 'rebound_byb' } as const
export const ALL_STROKE_EVENT_TYPES = [...Object.values(BODAQS_STROKE_EVENTS), ...Object.values(BYB_STROKE_EVENTS)]

export function strokeEventTypes(useByb: boolean) {
  return useByb ? BYB_STROKE_EVENTS : BODAQS_STROKE_EVENTS
}

export function strokeEventTypeMatches(value: string, target: string) {
  return value === target || value.startsWith(`${target}_`) || value.startsWith(`${target}>`)
}

export function isCompressionStroke(value: string) {
  return [BODAQS_STROKE_EVENTS.compression, BYB_STROKE_EVENTS.compression].some((type) => strokeEventTypeMatches(value, type))
}

export function isReboundStroke(value: string) {
  return [BODAQS_STROKE_EVENTS.rebound, BYB_STROKE_EVENTS.rebound].some((type) => strokeEventTypeMatches(value, type))
}

// Preserve other events (for example jumps and bottom-outs) when switching strokes.
export function selectStrokeDefinitionRows<T extends { eventType: string }>(rows: T[], useByb: boolean): T[] {
  const selected = Object.values(strokeEventTypes(useByb))
  return rows.filter((row) => !ALL_STROKE_EVENT_TYPES.some((type) => strokeEventTypeMatches(row.eventType, type))
    || selected.some((type) => strokeEventTypeMatches(row.eventType, type)))
}
