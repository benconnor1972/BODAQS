import { Copy, Plus, Save, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type {
  SavedSessionFilterRecord,
  SessionFilterField,
  SessionFilterPredicate,
  TrackpointCrossingFilterValue,
} from '../domain/sessionFilters'
import type { TrackRecord } from '../domain/types'

const defaultPredicate: SessionFilterPredicate = { field: 'rider', op: 'contains', value: '' }

type BuilderJoin = 'and' | 'or'
type BuilderMode = 'visual' | 'advanced'
type BuilderOperator = 'contains' | 'eq' | 'in' | 'present' | 'matches'

type FieldDefinition = {
  field: SessionFilterField
  label: string
  help: string
  operators: BuilderOperator[]
  values?: Array<{ value: string; label: string }>
  placeholder?: string
}

type BuilderCondition = {
  id: string
  field: SessionFilterField
  op: BuilderOperator
  value: string
  values: string[]
  boolValue: boolean
  trackId: string
  trackpointIds: string[]
  matchMode: 'any' | 'all' | 'min_count'
  toleranceM: string
  minCount: string
}

type PredicateBuilder = {
  join: BuilderJoin
  conditions: BuilderCondition[]
}

const fieldDefinitions: FieldDefinition[] = [
  {
    field: 'rider',
    label: 'Rider',
    help: 'Matches the rider value from session notes/catalog metadata.',
    operators: ['contains', 'eq', 'in'],
    placeholder: 'Ben',
  },
  {
    field: 'bike',
    label: 'Bike',
    help: 'Matches the bike/profile label carried in the catalog.',
    operators: ['contains', 'eq', 'in'],
    placeholder: 'Prototype F',
  },
  {
    field: 'note.status',
    label: 'Note status',
    help: 'Filters by session note state.',
    operators: ['eq', 'in'],
    values: [
      { value: 'missing', label: 'Missing' },
      { value: 'draft', label: 'Draft' },
      { value: 'edited', label: 'Edited' },
    ],
  },
  {
    field: 'qc.level',
    label: 'QC level',
    help: 'Filters by overall QC severity.',
    operators: ['eq', 'in'],
    values: [
      { value: 'ok', label: 'OK' },
      { value: 'warning', label: 'Warning' },
      { value: 'alert', label: 'Alert' },
    ],
  },
  {
    field: 'gps.present',
    label: 'GPS present',
    help: 'Filters sessions by whether any GPS source is present.',
    operators: ['present'],
  },
  {
    field: 'gps.quality',
    label: 'GPS quality',
    help: 'Filters by GPS completeness/quality summary.',
    operators: ['eq', 'in'],
    values: [
      { value: 'absent', label: 'Absent' },
      { value: 'limited', label: 'Limited' },
      { value: 'usable', label: 'Usable' },
      { value: 'invalid', label: 'Invalid' },
    ],
  },
  {
    field: 'gps.source',
    label: 'GPS source',
    help: 'Filters by GPS source type or stream name.',
    operators: ['eq', 'in', 'contains'],
    values: [
      { value: 'fit_enrichment', label: 'FIT enrichment' },
      { value: 'logger_sensor', label: 'Logger sensor' },
      { value: 'imported_route', label: 'Imported route' },
      { value: 'unknown', label: 'Unknown' },
    ],
  },
  {
    field: 'signals',
    label: 'Signals',
    help: 'Matches available signal names.',
    operators: ['contains', 'eq', 'in'],
    placeholder: 'accelerometer',
  },
  {
    field: 'event.schema',
    label: 'Event schema',
    help: 'Matches event schema IDs.',
    operators: ['contains', 'eq', 'in'],
    placeholder: 'bottom_out',
  },
  {
    field: 'preprocessing.profile',
    label: 'Preprocess profile',
    help: 'Matches the preprocessing profile recorded in the catalog.',
    operators: ['contains', 'eq', 'in'],
    placeholder: 'default',
  },
  {
    field: 'firmware',
    label: 'Firmware',
    help: 'Matches firmware version metadata.',
    operators: ['contains', 'eq', 'in'],
    placeholder: '0.3.0',
  },
  {
    field: 'source.archive',
    label: 'Source archive',
    help: 'Matches the original source/archive filename.',
    operators: ['contains', 'eq', 'in'],
    placeholder: '2026-02',
  },
  {
    field: 'trackpoint.crossing',
    label: 'Trackpoint crossing',
    help: 'Runs an async GPS/trackpoint match query against selected libraries.',
    operators: ['matches'],
  },
]

export function FilterManagerModal({
  filters,
  tracks,
  canWrite,
  onClose,
  onSave,
  onDelete,
}: {
  filters: SavedSessionFilterRecord[]
  tracks: TrackRecord[]
  canWrite: boolean
  onClose: () => void
  onSave: (filter: SavedSessionFilterRecord) => Promise<SavedSessionFilterRecord>
  onDelete: (filter: SavedSessionFilterRecord) => Promise<void>
}) {
  const initialFilter = filters[0] ?? emptyFilter()
  const initialEditor = editorStateForPredicate(initialFilter.predicate, tracks)
  const [selectedId, setSelectedId] = useState<string | null>(filters[0]?.id ?? null)
  const [isNew, setIsNew] = useState(filters.length === 0)
  const [draft, setDraft] = useState<SavedSessionFilterRecord>(() => cloneFilter(initialFilter))
  const [builder, setBuilder] = useState<PredicateBuilder>(initialEditor.builder)
  const [editorMode, setEditorMode] = useState<BuilderMode>(initialEditor.mode)
  const [advancedText, setAdvancedText] = useState(initialEditor.advancedText)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  function loadFilter(filter: SavedSessionFilterRecord, nextIsNew: boolean) {
    const nextEditor = editorStateForPredicate(filter.predicate, tracks)
    setSelectedId(nextIsNew ? null : filter.id)
    setIsNew(nextIsNew)
    setDraft(cloneFilter(filter))
    setBuilder(nextEditor.builder)
    setEditorMode(nextEditor.mode)
    setAdvancedText(nextEditor.advancedText)
    setStatus(nextEditor.mode === 'advanced' ? 'This predicate is using the advanced JSON fallback.' : '')
  }

  function selectFilter(filter: SavedSessionFilterRecord) {
    loadFilter(filter, false)
  }

  function startNewFilter() {
    loadFilter(emptyFilter(), true)
  }

  function startCopy() {
    const predicate = currentPredicateOrDraft()
    const next = {
      ...cloneFilter(draft),
      id: '',
      displayName: `${draft.displayName || 'Untitled filter'} copy`,
      origin: 'api_saved' as const,
      revision: 0,
      predicate,
    }
    loadFilter(next, true)
    setStatus('Editing a new persisted copy.')
  }

  async function saveDraft() {
    const displayName = draft.displayName.trim()
    if (!displayName) {
      setStatus('Name the filter before saving.')
      return
    }

    let predicate: SessionFilterPredicate
    try {
      predicate = editorMode === 'advanced' ? parsePredicate(advancedText) : buildPredicate(builder)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatus(`Filter definition is not valid: ${message}`)
      return
    }

    setBusy(true)
    try {
      const saving: SavedSessionFilterRecord =
        draft.origin === 'api_saved' && !isNew
          ? { ...draft, displayName, predicate }
          : { ...draft, id: '', displayName, origin: 'api_saved', revision: 0, predicate }
      const saved = await onSave(saving)
      loadFilter(saved, false)
      setStatus(`Saved "${saved.displayName}".`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatus(`Could not save filter: ${message}`)
    } finally {
      setBusy(false)
    }
  }

  async function deleteDraft() {
    if (isNew || draft.origin !== 'api_saved') {
      return
    }
    if (!window.confirm(`Delete saved filter "${draft.displayName}"?`)) {
      return
    }

    setBusy(true)
    try {
      await onDelete(draft)
      setStatus(`Deleted "${draft.displayName}".`)
      const remaining = filters.filter((filter) => filter.id !== draft.id)
      if (remaining.length > 0) {
        selectFilter(remaining[0])
      } else {
        startNewFilter()
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatus(`Could not delete filter: ${message}`)
    } finally {
      setBusy(false)
    }
  }

  function currentPredicateOrDraft() {
    try {
      return editorMode === 'advanced' ? parsePredicate(advancedText) : buildPredicate(builder)
    } catch {
      return draft.predicate
    }
  }

  function toggleEditorMode() {
    try {
      if (editorMode === 'visual') {
        setAdvancedText(JSON.stringify(buildPredicate(builder), null, 2))
        setEditorMode('advanced')
        setStatus('')
        return
      }
      const next = editorStateForPredicate(parsePredicate(advancedText), tracks)
      setBuilder(next.builder)
      setEditorMode(next.mode)
      setStatus(next.mode === 'advanced' ? 'That JSON is too complex for this visual builder.' : '')
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatus(`Could not switch editor mode: ${message}`)
    }
  }

  const canDelete = canWrite && !isNew && draft.origin === 'api_saved'
  const saveLabel = draft.origin === 'api_saved' && !isNew ? 'Save filter' : 'Save persisted copy'

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="Filter manager" className="modal filter-manager-modal" role="dialog">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Saved filter library</p>
            <h2>Filter Manager</h2>
          </div>
          <button aria-label="Close filter manager" className="icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>

        <div className="modal-content filter-manager-content">
          <aside className="filter-manager-list" aria-label="Saved filters">
            <div className="filter-manager-list-header">
              <strong>{filters.length} filters</strong>
              <button className="ghost-action compact-filter-action" onClick={startNewFilter} type="button">
                <Plus size={13} />
                New
              </button>
            </div>
            {filters.length === 0 ? (
              <p className="empty-note">No persisted filters yet. Create one from the editor.</p>
            ) : (
              filters.map((filter) => (
                <button
                  className={`filter-manager-list-item${filter.id === selectedId && !isNew ? ' selected' : ''}`}
                  key={filter.id}
                  onClick={() => selectFilter(filter)}
                  type="button"
                >
                  <strong>{filter.displayName}</strong>
                  <small>
                    {filter.category || 'custom'} / {filter.origin === 'api_saved' ? `r${filter.revision}` : 'prototype'}
                  </small>
                </button>
              ))
            )}
          </aside>

          <section className="filter-manager-form" aria-label="Filter editor">
            <div className="filter-manager-row two-columns">
              <label>
                Name
                <input
                  value={draft.displayName}
                  onChange={(event) => setDraft((current) => ({ ...current, displayName: event.target.value }))}
                />
              </label>
              <label>
                Category
                <input
                  value={draft.category}
                  onChange={(event) => setDraft((current) => ({ ...current, category: event.target.value }))}
                />
              </label>
            </div>

            <label className="filter-manager-row">
              Description
              <input
                value={draft.description}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
              />
            </label>

            {editorMode === 'visual' ? (
              <VisualFilterBuilder builder={builder} tracks={tracks} onChange={setBuilder} />
            ) : (
              <label className="filter-manager-row">
                Advanced predicate JSON
                <textarea
                  className="filter-manager-textarea"
                  spellCheck={false}
                  value={advancedText}
                  onChange={(event) => setAdvancedText(event.target.value)}
                />
              </label>
            )}

            <div className="filter-builder-footer">
              <p className="modal-note">
                Visual filters are saved as the same persisted predicate contract. Trackpoint filters will run async
                library queries when applied.
              </p>
              <button
                className="ghost-action compact-filter-action"
                onClick={toggleEditorMode}
                type="button"
              >
                {editorMode === 'visual' ? 'Advanced JSON' : 'Try visual builder'}
              </button>
            </div>

            {status && <p className="modal-status">{status}</p>}
            {!canWrite && (
              <p className="modal-status warning">Current data source is read-only for saved filters.</p>
            )}

            <div className="dialog-actions">
              <button className="ghost-action" disabled={busy} onClick={startCopy} type="button">
                <Copy size={14} />
                Copy
              </button>
              <button className="danger-action" disabled={!canDelete || busy} onClick={deleteDraft} type="button">
                <Trash2 size={14} />
                Delete
              </button>
              <button className="primary-action" disabled={!canWrite || busy} onClick={saveDraft} type="button">
                <Save size={14} />
                {saveLabel}
              </button>
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}

function VisualFilterBuilder({
  builder,
  tracks,
  onChange,
}: {
  builder: PredicateBuilder
  tracks: TrackRecord[]
  onChange: (builder: PredicateBuilder) => void
}) {
  function updateCondition(conditionId: string, updates: Partial<BuilderCondition>) {
    onChange({
      ...builder,
      conditions: builder.conditions.map((condition) =>
        condition.id === conditionId ? { ...condition, ...updates } : condition,
      ),
    })
  }

  function removeCondition(conditionId: string) {
    const nextConditions = builder.conditions.filter((condition) => condition.id !== conditionId)
    onChange({
      ...builder,
      conditions: nextConditions.length ? nextConditions : [defaultCondition()],
    })
  }

  return (
    <section className="visual-filter-builder" aria-label="Visual predicate builder">
      <div className="visual-filter-toolbar">
        <label>
          Match
          <select
            value={builder.join}
            onChange={(event) => onChange({ ...builder, join: event.target.value as BuilderJoin })}
          >
            <option value="and">All conditions</option>
            <option value="or">Any condition</option>
          </select>
        </label>
        <button
          className="ghost-action compact-filter-action"
          onClick={() => onChange({ ...builder, conditions: [...builder.conditions, defaultCondition()] })}
          type="button"
        >
          <Plus size={13} />
          Condition
        </button>
      </div>

      <div className="condition-stack">
        {builder.conditions.map((condition, index) => (
          <div className="condition-card" key={condition.id}>
            <div className="condition-card-header">
              <strong>Condition {index + 1}</strong>
              <button
                aria-label={`Remove condition ${index + 1}`}
                className="icon-button"
                onClick={() => removeCondition(condition.id)}
                type="button"
              >
                <X size={14} />
              </button>
            </div>

            <div className="condition-main-grid">
              <label>
                Field
                <select
                  value={condition.field}
                  onChange={(event) => {
                    const field = event.target.value as SessionFilterField
                    const definition = definitionForField(field)
                    updateCondition(condition.id, resetConditionForField(condition, definition))
                  }}
                >
                  {fieldDefinitions.map((definition) => (
                    <option key={definition.field} value={definition.field}>
                      {definition.label}
                    </option>
                  ))}
                </select>
              </label>

              {condition.field === 'trackpoint.crossing' ? (
                <TrackpointConditionEditor
                  condition={condition}
                  tracks={tracks}
                  onChange={(updates) => updateCondition(condition.id, updates)}
                />
              ) : (
                <CatalogConditionEditor
                  condition={condition}
                  onChange={(updates) => updateCondition(condition.id, updates)}
                />
              )}
            </div>
            <p className="condition-help">{definitionForField(condition.field).help}</p>
          </div>
        ))}
      </div>
    </section>
  )
}

function CatalogConditionEditor({
  condition,
  onChange,
}: {
  condition: BuilderCondition
  onChange: (updates: Partial<BuilderCondition>) => void
}) {
  const definition = definitionForField(condition.field)
  return (
    <>
      <label>
        Operator
        <select value={condition.op} onChange={(event) => onChange({ op: event.target.value as BuilderOperator })}>
          {definition.operators.map((operator) => (
            <option key={operator} value={operator}>
              {operatorLabel(operator)}
            </option>
          ))}
        </select>
      </label>
      <div className="condition-value-cell">
        {condition.op === 'present' ? (
          <label>
            Presence
            <select
              value={String(condition.boolValue)}
              onChange={(event) => onChange({ boolValue: event.target.value === 'true' })}
            >
              <option value="true">Present</option>
              <option value="false">Missing</option>
            </select>
          </label>
        ) : definition.values ? (
          <EnumConditionValue condition={condition} definition={definition} onChange={onChange} />
        ) : (
          <label>
            Value
            <input
              placeholder={condition.op === 'in' ? 'comma,separated,values' : definition.placeholder}
              value={condition.value}
              onChange={(event) => onChange({ value: event.target.value })}
            />
          </label>
        )}
      </div>
    </>
  )
}

function EnumConditionValue({
  condition,
  definition,
  onChange,
}: {
  condition: BuilderCondition
  definition: FieldDefinition
  onChange: (updates: Partial<BuilderCondition>) => void
}) {
  if (condition.op === 'contains') {
    return (
      <label>
        Value
        <input value={condition.value} onChange={(event) => onChange({ value: event.target.value })} />
      </label>
    )
  }
  if (condition.op === 'in') {
    return (
      <div className="enum-picker">
        {definition.values?.map((item) => (
          <label className="mini-check" key={item.value}>
            <input
              checked={condition.values.includes(item.value)}
              onChange={() => onChange({ values: toggleString(condition.values, item.value) })}
              type="checkbox"
            />
            {item.label}
          </label>
        ))}
      </div>
    )
  }
  return (
    <label>
      Value
      <select value={condition.value} onChange={(event) => onChange({ value: event.target.value })}>
        {definition.values?.map((item) => (
          <option key={item.value} value={item.value}>
            {item.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function TrackpointConditionEditor({
  condition,
  tracks,
  onChange,
}: {
  condition: BuilderCondition
  tracks: TrackRecord[]
  onChange: (updates: Partial<BuilderCondition>) => void
}) {
  const selectedTrack = tracks.find((track) => track.id === condition.trackId) ?? tracks[0] ?? null
  return (
    <div className="trackpoint-condition-grid">
      <label>
        Track
        <select
          value={condition.trackId}
          onChange={(event) => {
            const track = tracks.find((item) => item.id === event.target.value)
            onChange({
              trackId: event.target.value,
              trackpointIds: track?.trackpoints[0] ? [track.trackpoints[0].id] : [],
            })
          }}
        >
          <option value="">Select track</option>
          {tracks.map((track) => (
            <option key={track.id} value={track.id}>
              {track.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Match mode
        <select
          value={condition.matchMode}
          onChange={(event) => onChange({ matchMode: event.target.value as BuilderCondition['matchMode'] })}
        >
          <option value="all">All selected points</option>
          <option value="any">Any selected point</option>
          <option value="min_count">Minimum count</option>
        </select>
      </label>
      <label>
        Tolerance
        <input value={condition.toleranceM} onChange={(event) => onChange({ toleranceM: event.target.value })} />
      </label>
      {condition.matchMode === 'min_count' && (
        <label>
          Min count
          <input value={condition.minCount} onChange={(event) => onChange({ minCount: event.target.value })} />
        </label>
      )}
      <div className="trackpoint-picker">
        <strong>{selectedTrack ? `${selectedTrack.trackpoints.length} trackpoints` : 'No track selected'}</strong>
        {selectedTrack ? (
          selectedTrack.trackpoints.map((trackpoint) => (
            <label className="mini-check" key={trackpoint.id}>
              <input
                checked={condition.trackpointIds.includes(trackpoint.id)}
                onChange={() => onChange({ trackpointIds: toggleString(condition.trackpointIds, trackpoint.id) })}
                type="checkbox"
              />
              {trackpoint.name}
              <small>{trackpoint.stationM.toFixed(0)} m</small>
            </label>
          ))
        ) : (
          <span className="empty-note">Create a track in the Geospatial Workbench before using this condition.</span>
        )}
      </div>
    </div>
  )
}

function emptyFilter(): SavedSessionFilterRecord {
  return {
    id: '',
    displayName: '',
    description: '',
    category: 'custom',
    origin: 'api_saved',
    revision: 0,
    predicate: defaultPredicate,
  }
}

function editorStateForPredicate(predicate: SessionFilterPredicate, tracks: TrackRecord[]) {
  const builder = builderFromPredicate(predicate, tracks)
  if (builder) {
    return {
      mode: 'visual' as const,
      builder,
      advancedText: JSON.stringify(predicate, null, 2),
    }
  }
  return {
    mode: 'advanced' as const,
    builder: defaultBuilder(),
    advancedText: JSON.stringify(predicate, null, 2),
  }
}

function builderFromPredicate(predicate: SessionFilterPredicate, tracks: TrackRecord[]): PredicateBuilder | null {
  if ('children' in predicate) {
    const children = predicate.children.map((child) => conditionFromPredicate(child, tracks))
    if (children.some((child) => child === null)) {
      return null
    }
    return {
      join: predicate.op,
      conditions: children as BuilderCondition[],
    }
  }
  const condition = conditionFromPredicate(predicate, tracks)
  return condition ? { join: 'and', conditions: [condition] } : null
}

function conditionFromPredicate(predicate: SessionFilterPredicate, tracks: TrackRecord[]): BuilderCondition | null {
  if ('children' in predicate) {
    return null
  }
  if (predicate.field === 'trackpoint.crossing') {
    const value = predicate.value
    return trackpointConditionFromValue(value, tracks)
  }
  const definition = definitionForField(predicate.field)
  if (!definition.operators.includes(predicate.op)) {
    return null
  }
  const value = Array.isArray(predicate.value) ? predicate.value.join(', ') : String(predicate.value ?? '')
  return {
    ...defaultCondition(predicate.field),
    op: predicate.op,
    value,
    values: Array.isArray(predicate.value) ? predicate.value.map(String) : [String(predicate.value ?? '')].filter(Boolean),
    boolValue: typeof predicate.value === 'boolean' ? predicate.value : true,
  }
}

function trackpointConditionFromValue(value: TrackpointCrossingFilterValue, tracks: TrackRecord[]): BuilderCondition {
  const trackId = textValue(value.track_id ?? value.trackId)
  const fallbackTrackId = trackId || tracks[0]?.id || ''
  const track = tracks.find((item) => item.id === fallbackTrackId) ?? tracks[0] ?? null
  const rawIds =
    value.trackpoint_ids ?? value.trackpointIds ?? (value.trackpoint_id ?? value.trackpointId ? [value.trackpoint_id ?? value.trackpointId] : [])
  return {
    ...defaultCondition('trackpoint.crossing'),
    trackId: fallbackTrackId,
    trackpointIds: rawIds.length ? rawIds.map(textValue).filter(Boolean) : track?.trackpoints[0] ? [track.trackpoints[0].id] : [],
    matchMode: matchModeValue(value.match_mode ?? value.matchMode),
    toleranceM: String(numberValue(value.tolerance_m ?? value.toleranceM, 5)),
    minCount: String(numberValue(value.min_count ?? value.minCount, 1)),
  }
}

function defaultBuilder(): PredicateBuilder {
  return {
    join: 'and',
    conditions: [defaultCondition()],
  }
}

function defaultCondition(field: SessionFilterField = 'rider'): BuilderCondition {
  const definition = definitionForField(field)
  const firstValue = definition.values?.[0]?.value ?? ''
  return {
    id: nextConditionId(),
    field,
    op: definition.operators[0],
    value: firstValue,
    values: firstValue ? [firstValue] : [],
    boolValue: true,
    trackId: '',
    trackpointIds: [],
    matchMode: 'all',
    toleranceM: '5',
    minCount: '1',
  }
}

function resetConditionForField(condition: BuilderCondition, definition: FieldDefinition): BuilderCondition {
  return {
    ...defaultCondition(definition.field),
    id: condition.id,
  }
}

function buildPredicate(builder: PredicateBuilder): SessionFilterPredicate {
  const children = builder.conditions.map(conditionToPredicate)
  if (children.length === 0) {
    throw new Error('add at least one condition')
  }
  return children.length === 1 ? children[0] : { op: builder.join, children }
}

function conditionToPredicate(condition: BuilderCondition): SessionFilterPredicate {
  if (condition.field === 'trackpoint.crossing') {
    if (!condition.trackId) {
      throw new Error('trackpoint crossing needs a track')
    }
    if (condition.trackpointIds.length === 0) {
      throw new Error('trackpoint crossing needs at least one trackpoint')
    }
    const toleranceM = Number(condition.toleranceM)
    if (!Number.isFinite(toleranceM) || toleranceM < 0) {
      throw new Error('trackpoint tolerance must be a non-negative number')
    }
    const value: TrackpointCrossingFilterValue = {
      track_id: condition.trackId,
      trackpoint_ids: condition.trackpointIds,
      match_mode: condition.matchMode,
      tolerance_m: toleranceM,
    }
    if (condition.matchMode === 'min_count') {
      const minCount = Number(condition.minCount)
      if (!Number.isFinite(minCount) || minCount < 1) {
        throw new Error('trackpoint minimum count must be at least 1')
      }
      value.min_count = minCount
    }
    return {
      field: 'trackpoint.crossing',
      op: 'matches',
      value,
    }
  }

  if (condition.op === 'present') {
    return {
      field: condition.field,
      op: 'present',
      value: condition.boolValue,
    }
  }
  if (condition.op === 'in') {
    const values = condition.values.length ? condition.values : splitValues(condition.value)
    return {
      field: condition.field,
      op: 'in',
      value: values,
    }
  }
  if (condition.op === 'eq' || condition.op === 'contains') {
    return {
      field: condition.field,
      op: condition.op,
      value: condition.value,
    }
  }
  throw new Error(`unsupported operator ${condition.op}`)
}

function cloneFilter(filter: SavedSessionFilterRecord): SavedSessionFilterRecord {
  return {
    ...filter,
    predicate: JSON.parse(JSON.stringify(filter.predicate)) as SessionFilterPredicate,
  }
}

function parsePredicate(text: string): SessionFilterPredicate {
  const parsed = JSON.parse(text) as unknown
  if (!isPredicate(parsed)) {
    throw new Error('expected a predicate object with op plus either children or field')
  }
  return parsed
}

function isPredicate(value: unknown): value is SessionFilterPredicate {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }
  const candidate = value as Record<string, unknown>
  if (candidate.op === 'and' || candidate.op === 'or') {
    return Array.isArray(candidate.children) && candidate.children.every(isPredicate)
  }
  return typeof candidate.field === 'string' && typeof candidate.op === 'string'
}

function definitionForField(field: SessionFilterField): FieldDefinition {
  return fieldDefinitions.find((definition) => definition.field === field) ?? fieldDefinitions[0]
}

function operatorLabel(operator: BuilderOperator) {
  switch (operator) {
    case 'contains':
      return 'contains'
    case 'eq':
      return 'is'
    case 'in':
      return 'is one of'
    case 'present':
      return 'is'
    case 'matches':
      return 'matches'
  }
}

function toggleString(values: string[], value: string) {
  if (values.includes(value)) {
    return values.filter((item) => item !== value)
  }
  return [...values, value]
}

function splitValues(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function textValue(value: unknown) {
  return String(value ?? '').trim()
}

function numberValue(value: unknown, fallback: number) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function matchModeValue(value: unknown): 'any' | 'all' | 'min_count' {
  if (value === 'any' || value === 'min_count') {
    return value
  }
  return 'all'
}

let conditionIdCounter = 0

function nextConditionId() {
  conditionIdCounter += 1
  return `condition-${conditionIdCounter}`
}
