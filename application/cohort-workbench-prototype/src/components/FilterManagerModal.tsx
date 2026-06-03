import { Copy, Plus, Save, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import type { SavedSessionFilterRecord, SessionFilterPredicate } from '../domain/sessionFilters'

const defaultPredicate: SessionFilterPredicate = { field: 'rider', op: 'contains', value: '' }

export function FilterManagerModal({
  filters,
  canWrite,
  onClose,
  onSave,
  onDelete,
}: {
  filters: SavedSessionFilterRecord[]
  canWrite: boolean
  onClose: () => void
  onSave: (filter: SavedSessionFilterRecord) => Promise<SavedSessionFilterRecord>
  onDelete: (filter: SavedSessionFilterRecord) => Promise<void>
}) {
  const [selectedId, setSelectedId] = useState<string | null>(filters[0]?.id ?? null)
  const [isNew, setIsNew] = useState(filters.length === 0)
  const [draft, setDraft] = useState<SavedSessionFilterRecord>(() => cloneFilter(filters[0] ?? emptyFilter()))
  const [predicateText, setPredicateText] = useState(() => JSON.stringify(draft.predicate, null, 2))
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  function selectFilter(filter: SavedSessionFilterRecord) {
    setSelectedId(filter.id)
    setIsNew(false)
    setDraft(cloneFilter(filter))
    setPredicateText(JSON.stringify(filter.predicate, null, 2))
    setStatus('')
  }

  function startNewFilter() {
    const next = emptyFilter()
    setSelectedId(null)
    setIsNew(true)
    setDraft(next)
    setPredicateText(JSON.stringify(next.predicate, null, 2))
    setStatus('')
  }

  function startCopy() {
    const next = {
      ...cloneFilter(draft),
      id: '',
      displayName: `${draft.displayName || 'Untitled filter'} copy`,
      origin: 'api_saved' as const,
      revision: 0,
    }
    setSelectedId(null)
    setIsNew(true)
    setDraft(next)
    setPredicateText(JSON.stringify(next.predicate, null, 2))
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
      predicate = parsePredicate(predicateText)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatus(`Predicate JSON is not valid: ${message}`)
      return
    }

    setBusy(true)
    try {
      const saving: SavedSessionFilterRecord =
        draft.origin === 'api_saved' && !isNew
          ? { ...draft, displayName, predicate }
          : { ...draft, id: '', displayName, origin: 'api_saved', revision: 0, predicate }
      const saved = await onSave(saving)
      setSelectedId(saved.id)
      setIsNew(false)
      setDraft(cloneFilter(saved))
      setPredicateText(JSON.stringify(saved.predicate, null, 2))
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

            <label className="filter-manager-row">
              Predicate JSON
              <textarea
                className="filter-manager-textarea"
                spellCheck={false}
                value={predicateText}
                onChange={(event) => setPredicateText(event.target.value)}
              />
            </label>

            <p className="modal-note">
              First-cut editor: predicates use the persisted filter contract directly. A visual builder can sit on top of
              this shape later.
            </p>

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
