import { Copy, Filter, SlidersHorizontal, Trash2, X } from 'lucide-react'
import { savedFilterCategoryLabel, type SavedSessionFilterRecord } from '../domain/sessionFilters'

export function FilterPanel({
  savedFilters,
  activeSavedFilterIds,
  totalCount,
  savedFilteredCount,
  visibleCount,
  onToggleSavedFilter,
  onClearSavedFilters,
}: {
  savedFilters: SavedSessionFilterRecord[]
  activeSavedFilterIds: string[]
  totalCount: number
  savedFilteredCount: number
  visibleCount: number
  onToggleSavedFilter: (filterId: string) => void
  onClearSavedFilters: () => void
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
        <p className="empty-note">
          None yet. These will be temporary Session Selector header filters, separate from saved filters.
        </p>
      </div>

      <div className="filter-library">
        <div className="filter-library-title">
          <strong>Saved filter library</strong>
          <span className="subtle">Prototype entries until API persistence is wired.</span>
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
                <button className="icon-button" disabled title="Copy filter after persistence endpoints are wired" type="button">
                  <Copy size={14} />
                </button>
                <button className="icon-button icon-alert" disabled title="Delete filter after persistence endpoints are wired" type="button">
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
