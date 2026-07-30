import { Filter, SlidersHorizontal } from 'lucide-react'
import { savedFilterCategoryLabel, type SavedSessionFilterRecord } from '../domain/sessionFilters'
import { InfoTip } from './Common'

export function FilterPanel({
  savedFilters,
  activeSavedFilterIds,
  trackpointFilterStates,
  onToggleSavedFilter,
  onClearSavedFilters,
  onManageSavedFilters,
}: {
  savedFilters: SavedSessionFilterRecord[]
  activeSavedFilterIds: string[]
  trackpointFilterStates: Array<{
    key: string
    label: string
    status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
    candidateSessionCount: number
    processedSessionCount: number
    matchedSessionCount: number
    error: string
  }>
  onToggleSavedFilter: (filterId: string) => void
  onClearSavedFilters: () => void
  onManageSavedFilters: () => void
}) {
  const filtersByCategory = groupedFilters(savedFilters)

  return (
    <div className="filter-panel">
      <div className="filter-panel-scroll">
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
          {filtersByCategory.map(({ category, items, showHeading }) => (
            <fieldset className="filter-category" key={category}>
              {showHeading && <legend>{savedFilterCategoryLabel(category)}</legend>}
              {items.map((filter) => (
                <div className="check-row compact filter-row filter-list-row" key={filter.id}>
                  <input
                    aria-label={`Apply ${filter.displayName}`}
                    type="checkbox"
                    checked={activeSavedFilterIds.includes(filter.id)}
                    onChange={() => onToggleSavedFilter(filter.id)}
                  />
                  <span className="filter-row-info-slot">
                    {filter.description && <InfoTip label={`${filter.displayName} description`} text={filter.description} />}
                  </span>
                  <button className="filter-list-summary" onClick={() => onToggleSavedFilter(filter.id)} type="button">
                    <strong>{filter.displayName}</strong>
                  </button>
                </div>
              ))}
            </fieldset>
          ))}
        </div>
      </div>

      <div className="filter-panel-actions">
        <button className="secondary-action compact-filter-action" onClick={onManageSavedFilters} type="button">
          <SlidersHorizontal size={13} />
          Manage filters
        </button>
        <button
          className="ghost-action compact-filter-action"
          disabled={activeSavedFilterIds.length === 0}
          onClick={onClearSavedFilters}
          type="button"
        >
          Clear
        </button>
      </div>
    </div>
  )
}

function groupedFilters(filters: SavedSessionFilterRecord[]) {
  const anyCategorized = filters.some((filter) => filter.category.trim())
  const groups = new Map<string, SavedSessionFilterRecord[]>()
  for (const filter of filters) {
    const category = anyCategorized ? filter.category.trim() || 'custom' : ''
    const items = groups.get(category) ?? []
    items.push(filter)
    groups.set(category, items)
  }
  return Array.from(groups.entries()).map(([category, items]) => ({
    category,
    showHeading: anyCategorized,
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
