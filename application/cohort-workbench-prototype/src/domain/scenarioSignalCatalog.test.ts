import { describe, expect, it } from 'vitest'
import { scenarioCatalogFromSessions } from './scenarioSignalCatalog'
import type { SessionRecord } from './types'

describe('scenario catalog fallback', () => {
  it('uses only the chosen library and counts duplicate signals once per session', () => {
    const signal = { column: 'gx', streamName: 'native', unit: 'deg/s', displayName: 'Gyroscope' }
    const sessions = [
      { libraryId: 'test', sessionKey: 'a', availableSignals: [signal, signal] },
      { libraryId: 'test', sessionKey: 'b', availableSignals: [] },
      { libraryId: 'other', sessionKey: 'c', availableSignals: [signal] },
    ] as unknown as SessionRecord[]
    const result = scenarioCatalogFromSessions('test', sessions)
    expect(result.sessionCount).toBe(2)
    expect(result.signals).toHaveLength(1)
    expect(result.signals[0]).toMatchObject({ streamName: 'native', column: 'gx', sessionCount: 1, sessionFraction: 0.5 })
  })
})
