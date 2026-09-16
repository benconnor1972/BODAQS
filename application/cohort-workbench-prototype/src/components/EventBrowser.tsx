import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Pin, Tag, X } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionRefId } from '../domain/studySets'
import type {
  EventAnnotationRecord,
  EventDefinition,
  EventReference,
  EventSegment,
  ScenarioEvaluationResponse,
  ScenarioRecord,
  SessionRecord,
  StudySessionRef,
  StudySet,
  TableQueryRow,
} from '../domain/types'
import { InfoTip } from './Common'
import { AnalysisControlCard, AnalysisControlDrawer, AnalysisEndPicker, AnalysisEntityPicker, AnalysisScenarioPicker } from './AnalysisControls'

type Entity = { id: string; kind: 'session' | 'grouping'; label: string; color?: string; refs: StudySessionRef[] }
type MetricFilter = { column: string; min: string; max: string }
type TimeWindow = { startS: string; endS: string }
type EventSort = { column: string; direction: 'asc' | 'desc' }
type EventBrowserSettings = {
  selectedEntityIds?: string[]
  controlsCollapsed?: boolean
  definitionKey?: string
  selectedEnds?: string[]
  timeWindows?: Record<string, TimeWindow>
  metricFilter?: MetricFilter
  selectedScenarioIds?: string[]
  selectedSchemaTags?: string[]
  selectedUserTags?: string[]
  sort?: EventSort
  pinnedEventRefs?: EventReference[]
  hiddenPinnedEventKeys?: string[]
}

const SERIES_COLORS = ['#008c95', '#d55e00', '#0072b2', '#cc79a7', '#6f4c9b', '#009e73', '#e69f00']
const ALL_CONDITIONS = '__all__'
const MAX_COMPARISON_EVENTS = 12
const SORT_TRIGGER = 'trigger_time_s'
const SORT_SESSION = '__session__'
const SORT_END = '__end__'

