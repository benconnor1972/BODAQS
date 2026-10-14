import { useEffect, useRef, useState } from 'react'
import { ListFilter, Plus, Search } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { ScenarioRecord, ScenarioSessionQuery, ScenarioSessionQueryPage, SessionRecord, StudySessionRef } from '../domain/types'
import { sessionRefId, sessionToStudyRef } from '../domain/studySets'
import { IconButton, InfoTip } from './Common'

export function ScenarioSessionSearch({ dataSource, sessions, refreshToken, onManage, onFilter, onAttachSession }: {
  dataSource: LibraryDataSource
  sessions: SessionRecord[]
  refreshToken: boolean
  onManage: () => void
  onFilter: (ids: string[] | null) => void
  onAttachSession: (ref: StudySessionRef) => void
}) {
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [minimum, setMinimum] = useState('0')
  const [query, setQuery] = useState<ScenarioSessionQuery | null>(null)
  const [results, setResults] = useState<ScenarioSessionQueryPage | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [filterApplied, setFilterApplied] = useState(false)
  const sequence = useRef(0)
  const queryId = useRef<string | null>(null)
  const filterCallback = useRef(onFilter)
  useEffect(() => { filterCallback.current = onFilter }, [onFilter])
  const selected = scenarios.find((scenario) => scenario.id === selectedId)
  const threshold = Number(minimum)
  const available = Boolean(dataSource.createScenarioSessionQuery && dataSource.loadScenarioSessionQuery && dataSource.loadScenarioSessionQueryResults && dataSource.cancelScenarioSessionQuery)

  useEffect(() => {
    let disposed = false
    if (dataSource.listScenarios) void dataSource.listScenarios().then((items) => {
      if (!disposed) {
        setScenarios(items)
        setSelectedId((id) => items.some((item) => item.id === id) ? id : '')
        setResults(null)
        setQuery(null)
        setFilterApplied(false)
        filterCallback.current(null)
      }
    }).catch((error: unknown) => { if (!disposed) setMessage(String(error)) })
    return () => { disposed = true }
  }, [dataSource, refreshToken])

  useEffect(() => () => {
    sequence.current += 1
    if (queryId.current) void dataSource.cancelScenarioSessionQuery?.(queryId.current).catch(() => {})
  }, [dataSource])

  async function findSessions() {
    if (!selected || !available || !Number.isFinite(threshold) || threshold < 0) return
    const current = ++sequence.current
    setBusy(true)
    setQuery(null)
    queryId.current = null
    setMessage('')
    setResults(null)
    setFilterApplied(false)
    onFilter(null)
    try {
      let next = await dataSource.createScenarioSessionQuery!(selected, sessions.map(sessionToStudyRef), threshold)
      queryId.current = next.queryId
      if (current !== sequence.current) {
        await dataSource.cancelScenarioSessionQuery!(next.queryId)
        return
      }
      setQuery(next)
      while (next.status === 'queued' || next.status === 'running') {
        await new Promise((resolve) => setTimeout(resolve, 300))
        if (current !== sequence.current) return
        next = await dataSource.loadScenarioSessionQuery!(next.queryId)
        if (current !== sequence.current) return
        setQuery(next)
      }
      if (next.status === 'completed') {
        const page = await dataSource.loadScenarioSessionQueryResults!(next.queryId)
        if (current === sequence.current) setResults(page)
      } else if (next.status === 'failed') setMessage(next.error || 'Search failed.')
    } catch (error) {
      if (current === sequence.current) setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      if (current === sequence.current) setBusy(false)
    }
  }

  async function cancel() {
    if (!queryId.current) return
    try {
      const next = await dataSource.cancelScenarioSessionQuery!(queryId.current)
      sequence.current += 1
      setQuery(next)
      setBusy(false)
    } catch (error) { setMessage(String(error)) }
  }

  async function loadAllResults() {
    if (!query || !results) return []
    const rows = [...results.results]
    let offset = results.nextOffset
    while (offset !== null) {
      const page = await dataSource.loadScenarioSessionQueryResults!(query.queryId, offset)
      rows.push(...page.results)
      offset = page.nextOffset
    }
    return rows
  }

  function selectScenario(id: string) {
    sequence.current += 1
    setSelectedId(id)
    setResults(null)
    setQuery(null)
    setFilterApplied(false)
    onFilter(null)
  }

  return <section className="geo-card library-scenarios-card">
    <div className="geo-card-title">
      <ListFilter size={16} aria-hidden="true" />
      <strong className="inline-heading">Scenarios<InfoTip text="Select one saved scenario and search the currently filtered sessions. Minimum total duration sums its qualifying episodes. Incomplete evaluations are reported separately. Searches are temporary and do not change session data." /></strong>
      <span className="module-header-count">{scenarios.length} available</span>
      <button className="secondary-action compact" onClick={onManage} type="button" disabled={busy}>Create or edit</button>
    </div>
    <div className="track-list compact-track-list scenario-list" role="listbox" aria-label="Scenarios" onKeyDown={(event) => {
      if (busy || !scenarios.length || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const index = scenarios.findIndex((item) => item.id === selectedId)
      const target = event.key === 'Home' ? 0 : event.key === 'End' ? scenarios.length - 1 : event.key === 'ArrowDown' ? Math.min(index + 1, scenarios.length - 1) : Math.max(index - 1, 0)
      selectScenario(scenarios[target].id || '')
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="option"]')[target]?.focus()
    }}>
      {scenarios.map((scenario) => <button key={scenario.id} role="option" aria-selected={selectedId === scenario.id}
        className={`scenario-list-row${selectedId === scenario.id ? ' selected' : ''}`} type="button" disabled={busy}
        onClick={() => selectScenario(scenario.id || '')}>
        <strong>{scenario.displayName}</strong>{scenario.description && <small>{scenario.description}</small>}
      </button>)}
      {!scenarios.length && <p className="empty-state">No saved scenarios.</p>}
    </div>
    <label className="scenario-search-duration">Minimum total duration (s)
      <input aria-label="Minimum total duration (s)" type="number" min="0" step="any" value={minimum} disabled={busy}
        onChange={(event) => { sequence.current += 1; setMinimum(event.target.value); setResults(null); setQuery(null); setFilterApplied(false); onFilter(null) }} />
    </label>
    <div className="action-row tight">
      <button className="secondary-action compact" type="button" disabled={!selected || !available || busy || !sessions.length || minimum === '' || !Number.isFinite(threshold) || threshold < 0} onClick={() => void findSessions()}><Search size={14} />Find matching sessions</button>
      {busy && <button className="secondary-action compact" type="button" disabled={!query} onClick={() => void cancel()}>Cancel</button>}
    </div>
    {!available && <p className="modal-note">Scenario search is unavailable in this data source.</p>}
    {query && <p className="modal-note" role="status">{query.status}: {query.processedSessionCount}/{query.candidateSessionCount} checked; {query.matchedSessionCount} matching; {query.unavailableSessionCount} unavailable; {query.partialSessionCount} incomplete.</p>}
    {message && <p className="modal-note" role="alert">{message}</p>}
    {results && <>
      <button className="secondary-action compact" type="button" aria-pressed={filterApplied} onClick={() => {
        if (filterApplied) {
          onFilter(null)
          setFilterApplied(false)
          return
        }
        const current = sequence.current
        void loadAllResults().then((rows) => {
          if (current !== sequence.current) return
          onFilter(rows.map((row) => sessionRefId(row.sessionRef)))
          setFilterApplied(true)
        }).catch((error: unknown) => { if (current === sequence.current) setMessage(String(error)) })
      }}>{filterApplied ? 'Clear scenario filter' : 'Apply scenario filter'}</button>
      <div className="scenario-search-results">
      {results.results.map((row) => <div className="match-row" key={sessionRefId(row.sessionRef)}>
        <span>{sessions.find((session) => sessionRefId(sessionToStudyRef(session)) === sessionRefId(row.sessionRef))?.name || row.sessionRef.sessionKey}<small>{row.matchedDurationS.toFixed(2)} s matching</small></span>
        <IconButton label="Add session to Study Set" icon={<Plus size={14} />} onClick={() => onAttachSession(row.sessionRef)} />
      </div>)}
      {results.nextOffset !== null && <button className="secondary-action compact" type="button" onClick={() => {
        const current = sequence.current
        void dataSource.loadScenarioSessionQueryResults!(query!.queryId, results.nextOffset!).then((page) => {
          if (current === sequence.current) setResults({ ...page, results: [...results.results, ...page.results] })
        }).catch((error: unknown) => { if (current === sequence.current) setMessage(String(error)) })
      }}>More results</button>}
      </div>
    </>}
  </section>
}
