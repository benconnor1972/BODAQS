import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type RefObject } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { Filter, X } from 'lucide-react'
import { columnLabels, getColumnText } from '../domain/sessionCatalog'
import { candidateId } from '../domain/studySets'
import {
  tableColumnFilterOptions,
  tableFilterLabel,
  type TableColumnFilter,
} from '../domain/tableFilters'
import type {
  ColumnId,
  LibraryRecord,
  SessionInspectionTab,
  SessionRecord,
  SortDirection,
} from '../domain/types'
import { SessionInfoButtons } from './SessionInfoButtons'

export type SessionSelectionGesture = {
  extendRange: boolean
  toggle: boolean
}

export function SessionTable({
  sessions: tableSessions,
  filterBaseSessions,
  libraries,
  visibleColumns,
  tableColumnFilters,
  selectedIds,
  primaryId,
  sortColumn,
  sortDirection,
  onTableColumnFilterChange,
  onClearTableColumnFilter,
  onSort,
  onSelect,
  onInspect,
  onDeleteSession,
}: {
  sessions: SessionRecord[]
  filterBaseSessions: SessionRecord[]
  libraries: LibraryRecord[]
  visibleColumns: ColumnId[]
  tableColumnFilters: TableColumnFilter[]
  selectedIds: string[]
  primaryId: string | null
  sortColumn: ColumnId
  sortDirection: SortDirection
  onTableColumnFilterChange: (columnId: ColumnId, values: string[]) => void
  onClearTableColumnFilter: (columnId: ColumnId) => void
  onSort: (columnId: ColumnId) => void
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
  onDeleteSession?: (session: SessionRecord) => void
}) {
  const [openFilterColumnId, setOpenFilterColumnId] = useState<ColumnId | null>(null)
  const [filterSearchText, setFilterSearchText] = useState('')
  const filterMenuRef = useRef<HTMLDivElement>(null)
  const columns: ColumnDef<SessionRecord>[] = [
    ...visibleColumns.map((columnId): ColumnDef<SessionRecord> => ({
      id: columnId,
      accessorFn: (session) => getColumnText(session, columnId, libraries),
      header: columnLabels[columnId],
      cell: (info) => String(info.getValue() ?? ''),
      enableSorting: true,
    })),
    {
      id: 'info',
      header: 'Info',
      cell: ({ row }) => (
        <SessionInfoButtons
          session={row.original}
          onInspect={onInspect}
          showDelete
          onDelete={onDeleteSession}
        />
      ),
      enableSorting: false,
    },
  ]
  // TanStack Table intentionally returns function-bearing instances; keep it local to this component.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: tableSessions,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: candidateId,
    manualSorting: true,
    state: {
      sorting: [{ id: sortColumn, desc: sortDirection === 'desc' }],
    },
  })

  useEffect(() => {
    if (!openFilterColumnId) {
      return
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }
      if (filterMenuRef.current?.contains(target)) {
        return
      }
      setOpenFilterColumnId(null)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
    }
  }, [openFilterColumnId])

  function toggleFilterMenu(columnId: ColumnId) {
    setFilterSearchText('')
    setOpenFilterColumnId((current) => (current === columnId ? null : columnId))
  }

  return (
    <>
      <div className="table-shell">
        <table className="session-table" aria-label="Candidate sessions">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const columnId = header.column.id
                  const isSortableSessionColumn = isColumnId(columnId)
                  const selectedFilterValues = isSortableSessionColumn
                    ? tableColumnFilters.find((filter) => filter.columnId === columnId)?.values ?? []
                    : []
                  return (
                    <th key={header.id}>
                      {isSortableSessionColumn ? (
                        <div className="column-header-control">
                          <button className="sort-button" onClick={() => onSort(columnId)} type="button">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sortColumn === columnId && <span>{sortDirection === 'asc' ? 'up' : 'down'}</span>}
                          </button>
                          <button
                            aria-expanded={openFilterColumnId === columnId}
                            className={`column-filter-button${selectedFilterValues.length ? ' active' : ''}`}
                            onClick={(event) => {
                              event.stopPropagation()
                              toggleFilterMenu(columnId)
                            }}
                            title={
                              selectedFilterValues.length
                                ? `${columnLabels[columnId]} filter applied`
                                : `Filter ${columnLabels[columnId]}`
                            }
                            type="button"
                          >
                            <Filter size={13} />
                          </button>
                          {openFilterColumnId === columnId && (
                            <ColumnFilterMenu
                              columnId={columnId}
                              libraries={libraries}
                              options={tableColumnFilterOptions(filterBaseSessions, columnId, libraries)}
                              searchText={filterSearchText}
                              selectedValues={selectedFilterValues}
                              menuRef={filterMenuRef}
                              onSearchTextChange={setFilterSearchText}
                              onChange={(values) => onTableColumnFilterChange(columnId, values)}
                              onClear={() => onClearTableColumnFilter(columnId)}
                              onClose={() => setOpenFilterColumnId(null)}
                            />
                          )}
                        </div>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </th>
                  )
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const session = row.original
              const id = candidateId(session)
              const isSelected = selectedIds.includes(id)
              const isPrimary = primaryId === id
              return (
                <tr
                  aria-current={isPrimary ? 'true' : undefined}
                  aria-selected={isSelected}
                  className={[
                    'session-row',
                    isSelected ? 'selected' : '',
                    isPrimary ? 'primary-row' : '',
                  ].join(' ')}
                  key={id}
                  onClick={(event) => onSelect(session, mouseGesture(event))}
                  onKeyDown={(event) => handleRowKeyDown(event, session, onSelect)}
                  tabIndex={0}
                >
                  {row.getVisibleCells().map((cell) => {
                    const isInfoCell = cell.column.id === 'info'
                    return (
                      <td
                        className={isInfoCell ? 'icon-cluster' : undefined}
                        key={cell.id}
                        onClick={isInfoCell ? (event) => event.stopPropagation() : undefined}
                      >
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}

function ColumnFilterMenu({
  columnId,
  libraries,
  options,
  searchText,
  selectedValues,
  menuRef,
  onSearchTextChange,
  onChange,
  onClear,
  onClose,
}: {
  columnId: ColumnId
  libraries: LibraryRecord[]
  options: string[]
  searchText: string
  selectedValues: string[]
  menuRef: RefObject<HTMLDivElement | null>
  onSearchTextChange: (value: string) => void
  onChange: (values: string[]) => void
  onClear: () => void
  onClose: () => void
}) {
  const visibleOptions = options.filter((option) =>
    tableFilterLabel(columnId, libraries, option).toLowerCase().includes(searchText.trim().toLowerCase()),
  )

  function toggleValue(value: string) {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((item) => item !== value))
      return
    }
    onChange([...selectedValues, value])
  }

  return (
    <div className="column-filter-popover" ref={menuRef}>
      <div className="column-filter-header">
        <strong>{columnLabels[columnId]}</strong>
        <button aria-label="Close column filter" onClick={onClose} type="button">
          <X size={14} />
        </button>
      </div>
      <input
        className="column-filter-search"
        value={searchText}
        onChange={(event) => onSearchTextChange(event.target.value)}
        placeholder="Search values"
      />
      <div className="column-filter-actions">
        <span>{selectedValues.length ? `${selectedValues.length} selected` : 'No filter'}</span>
        <button onClick={onClear} type="button">
          Clear
        </button>
      </div>
      <div className="column-filter-options">
        {visibleOptions.length === 0 && <p className="empty-note">No matching values.</p>}
        {visibleOptions.map((option) => (
          <label className="check-row compact column-filter-option" key={option}>
            <input
              type="checkbox"
              checked={selectedValues.includes(option)}
              onChange={() => toggleValue(option)}
            />
            <span>{tableFilterLabel(columnId, libraries, option)}</span>
          </label>
        ))}
      </div>
    </div>
  )
}

function isColumnId(value: string): value is ColumnId {
  return value in columnLabels
}

function mouseGesture(event: MouseEvent<HTMLTableRowElement>): SessionSelectionGesture {
  return {
    extendRange: event.shiftKey,
    toggle: event.ctrlKey || event.metaKey,
  }
}

function handleRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
  session: SessionRecord,
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void,
) {
  if (event.key === 'Enter') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: event.ctrlKey || event.metaKey })
  }
  if (event.key === ' ') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: true })
  }
}
