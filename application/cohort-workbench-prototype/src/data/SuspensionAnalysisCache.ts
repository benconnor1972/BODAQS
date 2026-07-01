import type { LibraryDataSource } from './LibraryDataSource'

export type SuspensionCacheStore<T> = {
  entries: Map<string, T>
  inFlight: Map<string, Promise<T>>
  composed: Map<string, unknown>
}

export type SuspensionCacheDiagnostics = {
  requestedSessionCount: number
  cacheHitCount: number
  cacheMissCount: number
  inFlightHitCount: number
  composedCacheHitCount: number
  fetchedSessionCount: number
  fetchBatchCount: number
  fetchDurationMs: number
  composeDurationMs: number
  totalDurationMs: number
}

type InternalCacheStore = SuspensionCacheStore<unknown>

const suspensionCacheByDataSource = new WeakMap<LibraryDataSource, InternalCacheStore>()
const DEFAULT_SESSION_ENTRY_LIMIT = 96
const DEFAULT_COMPOSED_ENTRY_LIMIT = 24

export function suspensionSessionCache<T>(dataSource: LibraryDataSource): SuspensionCacheStore<T> {
  const cached = suspensionCacheByDataSource.get(dataSource)
  if (cached) {
    return cached as SuspensionCacheStore<T>
  }

  const next: InternalCacheStore = {
    entries: new Map<string, unknown>(),
    inFlight: new Map<string, Promise<unknown>>(),
    composed: new Map<string, unknown>(),
  }
  suspensionCacheByDataSource.set(dataSource, next)
  return next as SuspensionCacheStore<T>
}

export function getSuspensionCacheEntry<T>(store: SuspensionCacheStore<T>, key: string) {
  if (!store.entries.has(key)) {
    return null
  }
  const value = store.entries.get(key) ?? null
  if (value !== null) {
    store.entries.delete(key)
    store.entries.set(key, value)
  }
  return value
}

export function setSuspensionCacheEntry<T>(
  store: SuspensionCacheStore<T>,
  key: string,
  value: T,
  limit = DEFAULT_SESSION_ENTRY_LIMIT,
) {
  store.entries.delete(key)
  store.entries.set(key, value)
  pruneOldestEntries(store.entries, limit)
}

export function getSuspensionComposedCacheEntry<T>(store: SuspensionCacheStore<unknown>, key: string) {
  if (!store.composed.has(key)) {
    return null
  }
  const value = (store.composed.get(key) as T | undefined) ?? null
  if (value !== null) {
    store.composed.delete(key)
    store.composed.set(key, value)
  }
  return value
}

export function setSuspensionComposedCacheEntry<T>(
  store: SuspensionCacheStore<unknown>,
  key: string,
  value: T,
  limit = DEFAULT_COMPOSED_ENTRY_LIMIT,
) {
  store.composed.delete(key)
  store.composed.set(key, value)
  pruneOldestEntries(store.composed, limit)
}

export function invalidateSuspensionCacheForSession(dataSource: LibraryDataSource, sessionRefId: string) {
  const store = suspensionCacheByDataSource.get(dataSource)
  if (!store) {
    return
  }
  const refNeedle = `|${sessionRefId}|`
  for (const key of [...store.entries.keys()]) {
    if (key.includes(refNeedle)) {
      store.entries.delete(key)
    }
  }
  for (const key of [...store.inFlight.keys()]) {
    if (key.includes(refNeedle)) {
      store.inFlight.delete(key)
    }
  }
  store.composed.clear()
}

export function clearSuspensionCache(dataSource: LibraryDataSource) {
  const store = suspensionCacheByDataSource.get(dataSource)
  if (!store) {
    return
  }
  store.entries.clear()
  store.inFlight.clear()
  store.composed.clear()
}

export function startSuspensionCacheDiagnostics(requestedSessionCount: number): SuspensionCacheDiagnostics {
  return {
    requestedSessionCount,
    cacheHitCount: 0,
    cacheMissCount: 0,
    inFlightHitCount: 0,
    composedCacheHitCount: 0,
    fetchedSessionCount: 0,
    fetchBatchCount: 0,
    fetchDurationMs: 0,
    composeDurationMs: 0,
    totalDurationMs: -suspensionCacheNowMs(),
  }
}

export function finishSuspensionCacheDiagnostics(diagnostics: SuspensionCacheDiagnostics) {
  diagnostics.totalDurationMs += suspensionCacheNowMs()
  if (debugSuspensionCache()) {
    console.debug('[BODAQS] suspension analysis cache', {
      requested: diagnostics.requestedSessionCount,
      hits: diagnostics.cacheHitCount,
      misses: diagnostics.cacheMissCount,
      inFlightHits: diagnostics.inFlightHitCount,
      composedHits: diagnostics.composedCacheHitCount,
      fetched: diagnostics.fetchedSessionCount,
      batches: diagnostics.fetchBatchCount,
      fetchMs: Math.round(diagnostics.fetchDurationMs),
      composeMs: Math.round(diagnostics.composeDurationMs),
      totalMs: Math.round(diagnostics.totalDurationMs),
    })
  }
}

function pruneOldestEntries<K, V>(entries: Map<K, V>, limit: number) {
  if (limit <= 0) {
    entries.clear()
    return
  }
  while (entries.size > limit) {
    const firstKey = entries.keys().next().value as K | undefined
    if (firstKey === undefined) {
      return
    }
    entries.delete(firstKey)
  }
}

export function suspensionCacheLoadMessage(diagnostics: SuspensionCacheDiagnostics) {
  if (diagnostics.cacheMissCount === 0 && diagnostics.inFlightHitCount === 0) {
    return 'Visualization data loaded from browser cache.'
  }
  if (diagnostics.fetchedSessionCount === 0 && diagnostics.inFlightHitCount > 0) {
    return `Visualization data loaded after waiting for ${diagnostics.inFlightHitCount} in-progress request(s).`
  }
  return `Visualization data loaded (${diagnostics.cacheHitCount} cached, ${diagnostics.fetchedSessionCount} fetched).`
}

function debugSuspensionCache() {
  if (typeof window === 'undefined') {
    return false
  }
  try {
    return window.localStorage.getItem('bodaqs.debug.suspension-cache') === '1'
  } catch {
    return false
  }
}

export function suspensionCacheNowMs() {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now()
  }
  return Date.now()
}
