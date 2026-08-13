import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { Filter, LoaderCircle, X } from 'lucide-react'
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

export type SessionColumnWidthId = ColumnId | 'rowActions'
export type SessionColumnWidths = Partial<Record<SessionColumnWidthId, number>>

const defaultColumnWidths: Record<ColumnId, number> = {
  name: 230,
  runName: 160,
  started: 145,
  library: 130,
  runId: 170,
  sessionId: 145,
  bike: 150,
  rider: 135,
  duration: 92,
  distance: 92,
  profile: 140,
  eventSchema: 150,
  firmware: 105,
  source: 165,
  signals: 105,
  gps: 92,
  noteAction: 0,
  qaAction: 0,
  gpsAction: 0,
  videoAction: 0,
  signalInspectorAction: 0,
  metadataAction: 0,
}

const minColumnWidths: Record<ColumnId, number> = {
  name: 54,
  runName: 48,
  started: 54,
  library: 48,
  runId: 48,
  sessionId: 48,
  bike: 42,
  rider: 42,
  duration: 42,
  distance: 42,
  profile: 48,
  eventSchema: 48,
  firmware: 42,
  source: 48,
  signals: 42,
  gps: 36,
  noteAction: 0,
  qaAction: 0,
  gpsAction: 0,
  videoAction: 0,
  signalInspectorAction: 0,
  metadataAction: 0,
}

const RENAME_CLICK_DELAY_MS = 350

function rowActionsWidth(actionCount: number) {
  return Math.max(minRowActionsWidth(actionCount), 38 + actionCount * 28)
}

function minRowActionsWidth(actionCount: number) {
  return Math.max(76, 34 + actionCount * 26)
}

function minColumnWidth(columnId: SessionColumnWidthId, actionCount: number) {
  return columnId === 'rowActions' ? minRowActionsWidth(actionCount) : minColumnWidths[columnId]
}

function effectiveColumnWidth(columnId: SessionColumnWidthId, persistedWidth: number | undefined, actionCount: number) {
  const minimum = minColumnWidth(columnId, actionCount)
  const fallback = columnId === 'rowActions' ? rowActionsWidth(actionCount) : defaultColumnWidths[columnId]
  const safeWidth = typeof persistedWidth === 'number' && Number.isFinite(persistedWidth) ? persistedWidth : fallback
  return Math.max(minimum, Math.round(safeWidth))
}

export type SessionSelectionGesture = {
  extendRange: boolean
  toggle: boolean
}

