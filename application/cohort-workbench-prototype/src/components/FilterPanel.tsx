import { Copy, Filter, SlidersHorizontal, Trash2, X } from 'lucide-react'
import { savedFilterCategoryLabel, type SavedSessionFilterRecord } from '../domain/sessionFilters'

export function FilterPanel({
  savedFilters,
  activeSavedFilterIds,
  totalCount,
  savedFilteredCount,
  visibleCount,
  activeTableFilterCount,
  trackpointFilterStates,
  canManageSavedFilters,
  onToggleSavedFilter,
  onClearSavedFilters,
  onManageSavedFilters,
  onCopySavedFilter,
  onDeleteSavedFilter,
}: {
  savedFilters: SavedSessionFilterRecord[]
  activeSavedFilterIds: string[]
  totalCount: number
  savedFilteredCount: number
  visibleCount: number
  activeTableFilterCount: number
  trackpointFilterStates: Array<{
    key: string
    label: string
    status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
    candidateSessionCount: number
    processedSessionCount: number
    matchedSessionCount: number
    error: string
  }>
  canManageSavedFilters: boolean
  onToggleSavedFilter: (filterId: string) => void
  onClearSavedFilters: () => void
  onManageSavedFilters: () => void
  onCopySavedFilter: (filter: SavedSessionFilterRecord) => void
  onDeleteSavedFilter: (filter: SavedSessionFilterRecord) => void
}) {
  const activeSavedFilters = savedFilters.filter((filter) => activeSavedFilterIds.includes(filter.id))
  const filtersByCategory = groupedFilters(savedFilters)

  return (
    <div className="filter-panel">
      <div className="filter-summary">
        <div>
          <strong>{savedFilteredCount}</strong>
          <span>of {totalCount} match saved filters</span>
        </div>
        <div>
          <strong>{visibleCount}</strong>
          <span>shown after table/search</span>
        </div>
      </div>

      <div className="active-filter-stack">
        <div className="filter-stack-title">
          <Filter size={15} />
          <strong>Active saved filters</strong>
          <span className="pill neutral">AND</span>
        </div>
        {activeSavedFilters.length === 0 ? (
          <p className="empty-note">No saved filters active. Session selector starts from all selected-library sessions.</p>
        ) : (
          <div className="filter-chip-list">
            {activeSavedFilters.map((filter) => (
              <button
                className="filter-chip"
                key={filter.id}
                onClick={() => onToggleSavedFilter(filter.id)}
                type="button"
              >
                {filter.displayName}
                <X size={13} />
              </button>
            ))}
            <button className="ghost-action compact-filter-action" onClick={onClearSavedFilters} type="button">
              Clear saved filters
            </button>
          </div>
        )}
      </div>

      <div className="active-filter-stack table-filter-stack">
        <div className="filter-stack-title">
          <SlidersHorizontal size={15} />
          <strong>Ad-hoc table filters</strong>
          <span className="pill neutral">column headers</span>
        </div>
        {activeTableFilterCount === 0 ? (
          <p className="empty-note">
            None active. These are temporary Session Selector header filters, separate from saved filters.
          </p>
        ) : (
          <p className="empty-note">
            {activeTableFilterCount} active in the Session Selector headers. Use the table chips or header menus to clear them.
          </p>
        )}
      </div>

      {trackpointFilterStates.length > 0 && (
        <div className="active-filter-stack table-filter-stack">
          <div className="filter-stack-title">
            <Filter size={15} />
            <strong>Trackpoint filters</strong>
            <span className="pill neutral">async</span>
          </div>
          <div className="geo-filter-status-list">
            {trackpointFilterStates.map((state) => (
              <div className="geo-filter-status-row" key={state.key}>
                <div>
                  <strong>{state.label}</strong>
                  <small>
                    {state.processedSessionCount}/{state.candidateSessionCount} processed, {state.matchedSessionCount} matched
                  </small>
                  {state.error && <small className="warning-text">{state.error}</small>}
                </div>
                <span className={geoFilterStatusClass(state.status)}>{state.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="filter-library">
        <div className="filter-library-title">
          <div>
            <strong>Saved filter library</strong>
            <span className="subtle">
              {canManageSavedFilters ? 'Writable saved filters.' : 'Read-only prototype entries.'}
            </span>
          </div>
          <button className="ghost-action compact-filter-action" onClick={onManageSavedFilters} type="button">
            <SlidersHorizontal size={13} />
            Manage
          </button>
        </div>
        {filtersByCategory.map(({ category, items }) => (
          <fieldset className="filter-category" key={category}>
            <legend>{savedFilterCategoryLabel(category)}</legend>
            {items.map((filter) => (
              <div className="check-row compact filter-row saved-filter-row" key={filter.id}>
                <input
                  aria-label={`Apply ${filter.displayName}`}
                  type="checkbox"
                  checked={activeSavedFilterIds.includes(filter.id)}
                  onChange={() => onToggleSavedFilter(filter.id)}
                />
                <button className="saved-filter-summary" onClick={() => onToggleSavedFilter(filter.id)} type="button">
                  <strong>{filter.displayName}</strong>
                  <small>{filter.description}</small>
                </button>
                <button
                  className="icon-button"
                  disabled={!canManageSavedFilters}
                  onClick={() => onCopySavedFilter(filter)}
                  title="Copy filter"
                  type="button"
                >
                  <Copy size={14} />
                </button>
                <button
                  className="icon-button icon-alert"
                  disabled={!canManageSavedFilters || filter.origin !== 'api_saved'}
                  onClick={() => onDeleteSavedFilter(filter)}
                  title={filter.origin === 'api_saved' ? 'Delete filter' : 'Prototype filters cannot be deleted'}
                  type="button"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </fieldset>
        ))}
      </div>
    </div>
  )
}

function groupedFilters(filters: SavedSessionFilterRecord[]) {
  const groups = new Map<string, SavedSessionFilterRecord[]>()
  for (const filter of filters) {
    const items = groups.get(filter.category) ?? []
    items.push(filter)
    groups.set(filter.category, items)
  }
  return Array.from(groups.entries()).map(([category, items]) => ({
    category,
    items: items.sort((a, b) => a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' })),
  }))
}

function geoFilterStatusClass(status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed') {
  if (status === 'completed') {
    return 'pill ok'
  }
  if (status === 'failed' || status === 'cancelled') {
    return 'pill alert'
  }
  return 'pill warning'
}