export function EventBrowser({
  studySet,
  sessions,
  dataSource,
  canWrite = Boolean(dataSource.saveEventAnnotation),
  onInspectSignals,
}: {
  studySet: StudySet
  sessions: SessionRecord[]
  dataSource: LibraryDataSource
  canWrite?: boolean
  onInspectSignals?: (sessionRef: StudySessionRef, window: { startS: number; endS: number }) => void
}) {
  const entities = useMemo(() => eventBrowserEntities(studySet), [studySet])
  const settingsKey = useMemo(() => eventBrowserSettingsKey(studySet), [studySet])
  const initialSettings = useMemo(() => readEventBrowserSettings(settingsKey), [settingsKey])
  const [selectedEntityIds, setSelectedEntityIds] = useState(() => initialSettings.selectedEntityIds?.filter((id) => entities.some((item) => item.id === id)) ?? entities.filter((item) => item.kind === 'session').map((item) => item.id))
  const [controlsCollapsed, setControlsCollapsed] = useState(initialSettings.controlsCollapsed ?? false)
  const [definitions, setDefinitions] = useState<EventDefinition[]>([])
  const [definitionKey, setDefinitionKey] = useState(initialSettings.definitionKey ?? '')
  const [selectedEnds, setSelectedEnds] = useState<string[]>(initialSettings.selectedEnds ?? [])
  const [timeWindows, setTimeWindows] = useState<Record<string, TimeWindow>>(initialSettings.timeWindows ?? {})
  const [metricFilter, setMetricFilter] = useState<MetricFilter>(initialSettings.metricFilter ?? { column: '', min: '', max: '' })
  const [events, setEvents] = useState<TableQueryRow[]>([])
  const [loadingMessage, setLoadingMessage] = useState('Discovering event definitions...')
  const [error, setError] = useState('')
  const [index, setIndex] = useState(0)
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>([])
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<string[]>(initialSettings.selectedScenarioIds?.length ? initialSettings.selectedScenarioIds : [ALL_CONDITIONS])
  const [scenarioResults, setScenarioResults] = useState<Record<string, ScenarioEvaluationResponse>>({})
  const [annotations, setAnnotations] = useState<EventAnnotationRecord[]>([])
  const [tagDraft, setTagDraft] = useState('')
  const [selectedSchemaTags, setSelectedSchemaTags] = useState<string[]>(initialSettings.selectedSchemaTags ?? [])
  const [selectedUserTags, setSelectedUserTags] = useState<string[]>(initialSettings.selectedUserTags ?? [])
  const [sort, setSort] = useState<EventSort>(initialSettings.sort ?? { column: SORT_TRIGGER, direction: 'asc' })
  const [pinnedEventRefs, setPinnedEventRefs] = useState<EventReference[]>(initialSettings.pinnedEventRefs ?? [])
  const [hiddenPinnedEventKeys, setHiddenPinnedEventKeys] = useState<string[]>(initialSettings.hiddenPinnedEventKeys ?? [])
  const [bulkTag, setBulkTag] = useState('')
  const [comparisonMessage, setComparisonMessage] = useState('')
  const [segments, setSegments] = useState<EventSegment[]>([])

  const selectedRefs = useMemo(() => {
    const refs = selectedEntityIds.flatMap((id) => entities.find((item) => item.id === id)?.refs ?? [])
    return uniqueRefs(refs)
  }, [entities, selectedEntityIds])
  const selectedRefIds = useMemo(() => new Set(selectedRefs.map(sessionRefId)), [selectedRefs])
  const definition = definitions.find((item) => item.definitionKey === definitionKey) ?? definitions[0] ?? null
  const capabilityError = dataSource.queryEventDefinitions && dataSource.queryEventSegments ? '' : 'This data source does not provide schema-aware Event Browser queries.'

  useEffect(() => {
    if (typeof window === 'undefined') return
    const settings: EventBrowserSettings = {
      selectedEntityIds,
      controlsCollapsed,
      definitionKey,
      selectedEnds,
      timeWindows,
      metricFilter,
      selectedScenarioIds,
      selectedSchemaTags,
      selectedUserTags,
      sort,
      pinnedEventRefs,
      hiddenPinnedEventKeys,
    }
    try {
      window.localStorage.setItem(settingsKey, JSON.stringify(settings))
    } catch {
      // Browsing remains usable when storage is unavailable or full.
    }
  }, [controlsCollapsed, definitionKey, hiddenPinnedEventKeys, metricFilter, pinnedEventRefs, selectedEnds, selectedEntityIds, selectedScenarioIds, selectedSchemaTags, selectedUserTags, settingsKey, sort, timeWindows])

  useEffect(() => {
    let cancelled = false
    if (!dataSource.queryEventDefinitions) {
      return
    }
    dataSource.queryEventDefinitions(studySet.sessions).then((response) => {
      if (cancelled) return
      setDefinitions(response.definitions)
      setDefinitionKey((current) => response.definitions.some((item) => item.definitionKey === current) ? current : response.definitions[0]?.definitionKey ?? '')
      setSelectedEnds((current) => current.length
        ? current.filter((end) => response.definitions.some((item) => item.availableEnds.includes(end)))
        : response.definitions[0]?.availableEnds ?? [])
      setLoadingMessage(response.definitions.length ? '' : 'No detected Events are available in this Study Set.')
    }).catch((reason) => {
      if (!cancelled) {
        setError(reason instanceof Error ? reason.message : String(reason))
        setLoadingMessage('')
      }
    })
    return () => { cancelled = true }
  }, [dataSource, studySet.sessions])

  useEffect(() => {
    if (!dataSource.listScenarios) return
    dataSource.listScenarios().then(setScenarios).catch(() => setScenarios([]))
  }, [dataSource])

  useEffect(() => {
    if (!dataSource.listEventAnnotations) return
    dataSource.listEventAnnotations(studySet.sessions).then(setAnnotations).catch(() => setAnnotations([]))
  }, [dataSource, studySet.sessions])

  useEffect(() => {
    let cancelled = false
    if (!definition || selectedRefs.length === 0) {
      return
    }
    Promise.all(groupRefsByLibrary(selectedRefs).map(async ([libraryId, refs]) => {
      const [eventResponse, metricResponse] = await Promise.all([
        dataSource.queryEvents(libraryId, { sessions: refs, eventTypes: definition.eventSetIds }),
        dataSource.queryMetrics(libraryId, { sessions: refs, eventTypes: definition.eventSetIds }),
      ])
      const metricByEvent = new Map(metricResponse.rows.map((row) => [eventRowKey(row), row.fields]))
      return eventResponse.rows
        .filter((row) => String(row.fields.schema_id ?? row.eventType) === definition.schemaId)
        .map((row) => ({ ...row, fields: { ...row.fields, ...(metricByEvent.get(eventRowKey(row)) ?? {}) } }))
    })).then((parts) => {
      if (cancelled) return
      const next = parts.flat().sort((a, b) => compareEventRows(a, b, { column: SORT_TRIGGER, direction: 'asc' }))
      setEvents(next)
      setIndex(0)
      setLoadingMessage(next.length ? '' : 'No instances of this Event are available in the selected sessions or groups.')
    }).catch((reason) => {
      if (!cancelled) {
        setError(reason instanceof Error ? reason.message : String(reason))
        setLoadingMessage('')
      }
    })
    return () => { cancelled = true }
  }, [dataSource, definition, selectedRefs])

  useEffect(() => {
    let cancelled = false
    const selected = scenarios.filter((item) => item.id && selectedScenarioIds.includes(item.id))
    if (!selected.length || !dataSource.evaluateScenario || selectedRefs.length === 0) {
      return
    }
    Promise.all(selected.map(async (scenario) => {
      const result = await dataSource.evaluateScenario!({
        scenarioRef: scenario.id && scenario.revision !== undefined ? { scenarioId: scenario.id, revision: scenario.revision } : undefined,
        scenario: scenario.id ? undefined : scenario,
        sessions: selectedRefs,
      })
      return [scenario.id as string, result] as const
    })).then((results) => {
      if (!cancelled) {
        setScenarioResults(Object.fromEntries(results))
        setLoadingMessage('')
      }
    }).catch((reason) => {
      if (!cancelled) {
        setError(reason instanceof Error ? reason.message : String(reason))
        setLoadingMessage('')
      }
    })
    return () => { cancelled = true }
  }, [dataSource, scenarios, selectedRefs, selectedScenarioIds])

  const activeScenarioResults = useMemo(() => selectedScenarioIds.includes(ALL_CONDITIONS)
    ? []
    : selectedScenarioIds.map((id) => scenarioResults[id]).filter((result): result is ScenarioEvaluationResponse => Boolean(result)),
  [scenarioResults, selectedScenarioIds])
  const annotationByEventKey = useMemo(() => new Map(annotations.map((item) => [eventReferenceKey(item.eventRef), item])), [annotations])
  const availableSchemaTags = useMemo(() => Array.from(new Set([
    ...(definition?.schemaTags ?? []),
    ...events.flatMap((row) => stringList(row.fields.tags)),
  ])).sort((a, b) => a.localeCompare(b)), [definition?.schemaTags, events])
  const availableTags = useMemo(() => Array.from(new Set(annotations.flatMap((item) => item.tags))).sort((a, b) => a.localeCompare(b)), [annotations])
  const population = useMemo(() => {
    const baseRows = events.filter((row) => {
      if (!selectedRefIds.has(sessionRefId(row.sessionRef))) return false
      if (definition && String(row.fields.schema_id ?? row.eventType) !== definition.schemaId) return false
      if (definition?.sessionRefIds.length && !definition.sessionRefIds.includes(sessionRefId(row.sessionRef))) return false
      return true
    })
    const rowsBeforeMetric = baseRows.filter((row) => {
      if (selectedEnds.length && !selectedEnds.includes(row.signalRole)) return false
      const refId = sessionRefId(row.sessionRef)
      const window = timeWindows[refId]
      const trigger = finiteNumber(row.fields.trigger_time_s)
      if (window && trigger !== null) {
        const start = finiteNumber(window.startS)
        const end = finiteNumber(window.endS)
        if (start !== null && trigger < start) return false
        if (end !== null && trigger > end) return false
      }
      if (activeScenarioResults.length && !activeScenarioResults.some((result) => triggerInScenario(row, result))) return false
      const schemaTags = stringList(row.fields.tags)
      if (selectedSchemaTags.length && !selectedSchemaTags.some((tag) => schemaTags.includes(tag))) return false
      if (selectedUserTags.length) {
        const eventRef = rowEventReference(row, studySet.sessions)
        const userTags = annotationByEventKey.get(eventReferenceKey(eventRef))?.tags ?? []
        if (!selectedUserTags.some((tag) => userTags.includes(tag))) return false
      }
      return true
    })
    const missingMetricCount = metricFilter.column ? rowsBeforeMetric.filter((row) => finiteNumber(row.fields[metricFilter.column]) === null).length : 0
    const rows = rowsBeforeMetric.filter((row) => {
      if (metricFilter.column) {
        const value = finiteNumber(row.fields[metricFilter.column])
        if (value === null) return false
        const min = finiteNumber(metricFilter.min)
        const max = finiteNumber(metricFilter.max)
        if (min !== null && value < min) return false
        if (max !== null && value > max) return false
      }
      return true
    })
    rows.sort((a, b) => compareEventRows(a, b, sort))
    return { rows, baseCount: baseRows.length, missingMetricCount }
  }, [activeScenarioResults, annotationByEventKey, definition, events, metricFilter, selectedEnds, selectedRefIds, selectedSchemaTags, selectedUserTags, sort, studySet.sessions, timeWindows])
  const filteredEvents = population.rows

  const safeIndex = Math.min(index, Math.max(0, filteredEvents.length - 1))
  const selectedRow = filteredEvents[safeIndex] ?? null
  const selectedRef = useMemo(
    () => selectedRow ? { ...rowEventReference(selectedRow, studySet.sessions), schemaDigest: definition?.schemaDigest } : null,
    [definition?.schemaDigest, selectedRow, studySet.sessions],
  )
  const selectedAnnotation = selectedRef ? annotations.find((item) => eventReferenceKey(item.eventRef) === eventReferenceKey(selectedRef)) : undefined
  const compatiblePinnedEventRefs = useMemo(() => pinnedEventRefs.filter((ref) => isCompatibleEvent(ref, definition)), [definition, pinnedEventRefs])
  const incompatiblePinCount = pinnedEventRefs.length - compatiblePinnedEventRefs.length
  const visiblePinnedEventRefs = useMemo(() => compatiblePinnedEventRefs.filter((ref) => !hiddenPinnedEventKeys.includes(eventReferenceKey(ref))), [compatiblePinnedEventRefs, hiddenPinnedEventKeys])
  const comparisonCandidates = useMemo(() => uniqueEventRefs(selectedRef ? [selectedRef, ...visiblePinnedEventRefs] : visiblePinnedEventRefs), [selectedRef, visiblePinnedEventRefs])
  const displayEventRefs = useMemo(() => {
    return comparisonCandidates.slice(0, MAX_COMPARISON_EVENTS)
  }, [comparisonCandidates])
  const omittedTraceCount = Math.max(0, comparisonCandidates.length - displayEventRefs.length)
  const displayedSegmentKeys = useMemo(() => new Set(displayEventRefs.map(eventReferenceKey)), [displayEventRefs])
  const displayedSegments = useMemo(() => segments.filter((segment) => displayedSegmentKeys.has(eventReferenceKey(segment.eventRef))), [displayedSegmentKeys, segments])

  useEffect(() => {
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.altKey || event.ctrlKey || event.metaKey) return
      const target = event.target
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return
      if (event.key === 'ArrowLeft' && safeIndex > 0) {
        event.preventDefault()
        setIndex(safeIndex - 1)
      }
      if (event.key === 'ArrowRight' && safeIndex < filteredEvents.length - 1) {
        event.preventDefault()
        setIndex(safeIndex + 1)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [filteredEvents.length, safeIndex])

  useEffect(() => {
    let cancelled = false
    if (!selectedRef || !definition || !dataSource.queryEventSegments) {
      return
    }
    const adjacentRows = [filteredEvents[safeIndex - 1], filteredEvents[safeIndex + 1]].filter((row): row is TableQueryRow => Boolean(row))
    const prefetched = adjacentRows.map((row) => ({ ...rowEventReference(row, studySet.sessions), schemaDigest: definition.schemaDigest }))
    const unique = uniqueEventRefs([...displayEventRefs, ...prefetched]).slice(0, 12)
    Promise.all(groupEventsByLibrary(unique).map(([libraryId, refs]) => dataSource.queryEventSegments!(libraryId, {
      events: refs,
      window: { preS: definition.defaultWindow.preS, postS: definition.defaultWindow.postS },
      roles: definition.defaultRoles.map((item) => item.role),
    }))).then((responses) => {
      if (!cancelled) setSegments(responses.flatMap((item) => item.segments))
    }).catch((reason) => {
      if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason))
    })
    return () => { cancelled = true }
  }, [dataSource, definition, displayEventRefs, filteredEvents, safeIndex, selectedRef, studySet.sessions])

  async function setTags(tags: string[]) {
    if (!selectedRef || !dataSource.saveEventAnnotation || !canWrite) return
    const normalized = Array.from(new Set(tags.map((item) => item.trim()).filter(Boolean)))
    if (selectedAnnotation && normalized.length === 0 && dataSource.deleteEventAnnotation) {
      await dataSource.deleteEventAnnotation(selectedAnnotation.id)
      setAnnotations((current) => current.filter((item) => item.id !== selectedAnnotation.id))
      return
    }
    const saved = await dataSource.saveEventAnnotation({
      id: selectedAnnotation?.id ?? '',
      revision: selectedAnnotation?.revision ?? 0,
      eventRef: selectedRef,
      tags: normalized,
      createdAtUtc: selectedAnnotation?.createdAtUtc ?? '',
      updatedAtUtc: selectedAnnotation?.updatedAtUtc ?? '',
    })
    setAnnotations((current) => [...current.filter((item) => item.id !== saved.id), saved])
  }

  function togglePinnedCurrent() {
    if (!selectedRef) return
    const key = eventReferenceKey(selectedRef)
    if (pinnedEventRefs.some((ref) => eventReferenceKey(ref) === key)) {
      setPinnedEventRefs((current) => current.filter((ref) => eventReferenceKey(ref) !== key))
      setHiddenPinnedEventKeys((current) => current.filter((item) => item !== key))
      setComparisonMessage('Removed the current Event from the comparison tray.')
      return
    }
    if (pinnedEventRefs.length >= MAX_COMPARISON_EVENTS) {
      setComparisonMessage(`The comparison tray is limited to ${MAX_COMPARISON_EVENTS} pinned Events.`)
      return
    }
    setPinnedEventRefs((current) => [...current, selectedRef])
    setComparisonMessage('Pinned the current Event for comparison.')
  }

  function removePinnedEvent(ref: EventReference) {
    const key = eventReferenceKey(ref)
    setPinnedEventRefs((current) => current.filter((item) => eventReferenceKey(item) !== key))
    setHiddenPinnedEventKeys((current) => current.filter((item) => item !== key))
    setComparisonMessage('Removed an Event from the comparison tray.')
  }

  function addTaggedEvents() {
    if (!bulkTag) return
    const taggedRefs = filteredEvents.flatMap((row) => {
      const eventRef = { ...rowEventReference(row, studySet.sessions), schemaDigest: definition?.schemaDigest }
      return annotationByEventKey.get(eventReferenceKey(eventRef))?.tags.includes(bulkTag) ? [eventRef] : []
    })
    const existingKeys = new Set(pinnedEventRefs.map(eventReferenceKey))
    const additions = uniqueEventRefs(taggedRefs).filter((ref) => !existingKeys.has(eventReferenceKey(ref)))
    const capacity = Math.max(0, MAX_COMPARISON_EVENTS - pinnedEventRefs.length)
    const accepted = additions.slice(0, capacity)
    setPinnedEventRefs((current) => [...current, ...accepted])
    const omitted = additions.length - accepted.length
    setComparisonMessage(accepted.length
      ? `Added ${accepted.length} tagged Event${accepted.length === 1 ? '' : 's'}${omitted ? `; ${omitted} omitted by the ${MAX_COMPARISON_EVENTS}-pin limit` : ''}.`
      : additions.length ? `No Events were added because the tray is limited to ${MAX_COMPARISON_EVENTS} pins.` : 'All matching Events are already pinned, or no filtered Events have that tag.')
  }

  function clearPinnedEvents() {
    setPinnedEventRefs([])
    setHiddenPinnedEventKeys([])
    setComparisonMessage('Cleared the comparison tray.')
  }

  function toggleScenarioSelection(id: string, checked: boolean) {
    if (id === ALL_CONDITIONS) {
      setSelectedScenarioIds(checked ? [ALL_CONDITIONS] : [])
      return
    }
    setSelectedScenarioIds((current) => {
      const withoutBaseline = current.filter((item) => item !== ALL_CONDITIONS && item !== id)
      const next = checked ? [...withoutBaseline, id] : withoutBaseline
      return next.length ? next : [ALL_CONDITIONS]
    })
  }

  return (
    <div className="suspension-viz event-browser">
      <header className="suspension-viz-hero">
        <div>
          <h3 className="viz-heading">{studySet.displayName || 'Current Study Set'} <InfoTip text="Inspect detected Events one at a time, with schema-defined signals, trigger markers, metrics, tags, and aligned comparisons." /></h3>
          <p>{definition ? `${definition.displayName} · ${filteredEvents.length} of ${population.baseCount} instances` : 'Select an Event definition to begin.'}</p>
        </div>
      </header>
      <div className={`suspension-viz-workspace${controlsCollapsed ? ' controls-collapsed' : ''}`}>
        <AnalysisControlDrawer
          collapsed={controlsCollapsed}
          summary={`${selectedRefs.length} sessions · ${filteredEvents.length} of ${population.baseCount} Events`}
          infoText="Choose Study Set sessions or groups, Event definition, ends, Scenarios, primary-trigger time windows, and metric restrictions. Study Set membership is not changed."
          onToggle={() => setControlsCollapsed((current) => !current)}
        >
                <section className="viz-entity-selector">
                  <AnalysisEntityPicker
                    entities={entities.map((entity) => ({ id: entity.id, kind: entity.kind, label: entity.label, color: entity.color, memberCount: entity.refs.length }))}
                    selectedIds={selectedEntityIds}
                    onToggle={(id) => setSelectedEntityIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])}
                  />
                </section>
                <AnalysisControlCard title="Event type">
                  <select aria-label="Event type" value={definition?.definitionKey ?? ''} onChange={(event) => { const next = definitions.find((item) => item.definitionKey === event.target.value); setDefinitionKey(event.target.value); setSelectedEnds(next?.availableEnds ?? []); setMetricFilter({ column: '', min: '', max: '' }); setSelectedSchemaTags([]); setSort({ column: SORT_TRIGGER, direction: 'asc' }); setIndex(0) }}>
                    {definitions.map((item) => <option key={item.definitionKey} value={item.definitionKey}>{item.displayName} ({item.eventCount})</option>)}
                  </select>
                  {definition && <small>{definition.primaryTrigger.id} primary trigger{definition.secondaryTriggers.length ? ` · ${definition.secondaryTriggers.map((item) => item.id).join(', ')} secondary` : ''}</small>}
                </AnalysisControlCard>
                <AnalysisEndPicker
                  ends={(definition?.availableEnds ?? []).map((end) => ({ id: end, label: titleCase(end), color: end === 'front' ? '#008c95' : end === 'rear' ? '#101820' : '#8b9793' }))}
                  selectedIds={selectedEnds}
                  onToggle={(end) => setSelectedEnds((current) => current.includes(end) ? current.filter((item) => item !== end) : [...current, end])}
                />
                <AnalysisControlCard title="Scenarios" hint="Any selected Scenario may include an Event; inclusion uses its primary trigger.">
                  <AnalysisScenarioPicker
                    options={[{ id: ALL_CONDITIONS, label: 'All qualifying Events' }, ...scenarios.filter((item) => item.id).map((item) => ({ id: item.id as string, label: `${item.displayName} (r${item.revision})` }))]}
                    selectedIds={selectedScenarioIds}
                    onToggle={toggleScenarioSelection}
                  />
                </AnalysisControlCard>
                <TimeWindowControl refs={selectedRefs} sessions={sessions} value={timeWindows} onChange={setTimeWindows} />
                <AnalysisControlCard title="Metric filter">
                  <select aria-label="Metric filter" value={metricFilter.column} onChange={(event) => { setMetricFilter({ column: event.target.value, min: '', max: '' }); setIndex(0) }}><option value="">No metric filter</option>{definition?.metricFields.map((field) => <option key={field.column} value={field.column}>{field.displayName}</option>)}</select>
                  {metricFilter.column && <div className="event-browser-range"><label>Minimum<input type="number" value={metricFilter.min} onChange={(event) => setMetricFilter((current) => ({ ...current, min: event.target.value }))} /></label><label>Maximum<input type="number" value={metricFilter.max} onChange={(event) => setMetricFilter((current) => ({ ...current, max: event.target.value }))} /></label></div>}
                  {metricFilter.column && population.missingMetricCount > 0 && <small>{population.missingMetricCount} Event{population.missingMetricCount === 1 ? '' : 's'} excluded because this metric is missing.</small>}
                </AnalysisControlCard>
                {availableSchemaTags.length > 0 && <AnalysisControlCard title="Schema tags" hint="An Event may match any selected schema tag.">
                  <AnalysisScenarioPicker
                    ariaLabel="Schema tag filters"
                    optionAriaLabelPrefix="Filter schema tag"
                    options={availableSchemaTags.map((tag) => ({ id: tag, label: tag }))}
                    selectedIds={selectedSchemaTags}
                    onToggle={(tag, checked) => { setSelectedSchemaTags((current) => toggleListValue(current, tag, checked)); setIndex(0) }}
                  />
                </AnalysisControlCard>}
                {availableTags.length > 0 && <AnalysisControlCard title="User tags" hint="Independent of schema tags; an Event may match any selected user tag.">
                  <AnalysisScenarioPicker
                    ariaLabel="User tag filters"
                    optionAriaLabelPrefix="Filter user tag"
                    options={availableTags.map((tag) => ({ id: tag, label: tag }))}
                    selectedIds={selectedUserTags}
                    onToggle={(tag, checked) => { setSelectedUserTags((current) => toggleListValue(current, tag, checked)); setIndex(0) }}
                  />
                </AnalysisControlCard>}
                <AnalysisControlCard title="Event order">
                  <div className="event-browser-sort">
                    <select aria-label="Sort Events by" value={sort.column} onChange={(event) => { setSort((current) => ({ ...current, column: event.target.value })); setIndex(0) }}>
                      <option value={SORT_TRIGGER}>Primary trigger time</option>
                      <option value={SORT_SESSION}>Session</option>
                      <option value={SORT_END}>End</option>
                      {definition?.metricFields.map((field) => <option key={field.column} value={field.column}>{field.displayName}</option>)}
                    </select>
                    <select aria-label="Sort direction" value={sort.direction} onChange={(event) => { setSort((current) => ({ ...current, direction: event.target.value as EventSort['direction'] })); setIndex(0) }}>
                      <option value="asc">Ascending</option>
                      <option value="desc">Descending</option>
                    </select>
                  </div>
                </AnalysisControlCard>
        </AnalysisControlDrawer>
        <main className="suspension-viz-content">
          {loadingMessage && <div className="viz-status">{loadingMessage}</div>}
          {(error || capabilityError) && <div className="viz-status warning">{error || capabilityError}</div>}
          {selectedRow && selectedRef ? (
            <>
              <nav className="event-browser-navigator" aria-label="Event instances">
                <button type="button" className="secondary-action compact" aria-keyshortcuts="ArrowLeft" disabled={safeIndex === 0} onClick={() => setIndex(Math.max(0, safeIndex - 1))}>Previous</button>
                <strong>Event {safeIndex + 1} of {filteredEvents.length}</strong>
                <select aria-label="Event instance" value={safeIndex} onChange={(event) => setIndex(Number(event.target.value))}>{filteredEvents.map((row, rowIndex) => <option key={eventRowKey(row)} value={rowIndex}>{rowIndex + 1}. {row.sessionRef.label} · {titleCase(row.signalRole)} · {formatNumber(row.fields.trigger_time_s)} s</option>)}</select>
                <button type="button" className="secondary-action compact" aria-keyshortcuts="ArrowRight" disabled={safeIndex >= filteredEvents.length - 1} onClick={() => setIndex(Math.min(filteredEvents.length - 1, safeIndex + 1))}>Next</button>
              </nav>
              <section className="viz-panel event-browser-comparison" aria-label="Comparison tray">
                <div className="viz-panel-heading">
                  <div>
                    <strong>Comparison tray</strong>
                    <small>{pinnedEventRefs.length} pinned · plotted with the current Event and aligned at the primary trigger · {MAX_COMPARISON_EVENTS} traces maximum</small>
                  </div>
                  <div className="event-browser-comparison-actions">
                    <button className="secondary-action compact" type="button" aria-pressed={pinnedEventRefs.some((ref) => eventReferenceKey(ref) === eventReferenceKey(selectedRef))} onClick={togglePinnedCurrent}><Pin size={14} />{pinnedEventRefs.some((ref) => eventReferenceKey(ref) === eventReferenceKey(selectedRef)) ? 'Unpin current' : 'Pin current'}</button>
                    {pinnedEventRefs.length > 0 && <button className="ghost-action compact" type="button" onClick={clearPinnedEvents}>Clear</button>}
                  </div>
                </div>
                <div className="event-browser-comparison-body">
                  <div className="event-browser-bulk-add">
                    <select aria-label="Tagged Events to add" value={bulkTag} onChange={(event) => setBulkTag(event.target.value)}><option value="">Choose a user tag</option>{availableTags.map((tag) => <option key={tag} value={tag}>{tag}</option>)}</select>
                    <button className="secondary-action compact" type="button" disabled={!bulkTag} onClick={addTaggedEvents}>Add filtered matches</button>
                  </div>
                  {pinnedEventRefs.length ? <div className="event-browser-pinned-list">{pinnedEventRefs.map((ref) => {
                    const key = eventReferenceKey(ref)
                    const active = key === eventReferenceKey(selectedRef)
                    const compatible = isCompatibleEvent(ref, definition)
                    const visible = active || !hiddenPinnedEventKeys.includes(key)
                    const displayIndex = displayEventRefs.findIndex((item) => eventReferenceKey(item) === key)
                    return <div className={`event-browser-pinned-item${compatible ? '' : ' incompatible'}`} key={key}>
                      <span aria-hidden="true" className="event-browser-trace-swatch" style={{ backgroundColor: displayIndex >= 0 ? SERIES_COLORS[displayIndex % SERIES_COLORS.length] : '#8b9793' }} />
                      <span><strong>{ref.label || ref.sessionId}</strong><small>{ref.eventId} · {formatNumber(ref.triggerTimeS)} s{active ? ' · current' : ''}{compatible ? '' : ' · incompatible schema revision'}</small></span>
                      <button className="ghost-action compact icon-only" type="button" aria-label={`${visible ? 'Hide' : 'Show'} ${ref.eventId} trace`} title={`${visible ? 'Hide' : 'Show'} trace`} disabled={!compatible || active} onClick={() => setHiddenPinnedEventKeys((current) => toggleListValue(current, key, !current.includes(key)))}>{visible ? <Eye size={14} /> : <EyeOff size={14} />}</button>
                      <button className="ghost-action compact icon-only" type="button" aria-label={`Remove ${ref.eventId} from comparison`} title="Remove from comparison" onClick={() => removePinnedEvent(ref)}><X size={14} /></button>
                    </div>
                  })}</div> : <small>Pin Events while browsing, or add the filtered Events matching a user tag.</small>}
                  {(comparisonMessage || incompatiblePinCount > 0 || omittedTraceCount > 0) && <div className="event-browser-comparison-status" role="status">{comparisonMessage}{incompatiblePinCount > 0 && ` ${incompatiblePinCount} pin${incompatiblePinCount === 1 ? '' : 's'} belong to another schema revision and are not plotted.`}{omittedTraceCount > 0 && ` ${omittedTraceCount} visible pin${omittedTraceCount === 1 ? '' : 's'} omitted to keep the plot within ${MAX_COMPARISON_EVENTS} traces.`}</div>}
                </div>
              </section>
              <section className="viz-panel event-browser-chart-panel"><div className="viz-panel-heading"><div><strong>Signal window</strong><small>{selectedRef.label} · {titleCase(selectedRow.signalRole)} · primary trigger at {formatNumber(selectedRow.fields.trigger_time_s)} s · use ←/→ to navigate</small></div>{onInspectSignals && selectedRef.triggerTimeS !== null && selectedRef.triggerTimeS !== undefined && <button className="secondary-action compact" type="button" onClick={() => onInspectSignals(selectedRef, { startS: Math.max(0, selectedRef.triggerTimeS! - (definition?.defaultWindow.preS ?? 0.8)), endS: selectedRef.triggerTimeS! + (definition?.defaultWindow.postS ?? 0.8) })}>Open in Signal Inspector</button>}</div><EventSegmentCharts segments={displayedSegments} primaryKey={eventReferenceKey(selectedRef)} /></section>
              <div className="event-browser-detail-grid">
                <section className="viz-panel event-browser-metrics"><div className="viz-panel-heading"><strong>Event metrics</strong></div><dl>{definition?.metricFields.map((field) => <div key={field.column}><dt>{field.displayName}</dt><dd>{formatNumber(selectedRow.fields[field.column])}{field.unit ? ` ${field.unit}` : ''}</dd></div>)}</dl></section>
                <section className="viz-panel event-browser-metrics"><div className="viz-panel-heading"><strong>Identity, QC and provenance</strong></div><dl><div><dt>Event ID</dt><dd>{selectedRef.eventId}</dd></div><div><dt>Event set</dt><dd>{selectedRef.eventSetId}</dd></div><div><dt>Schema</dt><dd>{selectedRef.schemaId} {selectedRef.schemaVersion ? `v${selectedRef.schemaVersion}` : ''}</dd></div><div><dt>Schema digest</dt><dd title={selectedRef.schemaDigest}>{abbreviateHash(selectedRef.schemaDigest)}</dd></div><div><dt>Detector parameters</dt><dd title={selectedRef.paramsHash}>{abbreviateHash(selectedRef.paramsHash)}</dd></div><div><dt>Score</dt><dd>{formatNumber(selectedRow.fields.score)}</dd></div><div><dt>QC flags</dt><dd>{formatValue(selectedRow.fields.qc_flags)}</dd></div><div><dt>Schema tags</dt><dd>{formatValue(selectedRow.fields.tags)}</dd></div></dl></section>
                <section className="viz-panel event-browser-tags"><div className="viz-panel-heading"><strong>Tags</strong></div><div className="event-browser-tag-list">{selectedAnnotation?.tags.map((tag) => <button key={tag} type="button" title="Remove tag" disabled={!canWrite} onClick={() => void setTags(selectedAnnotation.tags.filter((item) => item !== tag))}><Tag size={13} />{tag} ×</button>)}{!selectedAnnotation?.tags.length && <small>No tags on this Event.</small>}</div><form onSubmit={(event) => { event.preventDefault(); if (tagDraft.trim()) void setTags([...(selectedAnnotation?.tags ?? []), tagDraft]); setTagDraft('') }}><input value={tagDraft} onChange={(event) => setTagDraft(event.target.value)} placeholder="Add a tag" disabled={!canWrite} /><button className="secondary-action compact" type="submit" disabled={!canWrite || !tagDraft.trim()}>Add</button></form></section>
              </div>
            </>
          ) : !loadingMessage && <div className="viz-status">No Events match the current filters.</div>}
        </main>
      </div>
    </div>
  )
}

