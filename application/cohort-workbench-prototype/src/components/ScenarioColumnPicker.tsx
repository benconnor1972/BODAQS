import { useState } from 'react'
import type { LibrarySignalCatalog } from '../data/LibraryDataSource'

const defaultStreams = ['spatial_context', 'primary', 'gps_logger', 'gps_fit']

export function ScenarioColumnPicker({ streamName, column, catalog, onChange }: {
  streamName: string
  column: string
  catalog?: LibrarySignalCatalog
  onChange: (reference: { streamName: string; column: string }) => void
}) {
  const [search, setSearch] = useState('')
  const [manual, setManual] = useState(false)
  const streams = [...new Set([...defaultStreams, ...(catalog?.signals.map((signal) => signal.streamName) ?? []), streamName])].filter(Boolean)
  const grouped = new Map<string, NonNullable<LibrarySignalCatalog['signals']>>()
  for (const signal of catalog?.signals ?? []) {
    if (signal.streamName !== streamName) continue
    grouped.set(signal.column, [...(grouped.get(signal.column) ?? []), signal])
  }
  const choices = [...grouped.entries()].sort((a, b) => a[1][0].displayName.localeCompare(b[1][0].displayName))
  const needle = search.trim().toLowerCase()
  const visible = choices.filter(([name, entries]) => name === column ||
    entries.some((entry) => [entry.column, entry.displayName, ...entry.displayNames, entry.unit].join(' ').toLowerCase().includes(needle)))
  const matching = grouped.get(column) ?? []
  const units = [...new Set(matching.map((entry) => entry.unit || 'unknown'))]

  return <div className="scenario-column-picker">
    <label>Stream
      <select value={streamName} onChange={(event) => {
        setSearch('')
        onChange({ streamName: event.target.value, column: '' })
      }}>
        {streams.map((stream) => <option key={stream} value={stream}>{streamLabel(stream)}</option>)}
      </select>
    </label>
    {!manual && <label>Find a column
      <input type="search" placeholder="Search names, columns or units" value={search} onChange={(event) => setSearch(event.target.value)} />
    </label>}
    <label>Column
      {manual ? <input value={column} onChange={(event) => onChange({ streamName, column: event.target.value })} /> :
        <select value={column} onChange={(event) => onChange({ streamName, column: event.target.value })}>
          <option value="">Select a column</option>
          {column && !grouped.has(column) && <option value={column}>{column} — not in this catalog</option>}
          {visible.map(([name, entries]) => <option key={name} value={name}>
            {entries[0].displayName} [{name}] — {entries.map((entry) => `${entry.unit || 'unknown units'} · ${entry.sessionCount}/${catalog?.sessionCount ?? 0} sessions (${Math.round(entry.sessionFraction * 100)}%)`).join('; ')}
          </option>)}
        </select>}
    </label>
    <button className="ghost-action compact-filter-action" type="button" onClick={() => setManual(!manual)}>
      {manual ? 'Choose from catalog' : 'Enter column name'}
    </button>
    {!manual && visible.length === 0 && <p className="condition-help">No matching columns in this stream.</p>}
    {column && matching.length === 0 && <p className="condition-help">This reference is retained. It is not listed in the selected library catalog.</p>}
    {units.length > 1 && <p className="condition-help">Different units occur for this column ({units.join(', ')}). Thresholds use each session’s stored units.</p>}
  </div>
}

function streamLabel(stream: string) {
  return ({ primary: 'Primary', spatial_context: 'Spatial context', gps_logger: 'Logger GPS', gps_fit: 'FIT GPS' } as Record<string, string>)[stream] ?? stream
}
