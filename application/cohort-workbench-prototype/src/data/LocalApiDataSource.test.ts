import { afterEach, describe, expect, it, vi } from 'vitest'
import { LocalApiDataSource } from './LocalApiDataSource'
import { fixtureSessions } from './fixtures'
import { emptySessionAnnotations } from '../domain/sessionAnnotations'
import { emptyScenario } from '../domain/scenarios'
import { sessionToStudyRef } from '../domain/studySets'

afterEach(() => vi.unstubAllGlobals())

it('maps scenario search requests, progress and paginated duration summaries', async () => {
  const record = { query_id: 'query', status: 'completed', candidate_session_count: 1, processed_session_count: 1, matched_session_count: 1, unavailable_session_count: 0, partial_session_count: 0, error: null }
  const ref = sessionToStudyRef(fixtureSessions[0])
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(record), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ result_count: 1, next_offset: null, results: [{ session_ref: { library_id: ref.libraryId, run_id: ref.runId, session_id: ref.sessionId, session_key: ref.sessionKey }, matched_duration_s: 8.5 }] }), { status: 200 }))
  vi.stubGlobal('fetch', fetch)
  const source = new LocalApiDataSource('http://localhost:8765')
  const query = await source.createScenarioSessionQuery({ ...emptyScenario(), id: 'fast', revision: 4 }, [ref], 5)
  expect(query).toMatchObject({ queryId: 'query', status: 'completed', matchedSessionCount: 1 })
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ scenario_ref: { scenario_id: 'fast', revision: 4 }, sessions: [{ library_id: ref.libraryId, run_id: ref.runId, session_id: ref.sessionId, session_key: ref.sessionKey }], minimum_total_duration_s: 5 })
  const page = await source.loadScenarioSessionQueryResults('query', 100)
  expect(fetch.mock.calls[1][0]).toContain('/query/results?offset=100&limit=100')
  expect(page).toMatchObject({ nextOffset: null, resultCount: 1, results: [{ sessionRef: { sessionKey: ref.sessionKey }, matchedDurationS: 8.5 }] })
})

it('loads and saves annotations with the loaded revision and editable fields only', async () => {
  const session = fixtureSessions[0]
  const response = { present: true, annotations: { revision: 4, tags: ['wet'], gps_issue: { flagged: true, explanation: 'Wrong location' }, qa_issue: { flagged: false, explanation: '' } } }
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } }))
  vi.stubGlobal('fetch', fetch)
  const source = new LocalApiDataSource('http://localhost:8765')
  const loaded = await source.loadSessionUserAnnotations(session)
  expect(loaded).toMatchObject({ revision: 4, tags: ['wet'], gpsIssue: { flagged: true, explanation: 'Wrong location' } })
  await source.saveSessionUserAnnotations({ ...emptySessionAnnotations(session), ...loaded })
  expect(fetch.mock.calls[0][0]).toContain('/user-annotations')
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ expected_revision: 4, annotations: { tags: ['wet'], gps_issue: { flagged: true, explanation: 'Wrong location' }, qa_issue: { flagged: false, explanation: '' } } })
})

describe('library signal catalog transport', () => {
  it('loads library-scoped summary metadata, units and coverage from the API', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      library_id: 'test/library', session_count: 10,
      signals: [{ entry_id: 'entry', stream_name: 'imu_native', column: 'gx', unit: 'deg/s',
        display_name: 'Gyroscope X', display_names: ['Gyroscope X'], session_count: 8, session_fraction: 0.8,
        metadata: { domain: 'motion' }, metadata_variants: [{ metadata: { domain: 'motion', component: 'x' }, session_count: 8, session_fraction: 0.8 }] }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetch)
    const result = await new LocalApiDataSource('http://localhost:8765/').loadLibrarySignalCatalog('test/library')
    expect(fetch.mock.calls[0][0]).toBe('http://localhost:8765/api/v1/libraries/test%2Flibrary/signal-catalog')
    expect(result).toEqual({ libraryId: 'test/library', sessionCount: 10, signals: [{
      entryId: 'entry', streamName: 'imu_native', column: 'gx', unit: 'deg/s', displayName: 'Gyroscope X',
      displayNames: ['Gyroscope X'], sessionCount: 8, sessionFraction: 0.8,
      metadata: { domain: 'motion' }, metadataVariants: [{ metadata: { domain: 'motion', component: 'x' }, sessionCount: 8, sessionFraction: 0.8 }],
    }] })
  })

  it('reports API failure instead of treating the failed load as an empty catalog', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ message: 'Unavailable' }), { status: 503 })))
    await expect(new LocalApiDataSource('http://localhost:8765').loadLibrarySignalCatalog('test')).rejects.toThrow()
  })
})