function TimeWindowControl({ refs, sessions, value, onChange }: { refs: StudySessionRef[]; sessions: SessionRecord[]; value: Record<string, TimeWindow>; onChange: (value: Record<string, TimeWindow>) => void }) {
  return <AnalysisControlCard title="Time windows" hint="Filter by primary-trigger time within each session."><div className="event-browser-time-windows">{refs.map((ref) => { const key = sessionRefId(ref); const duration = sessions.find((item) => item.libraryId === ref.libraryId && item.sessionKey === ref.sessionKey)?.durationMin; const window = value[key] ?? { startS: '', endS: '' }; return <div key={key}><span>{ref.label}</span><label>From<input type="number" min="0" value={window.startS} placeholder="0" onChange={(event) => onChange({ ...value, [key]: { ...window, startS: event.target.value } })} /></label><label>To<input type="number" min="0" value={window.endS} placeholder={duration ? String(Math.round(duration * 60)) : 'end'} onChange={(event) => onChange({ ...value, [key]: { ...window, endS: event.target.value } })} /></label></div> })}</div>{Object.keys(value).length > 0 && <button className="ghost-action compact" type="button" onClick={() => onChange({})}>Reset all windows</button>}</AnalysisControlCard>
}

function EventSegmentCharts({ segments, primaryKey }: { segments: EventSegment[]; primaryKey: string }) {
  const primary = segments.find((item) => eventReferenceKey(item.eventRef) === primaryKey) ?? segments[0]
  if (!primary) return <div className="viz-status">Loading schema-resolved signal window...</div>
  return <div className="event-browser-charts">{primary.signals.map((signal) => <SignalChart key={signal.role} role={signal.role} unit={signal.unit} segments={segments} triggers={primary.triggers} />)}</div>
}

