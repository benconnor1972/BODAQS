import { Filter, X } from 'lucide-react'
import { filterCategoryLabel, type SessionFilterRecord } from '../domain/sessionFilters'

export function FilterPanel({
  filters,
  activeFilterIds,
  totalCount,
  filteredCount,
  visibleCount,
  onToggleFilter,
  onClearFilters,
}: {
  filters: SessionFilterRecord[]
  activeFilterIds: string[]
  totalCount: number
  filteredCount: number
  visibleCount: number
  onToggleFilter: (filterId: string) => void
  onClearFilters: () => void
}) {
  const activeFilters = filters.filter((filter) => activeFilterIds.includes(filter.id))
  const filtersByCategory = groupedFilters(filters)

  return (
    <div className="filter-panel">
      <div className="filter-summary">
        <div>
          <strong>{filteredCount}</strong>
          <span>of {totalCount} match filters</span>
        </div>
        <div>
          <strong>{visibleCount}</strong>
          <span>shown after search</span>
        </div>
      </div>

      <div className="active-filter-stack">
        <div className="filter-stack-title">
          <Filter size={15} />
          <strong>Active filter stack</strong>
          <span className="pill neutral">AND</span>
        </div>
        {activeFilters.length === 0 ? (
          <p className="empty-note">No filters active. Session selector shows all selected-library sessions.</p>
        ) : (
          <div className="filter-chip-list">
            {activeFilters.map((filter) => (
              <button className="filter-chip" key={filter.id} onClick={() => onToggleFilter(filter.id)} type="button">
                {filter.displayName}
                <X size={13} />
              </button>
            ))}
            <button className="ghost-action compact-filter-action" onClick={onClearFilters} type="button">
              Clear filters
            </button>
          </div>
        )}
      </div>

      <div className="filter-library">
        {filtersByCategory.map(({ category, items }) => (
          <fieldset className="filter-category" key={category}>
            <legend>{filterCategoryLabel(category)}</legend>
            {items.map((filter) => (
              <label className="check-row compact filter-row" key={filter.id}>
                <input
                  type="checkbox"
                  checked={activeFilterIds.includes(filter.id)}
                  onChange={() => onToggleFilter(filter.id)}
                />
                <span>
                  <strong>{filter.displayName}</strong>
                  <small>{filter.description}</small>
                </span>
              </label>
            ))}
          </fieldset>
        ))}
      </div>
    </div>
  )
}

function groupedFilters(filters: SessionFilterRecord[]) {
  const groups = new Map<string, SessionFilterRecord[]>()
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
