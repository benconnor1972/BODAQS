import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type RefObject } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { Filter, X } from 'lucide-react'
import { columnLabels, getColumnText, isInfoActionColumn } from '../domain/sessionCatalog'
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
import {
  SessionDeleteButton,
  SessionInfoButtons,
  sessionInfoActionForColumn,
  type SessionInfoAction,
} from './SessionInfoButtons'

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
  onRenameSession,
  onCopyNote,
  onPasteNote,
  canPasteNote = false,
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
  onRenameSession?: (session: SessionRecord, name: string) => Promise<void>
  onCopyNote?: (session: SessionRecord) => void
  onPasteNote?: (session: SessionRecord) => void
  canPasteNote?: boolean
}) {
  const [openFilterColumnId, setOpenFilterColumnId] = useState<ColumnId | null>(null)
  const [filterSearchText, setFilterSearchText] = useState('')
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null)
  const [savingSessionId, setSavingSessionId] = useState<string | null>(null)
  const [contextMenu, setContextMenu] = useState<{ session: SessionRecord; x: number; y: number } | null>(null)
  const filterMenuRef = useRef<HTMLDivElement>(null)
  const contextMenuRef = useRef<HTMLDivElement>(null)
  const renameCommitInFlightRef = useRef<string | null>(null)
  const dataColumns = visibleColumns.filter((columnId) => !isInfoActionColumn(columnId))
  const canRenameSessions = Boolean(onRenameSession) && dataColumns.includes('name')
  const hasContextMenu = canRenameSessions || Boolean(onInspect) || Boolean(onCopyNote) || Boolean(onPasteNote)
  const infoActions = visibleColumns
    .map(sessionInfoActionForColumn)
    .filter((action): action is SessionInfoAction => Boolean(action))
  const columns: ColumnDef<SessionRecord>[] = dataColumns.map((columnId): ColumnDef<SessionRecord> => ({
      id: columnId,
      accessorFn: (session) => getColumnText(session, columnId, libraries),
      header: columnLabels[columnId],
      cell: (info) => {
        const session = info.row.original
        const sessionId = candidateId(session)
        if (columnId === 'name' && editingSessionId === sessionId) {
          return (
            <SessionRenameInput
              disabled={savingSessionId === sessionId}
              initialValue={session.sessionLabel || session.name}
              label={`Rename ${session.name}`}
              onCancel={cancelRename}
              onCommit={(value) => {
                void commitRename(session, value)
              }}
            />
          )
        }
        return String(info.getValue() ?? '')
      },
      enableSorting: true,
    }))
  columns.push({
    id: 'rowActions',
    header: '',
    cell: ({ row }) => (
      <div className="row-action-strip">
        {infoActions.length > 0 && (
          <span className="row-info-action-group">
            <SessionInfoButtons session={row.original} onInspect={onInspect} actions={infoActions} />
          </span>
        )}
        <SessionDeleteButton session={row.original} onDelete={onDeleteSession} />
      </div>
    ),
    enableSorting: false,
  })
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

  useEffect(() => {
    if (!contextMenu) {
      return
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }
      if (contextMenuRef.current?.contains(target)) {
        return
      }
      setContextMenu(null)
    }

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        setContextMenu(null)
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [contextMenu])

  function toggleFilterMenu(columnId: ColumnId) {
    setFilterSearchText('')
    setOpenFilterColumnId((current) => (current === columnId ? null : columnId))
  }

  function startRename(session: SessionRecord) {
    if (!canRenameSessions || !onRenameSession) {
      return
    }
    setContextMenu(null)
    setEditingSessionId(candidateId(session))
  }

  function cancelRename() {
    renameCommitInFlightRef.current = null
    setEditingSessionId(null)
    setSavingSessionId(null)
  }

  async function commitRename(session: SessionRecord, nextName: string) {
    if (!onRenameSession) {
      cancelRename()
      return
    }
    const sessionId = candidateId(session)
    if (editingSessionId !== sessionId || savingSessionId === sessionId || renameCommitInFlightRef.current === sessionId) {
      return
    }
    const trimmedName = nextName.trim()
    const currentName = (session.sessionLabel || session.name).trim()
    if (!trimmedName || trimmedName === currentName) {
      cancelRename()
      return
    }
    try {
      renameCommitInFlightRef.current = sessionId
      setSavingSessionId(sessionId)
      await onRenameSession(session, trimmedName)
      cancelRename()
    } catch {
      renameCommitInFlightRef.current = null
      setSavingSessionId(null)
    }
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
                  const isInfoActionHeader = columnId === 'rowActions'
                  const selectedFilterValues = isSortableSessionColumn
                    ? tableColumnFilters.find((filter) => filter.columnId === columnId)?.values ?? []
                    : []
                  return (
                    <th className={isInfoActionHeader ? 'info-action-heading' : undefined} key={header.id}>
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
                      ) : isInfoActionHeader ? (
                        <span title="Session info actions" />
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
                  onContextMenu={(event) => {
                    if (!hasContextMenu) {
                      return
                    }
                    event.preventDefault()
                    setContextMenu({ session, x: event.clientX, y: event.clientY })
                  }}
                  onKeyDown={(event) => handleRowKeyDown(event, session, onSelect, startRename)}
                  tabIndex={0}
                >
                  {row.getVisibleCells().map((cell) => {
                    const isInfoCell = cell.column.id === 'rowActions'
                    return (
                      <td
                        className={isInfoCell ? 'icon-cluster info-action-cell session-info-action-cell' : undefined}
                        key={cell.id}
                        onClick={(event) => {
                          if (isInfoCell) {
                            event.stopPropagation()
                            return
                          }
                          onSelect(session, mouseGesture(event))
                        }}
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
      {contextMenu && (
        <div
          className="session-row-context-menu"
          ref={contextMenuRef}
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            disabled={!canRenameSessions}
            onClick={() => startRename(contextMenu.session)}
            type="button"
          >
            Rename session
          </button>
          <div className="session-row-context-menu-separator" />
          <button
            onClick={() => {
              setContextMenu(null)
              onInspect(contextMenu.session, 'signals')
            }}
            type="button"
          >
            Inspect signals
          </button>
          <button
            onClick={() => {
              setContextMenu(null)
              onInspect(contextMenu.session, 'gps')
            }}
            type="button"
          >
            View GPS
          </button>
          <button
            onClick={() => {
              setContextMenu(null)
              onInspect(contextMenu.session, 'metadata')
            }}
            type="button"
          >
            View metadata
          </button>
          <button
            onClick={() => {
              setContextMenu(null)
              onInspect(contextMenu.session, 'qc')
            }}
            type="button"
          >
            View QA info
          </button>
          <div className="session-row-context-menu-separator" />
          <button
            disabled={!onCopyNote}
            onClick={() => {
              setContextMenu(null)
              onCopyNote?.(contextMenu.session)
            }}
            type="button"
          >
            Copy note
          </button>
          <button
            disabled={!canPasteNote || !onPasteNote}
            onClick={() => {
              setContextMenu(null)
              onPasteNote?.(contextMenu.session)
            }}
            type="button"
          >
            Paste note
          </button>
        </div>
      )}
    </>
  )
}

function SessionRenameInput({
  disabled,
  initialValue,
  label,
  onCancel,
  onCommit,
}: {
  disabled: boolean
  initialValue: string
  label: string
  onCancel: () => void
  onCommit: (value: string) => void
}) {
  const [value, setValue] = useState(initialValue)
  const inputRef = useRef<HTMLInputElement>(null)
  const skipBlurCommitRef = useRef(false)

  useEffect(() => {
    inputRef.current?.focus()
    inputRef.current?.select()
  }, [])

  return (
    <input
      aria-label={label}
      className="session-inline-edit"
      disabled={disabled}
      ref={inputRef}
      value={value}
      onBlur={() => {
        if (skipBlurCommitRef.current) {
          skipBlurCommitRef.current = false
          return
        }
        onCommit(value)
      }}
      onChange={(event) => setValue(event.target.value)}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        event.stopPropagation()
        if (event.key === 'Enter') {
          event.preventDefault()
          onCommit(value)
          return
        }
        if (event.key === 'Escape') {
          event.preventDefault()
          skipBlurCommitRef.current = true
          onCancel()
        }
      }}
      onPointerDown={(event) => event.stopPropagation()}
    />
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

function mouseGesture(event: MouseEvent<HTMLElement>): SessionSelectionGesture {
  return {
    extendRange: event.shiftKey,
    toggle: event.ctrlKey || event.metaKey,
  }
}

function handleRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
  session: SessionRecord,
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void,
  onRename?: (session: SessionRecord) => void,
) {
  if (event.key === 'F2' && onRename) {
    event.preventDefault()
    onRename(session)
    return
  }
  if (event.key === 'Enter') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: event.ctrlKey || event.metaKey })
  }
  if (event.key === ' ') {
    event.preventDefault()
    onSelect(session, { extendRange: event.shiftKey, toggle: true })
  }
}