function SignalChart({ role, unit, segments, triggers }: { role: string; unit: string; segments: EventSegment[]; triggers: EventSegment['triggers'] }) {
  const width = 900, height = 190, left = 58, right = 18, top = 18, bottom = 30
  const series = segments.map((segment) => ({ segment, signal: segment.signals.find((item) => item.role === role) })).filter((item) => item.signal)
  const times = series.flatMap((item) => item.segment.timeRelS.filter((value): value is number => value !== null))
  const values = series.flatMap((item) => item.signal!.values.filter((value): value is number => value !== null))
  if (!times.length || !values.length) return null
  const xMin = Math.min(...times), xMax = Math.max(...times), yMinRaw = Math.min(...values), yMaxRaw = Math.max(...values)
  const yPad = Math.max((yMaxRaw - yMinRaw) * 0.08, 1e-6), yMin = yMinRaw - yPad, yMax = yMaxRaw + yPad
  const x = (value: number) => left + ((value - xMin) / Math.max(xMax - xMin, 1e-9)) * (width - left - right)
  const y = (value: number) => top + (1 - (value - yMin) / Math.max(yMax - yMin, 1e-9)) * (height - top - bottom)
  return <figure className="event-browser-chart"><figcaption>{titleCase(role)}{unit ? ` (${unit})` : ''}</figcaption><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${role} Event signal window`}><line className="event-chart-axis" x1={left} y1={height-bottom} x2={width-right} y2={height-bottom} /><line className="event-chart-axis" x1={left} y1={top} x2={left} y2={height-bottom} />{triggers.map((trigger) => <g key={trigger.id}><line className={`event-chart-trigger ${trigger.kind}`} x1={x(trigger.timeRelS)} x2={x(trigger.timeRelS)} y1={top} y2={height-bottom} /><text x={x(trigger.timeRelS)+4} y={top+11}>{trigger.id}</text></g>)}{series.map((item, seriesIndex) => <polyline key={eventReferenceKey(item.segment.eventRef)} fill="none" stroke={SERIES_COLORS[seriesIndex % SERIES_COLORS.length]} strokeWidth={seriesIndex === 0 ? 2.2 : 1.25} opacity={seriesIndex === 0 ? 1 : 0.65} points={item.segment.timeRelS.map((time, pointIndex) => { const value = item.signal!.values[pointIndex]; return time === null || value === null ? null : `${x(time)},${y(value)}` }).filter(Boolean).join(' ')} />)}<text x={left} y={height-8}>{xMin.toFixed(2)} s</text><text textAnchor="end" x={width-right} y={height-8}>{xMax.toFixed(2)} s</text><text x={4} y={top+10}>{yMaxRaw.toFixed(2)}</text><text x={4} y={height-bottom}>{yMinRaw.toFixed(2)}</text></svg></figure>
}

function eventBrowserEntities(studySet: StudySet): Entity[] {
  const sessions = studySet.sessions.map((ref) => ({ id: sessionRefId(ref), kind: 'session' as const, label: ref.label || ref.sessionId, refs: [ref] }))
  const groups = studySet.groupings.map((group) => ({ id: `grouping:${group.id}`, kind: 'grouping' as const, label: group.name, color: group.color, refs: group.sessionRefs.map((id) => studySet.sessions.find((ref) => sessionRefId(ref) === id)).filter((ref): ref is StudySessionRef => Boolean(ref)) }))
  return [...sessions, ...groups]
}

function uniqueRefs(refs: StudySessionRef[]) { const seen = new Set<string>(); return refs.filter((ref) => { const key = sessionRefId(ref); if (seen.has(key)) return false; seen.add(key); return true }) }
function groupRefsByLibrary(refs: StudySessionRef[]) { const groups = new Map<string, StudySessionRef[]>(); refs.forEach((ref) => groups.set(ref.libraryId, [...(groups.get(ref.libraryId) ?? []), ref])); return [...groups.entries()] }
function groupEventsByLibrary(refs: EventReference[]) { const groups = new Map<string, EventReference[]>(); refs.forEach((ref) => groups.set(ref.libraryId, [...(groups.get(ref.libraryId) ?? []), ref])); return [...groups.entries()] }
function uniqueEventRefs(refs: EventReference[]) { const seen = new Set<string>(); return refs.filter((ref) => { const key = eventReferenceKey(ref); if (seen.has(key)) return false; seen.add(key); return true }) }
function eventReferenceKey(ref: EventReference) { return `${ref.libraryId}|||${ref.sessionKey}|||${ref.eventSetId}|||${ref.eventId}` }
function eventRowKey(row: TableQueryRow) { return `${sessionRefId(row.sessionRef)}|||${row.setId}|||${String(row.fields.event_id ?? row.rowIndex)}` }
function rowEventReference(row: TableQueryRow, refs: StudySessionRef[]): EventReference { const ref = refs.find((item) => sessionRefId(item) === sessionRefId(row.sessionRef)) ?? row.sessionRef; return { ...ref, eventSetId: row.setId, eventId: String(row.fields.event_id ?? ''), schemaId: String(row.fields.schema_id ?? row.eventType), schemaVersion: String(row.fields.schema_version ?? ''), paramsHash: String(row.fields.params_hash ?? ''), triggerTimeS: finiteNumber(row.fields.trigger_time_s) } }
function triggerInScenario(row: TableQueryRow, result: ScenarioEvaluationResponse) { const trigger = finiteNumber(row.fields.trigger_time_s); if (trigger === null) return false; const session = result.sessions.find((item) => sessionRefId(item.sessionRef) === sessionRefId(row.sessionRef)); return Boolean(session?.episodes.some((episode) => trigger >= episode.startTimeS && trigger <= episode.endTimeS)) }
function compareEventRows(a: TableQueryRow, b: TableQueryRow, sort: EventSort) {
  let comparison: number
  if (sort.column === SORT_SESSION) comparison = (a.sessionRef.label || a.sessionRef.sessionId).localeCompare(b.sessionRef.label || b.sessionRef.sessionId)
  else if (sort.column === SORT_END) comparison = a.signalRole.localeCompare(b.signalRole)
  else {
    const aValue = finiteNumber(a.fields[sort.column])
    const bValue = finiteNumber(b.fields[sort.column])
    if (aValue === null && bValue !== null) return 1
    if (aValue !== null && bValue === null) return -1
    comparison = (aValue ?? 0) - (bValue ?? 0)
  }
  if (comparison !== 0) return sort.direction === 'desc' ? -comparison : comparison
  return eventRowKey(a).localeCompare(eventRowKey(b))
}
function stringList(value: unknown): string[] { if (Array.isArray(value)) return value.map(String).filter(Boolean); return typeof value === 'string' && value ? [value] : [] }
function toggleListValue(values: string[], value: string, checked: boolean) { return checked ? Array.from(new Set([...values, value])) : values.filter((item) => item !== value) }
function isCompatibleEvent(ref: EventReference, definition: EventDefinition | null) {
  if (!definition || ref.schemaId !== definition.schemaId) return false
  if (ref.schemaDigest && definition.schemaDigest) return ref.schemaDigest === definition.schemaDigest
  if (ref.schemaVersion && definition.schemaVersion) return ref.schemaVersion === definition.schemaVersion
  return true
}
function eventBrowserSettingsKey(studySet: StudySet) {
  const scope = studySet.id || studySet.sessions.map(sessionRefId).sort().join('||') || 'empty-study-set'
  return `bodaqs.event-browser.settings.v1.${scope}.r${studySet.revision}`
}
function readEventBrowserSettings(key: string): EventBrowserSettings {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return {}
    const value = JSON.parse(raw) as Record<string, unknown>
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
    const stringArray = (item: unknown) => Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === 'string') : undefined
    const metric = value.metricFilter && typeof value.metricFilter === 'object' ? value.metricFilter as Record<string, unknown> : null
    const savedSort = value.sort && typeof value.sort === 'object' ? value.sort as Record<string, unknown> : null
    const savedWindows = value.timeWindows && typeof value.timeWindows === 'object' && !Array.isArray(value.timeWindows) ? value.timeWindows as Record<string, TimeWindow> : undefined
    const pins = Array.isArray(value.pinnedEventRefs) ? value.pinnedEventRefs.filter((item): item is EventReference => {
      if (!item || typeof item !== 'object') return false
      const ref = item as Record<string, unknown>
      return typeof ref.libraryId === 'string' && typeof ref.sessionKey === 'string' && typeof ref.eventSetId === 'string' && typeof ref.eventId === 'string'
    }).slice(0, MAX_COMPARISON_EVENTS) : undefined
    return {
      selectedEntityIds: stringArray(value.selectedEntityIds),
      controlsCollapsed: typeof value.controlsCollapsed === 'boolean' ? value.controlsCollapsed : undefined,
      definitionKey: typeof value.definitionKey === 'string' ? value.definitionKey : undefined,
      selectedEnds: stringArray(value.selectedEnds),
      timeWindows: savedWindows,
      metricFilter: metric && typeof metric.column === 'string' && typeof metric.min === 'string' && typeof metric.max === 'string' ? metric as MetricFilter : undefined,
      selectedScenarioIds: stringArray(value.selectedScenarioIds),
      selectedSchemaTags: stringArray(value.selectedSchemaTags),
      selectedUserTags: stringArray(value.selectedUserTags),
      sort: savedSort && typeof savedSort.column === 'string' && (savedSort.direction === 'asc' || savedSort.direction === 'desc') ? savedSort as EventSort : undefined,
      pinnedEventRefs: pins,
      hiddenPinnedEventKeys: stringArray(value.hiddenPinnedEventKeys),
    }
  } catch {
    return {}
  }
}
function finiteNumber(value: unknown): number | null { if (value === '' || value === null || value === undefined) return null; const number = Number(value); return Number.isFinite(number) ? number : null }
function formatNumber(value: unknown) { const number = finiteNumber(value); return number === null ? '—' : Math.abs(number) >= 100 ? number.toFixed(1) : number.toFixed(3) }
function formatValue(value: unknown) { if (value === null || value === undefined || value === '') return '—'; if (Array.isArray(value)) return value.length ? value.join(', ') : '—'; if (typeof value === 'object') return JSON.stringify(value); return String(value) }
function abbreviateHash(value: string | undefined) { if (!value) return '—'; return value.length > 20 ? `${value.slice(0, 12)}…${value.slice(-6)}` : value }
function titleCase(value: string) { return value.replace(/[_-]+/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()) }
