import type { LibrarySignalCatalog } from '../data/LibraryDataSource'
import type { SessionRecord } from './types'

// Discovery hints only; resolution and ambiguity checks remain in the service.
export function meaningMatches(entry: LibrarySignalCatalog['signals'][number], selector: Record<string, string>) {
  const variants = entry.metadataVariants?.length ? entry.metadataVariants.map((variant) => variant.metadata) : [entry.metadata ?? {}]
  return variants.some((metadata) => Object.entries(selector).every(([key, value]) =>
    String(key === 'unit' ? entry.unit : metadata[key] ?? '').trim().toLowerCase() === value.trim().toLowerCase()))
}

// Older/fixture data sources can supply the same discovery from loaded sessions.
export function scenarioCatalogFromSessions(libraryId: string, sessions: SessionRecord[]): LibrarySignalCatalog {
  const selected = sessions.filter((session) => session.libraryId === libraryId)
  const entries = new Map<string, { signal: LibrarySignalCatalog['signals'][number]; sessions: Set<string> }>()
  for (const session of selected) {
    for (const signal of session.availableSignals ?? []) {
      if (!signal.column) continue
      const streamName = signal.streamName || 'primary'
      const key = JSON.stringify([streamName, signal.column, signal.unit || ''])
      const entry = entries.get(key) ?? {
        signal: { entryId: key, streamName, column: signal.column, unit: signal.unit || '',
          displayName: signal.displayName || signal.column, displayNames: [], sessionCount: 0, sessionFraction: 0,
          metadata: { domain: signal.domain, quantity: signal.quantity, end: signal.end, component: signal.component,
            processing_role: signal.processingRole, kind: signal.kind, sensor: signal.sensor, coordinate_frame: signal.coordinateFrame } },
        sessions: new Set<string>(),
      }
      entry.sessions.add(session.sessionKey)
      entry.signal.displayNames = [...new Set([...entry.signal.displayNames, signal.displayName || signal.column])].sort()
      entries.set(key, entry)
    }
  }
  const total = new Set(selected.map((session) => session.sessionKey)).size
  return {
    libraryId, sessionCount: total,
    signals: [...entries.values()].map(({ signal, sessions: present }) => ({
      ...signal, sessionCount: present.size, sessionFraction: total ? present.size / total : 0,
    })),
  }
}