export function SessionTable({
  sessions: tableSessions,
  filterBaseSessions,
  libraries,
  visibleColumns,
  columnWidths,
  tableColumnFilters,
  selectedIds,
  primaryId,
  sortColumn,
  sortDirection,
  onTableColumnFilterChange,
  onClearTableColumnFilter,
  onColumnWidthsChange,
  onSort,
  onSelect,
  onAnalyzeSession,
  onInspect,
  onDeleteSession,
  onRenameSession,
  onCopyNote,
  onPasteNote,
  notePasteSavingIds,
  canPasteNote = false,
}: {
  sessions: SessionRecord[]
  filterBaseSessions: SessionRecord[]
  libraries: LibraryRecord[]
  visibleColumns: ColumnId[]
  columnWidths: SessionColumnWidths
  tableColumnFilters: TableColumnFilter[]
  selectedIds: string[]
  primaryId: string | null
  sortColumn: ColumnId
  sortDirection: SortDirection
  onTableColumnFilterChange: (columnId: ColumnId, values: string[]) => void
  onClearTableColumnFilter: (columnId: ColumnId) => void
  onColumnWidthsChange: (widths: SessionColumnWidths) => void
  onSort: (columnId: ColumnId) => void
  onSelect: (session: SessionRecord, gesture: SessionSelectionGesture) => void
  onAnalyzeSession?: (session: SessionRecord) => void
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
  onDeleteSession?: (session: SessionRecord) => void
  onRenameSession?: (session: SessionRecord, name: string) => Promise<void>
  onCopyNote?: (session: SessionRecord) => void
  onPasteNote?: (session: SessionRecord) => void
  notePasteSavingIds?: ReadonlySet<string>
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
  const pendingRenameTimeoutRef = useRef<number | null>(null)
  const dataColumns = visibleColumns.filter((columnId) => !isInfoActionColumn(columnId))
  const canRenameSessions = Boolean(onRenameSession) && dataColumns.includes('name')
  const hasContextMenu = canRenameSessions || Boolean(onInspect) || Boolean(onCopyNote) || Boolean(onPasteNote)
  const infoActions = visibleColumns
    .map(sessionInfoActionForColumn)
    .filter((action): action is SessionInfoAction => Boolean(action))
  const visibleTableColumnIds: SessionColumnWidthId[] = [...dataColumns, 'rowActions']
  const effectiveColumnWidths = Object.fromEntries(
    visibleTableColumnIds.map((columnId) => [columnId, effectiveColumnWidth(columnId, columnWidths[columnId], infoActions.length)]),
  ) as Record<SessionColumnWidthId, number>
  const tableMinWidth = visibleTableColumnIds.reduce((total, columnId) => total + effectiveColumnWidths[columnId], 0)
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
        return (
          <span className="session-name-value">
            {String(info.getValue() ?? '')}
            {savingSessionId === sessionId && <LoaderCircle className="session-rename-pending" size={14} />}
          </span>
        )
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
            <SessionInfoButtons
              session={row.original}
              onInspect={onInspect}
              actions={infoActions}
              noteSaving={notePasteSavingIds?.has(candidateId(row.original))}
            />
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

  useEffect(() => () => {
    if (pendingRenameTimeoutRef.current !== null) {
      window.clearTimeout(pendingRenameTimeoutRef.current)
    }
  }, [])

  function toggleFilterMenu(columnId: ColumnId) {
    setFilterSearchText('')
    setOpenFilterColumnId((current) => (current === columnId ? null : columnId))
  }

  function startColumnResize(
    event: ReactPointerEvent<HTMLButtonElement>,
    leftColumnId: SessionColumnWidthId,
    rightColumnId: SessionColumnWidthId,
  ) {
    event.preventDefault()
    event.stopPropagation()
    setOpenFilterColumnId(null)
    const startX = event.clientX
    const leftStartWidth = effectiveColumnWidths[leftColumnId]
    const rightStartWidth = effectiveColumnWidths[rightColumnId]
    const leftMinWidth = minColumnWidth(leftColumnId, infoActions.length)
    const rightMinWidth = minColumnWidth(rightColumnId, infoActions.length)
    const minDelta = leftMinWidth - leftStartWidth
    const maxDelta = rightStartWidth - rightMinWidth

    function handlePointerMove(moveEvent: PointerEvent) {
      const requestedDelta = moveEvent.clientX - startX
      const boundedDelta = Math.max(minDelta, Math.min(maxDelta, requestedDelta))
      onColumnWidthsChange({
        [leftColumnId]: Math.round(leftStartWidth + boundedDelta),
        [rightColumnId]: Math.round(rightStartWidth - boundedDelta),
      })
    }

    function handlePointerUp() {
      document.body.classList.remove('is-resizing-session-column')
      document.removeEventListener('pointermove', handlePointerMove)
      document.removeEventListener('pointerup', handlePointerUp)
      document.removeEventListener('pointercancel', handlePointerUp)
    }

    document.body.classList.add('is-resizing-session-column')
    document.addEventListener('pointermove', handlePointerMove)
    document.addEventListener('pointerup', handlePointerUp)
    document.addEventListener('pointercancel', handlePointerUp)
  }

  function startRename(session: SessionRecord) {
    clearPendingRename()
    if (!canRenameSessions || !onRenameSession || savingSessionId === candidateId(session)) {
      return
    }
    setContextMenu(null)
    setEditingSessionId(candidateId(session))
  }

  function cancelRename() {
    clearPendingRename()
    renameCommitInFlightRef.current = null
    setEditingSessionId(null)
    setSavingSessionId(null)
  }

  function scheduleRename(session: SessionRecord) {
    clearPendingRename()
    pendingRenameTimeoutRef.current = window.setTimeout(() => {
      pendingRenameTimeoutRef.current = null
      startRename(session)
    }, RENAME_CLICK_DELAY_MS)
  }

  function clearPendingRename() {
    if (pendingRenameTimeoutRef.current !== null) {
      window.clearTimeout(pendingRenameTimeoutRef.current)
      pendingRenameTimeoutRef.current = null
    }
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
    renameCommitInFlightRef.current = sessionId
    setEditingSessionId(null)
    setSavingSessionId(sessionId)
    void onRenameSession(session, trimmedName)
      .catch(() => {
        // The app-level handler restores the original row and reports the failure.
      })
      .finally(() => {
        if (renameCommitInFlightRef.current === sessionId) {
          renameCommitInFlightRef.current = null
          setSavingSessionId(null)
        }
      })
  }

  return (
    <>
      <div className="table-shell">
        <table
          className="session-table resizable-session-table"
          aria-label="Candidate sessions"
          style={{ minWidth: '100%', width: tableMinWidth }}
        >
          <colgroup>
            {visibleTableColumnIds.map((columnId) => (
              <col key={columnId} style={{ width: effectiveColumnWidths[columnId] }} />
            ))}
          </colgroup>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header, headerIndex) => {
                  const columnId = header.column.id
                  const isSortableSessionColumn = isColumnId(columnId)
                  const isInfoActionHeader = columnId === 'rowActions'
                  const currentWidthId: SessionColumnWidthId = isSortableSessionColumn ? columnId : 'rowActions'
                  const nextWidthId = visibleTableColumnIds[headerIndex + 1]
                  const selectedFilterValues = isSortableSessionColumn
                    ? tableColumnFilters.find((filter) => filter.columnId === columnId)?.values ?? []
                    : []
                  const headerClasses = [
                    isInfoActionHeader ? 'info-action-heading' : '',
                    'resizable-column-header',
                    openFilterColumnId === columnId ? 'filter-open' : '',
                  ].filter(Boolean).join(' ')
                  return (
                    <th className={headerClasses} key={header.id}>
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
                            onPointerDown={(event) => {
                              event.stopPropagation()
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
                      {nextWidthId && (
                        <button
                          aria-label={`Resize boundary after ${isSortableSessionColumn ? columnLabels[columnId] : 'actions'}`}
                          className="column-resize-handle"
                          onClick={(event) => event.stopPropagation()}
                          onPointerDown={(event) => startColumnResize(event, currentWidthId, nextWidthId)}
                          type="button"
                        />
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
                  onDoubleClick={(event) => {
                    clearPendingRename()
                    handleRowDoubleClick(event, session, onAnalyzeSession)
                  }}
                  onKeyDown={(event) => handleRowKeyDown(event, session, onSelect, startRename)}
                  tabIndex={0}
                >
                  {row.getVisibleCells().map((cell) => {
                    const isInfoCell = cell.column.id === 'rowActions'
                    const isNameCell = cell.column.id === 'name'
                    return (
                      <td
                        className={[
                          isInfoCell ? 'icon-cluster info-action-cell session-info-action-cell' : '',
                          isNameCell ? 'session-name-cell' : '',
                        ].filter(Boolean).join(' ')}
                        key={cell.id}
                        onClick={(event) => {
                          if (isInfoCell) {
                            event.stopPropagation()
                            return
                          }
                          if (isNameCell && isSelected && !hasSelectionModifier(event) && canRenameSessions) {
                            scheduleRename(session)
                            return
                          }
                          clearPendingRename()
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

function hasSelectionModifier(event: MouseEvent<HTMLElement>) {
  return event.shiftKey || event.ctrlKey || event.metaKey
}

function handleRowDoubleClick(
  event: MouseEvent<HTMLTableRowElement>,
  session: SessionRecord,
  onAnalyzeSession?: (session: SessionRecord) => void,
) {
  if (!onAnalyzeSession || isInteractiveDoubleClickTarget(event.target)) {
    return
  }
  event.preventDefault()
  onAnalyzeSession(session)
}

function isInteractiveDoubleClickTarget(target: EventTarget) {
  return target instanceof Element && Boolean(
    target.closest(
      'button, input, select, textarea, a, [role="button"], .column-filter-popover, .session-info-action-cell',
    ),
  )
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
