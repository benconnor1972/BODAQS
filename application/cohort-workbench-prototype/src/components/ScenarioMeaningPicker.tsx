import { useId } from 'react'
import type { LibrarySignalCatalog } from '../data/LibraryDataSource'
import { meaningMatches } from '../domain/scenarioSignalCatalog'
import { InfoTip } from './Common'

const fields = [
  ['domain', 'Domain'], ['quantity', 'Quantity'], ['end', 'Front / rear'],
  ['component', 'Component'], ['unit', 'Unit'],
]
const extraFields = [
  ['processing_role', 'Processing role'], ['kind', 'Signal kind'], ['sensor', 'Sensor'],
  ['coordinate_frame', 'Coordinate frame'], ['analysis_variant', 'Analysis variant'],
  ['motion_source_id', 'Motion source'], ['origin', 'Origin'],
]

export function ScenarioMeaningPicker({ streamName, selector, catalog, onChange }: {
  streamName: string
  selector: Record<string, string>
  catalog?: LibrarySignalCatalog
  onChange: (reference: { streamName: string; selector: Record<string, string> }) => void
}) {
  const id = useId()
  const entries = (catalog?.signals ?? []).filter((entry) => entry.streamName === streamName)
  const streams = [...new Set(['primary', 'spatial_context', 'gps_logger', 'gps_fit', ...(catalog?.signals.map((entry) => entry.streamName) ?? []), streamName])]
  const knownKeys = [...fields, ...extraFields].map(([key]) => key)
  const customFields = Object.keys(selector).filter((key) => !knownKeys.includes(key)).map((key) => [key, key])
  const matches = entries.filter((entry) => meaningMatches(entry, selector))

  function field([key, label]: string[]) {
    const options = [...new Set(entries.flatMap((entry) => {
      const variants = entry.metadataVariants?.length ? entry.metadataVariants.map((variant) => variant.metadata) : [entry.metadata ?? {}]
      return variants.map((metadata) => key === 'unit' ? entry.unit : metadata[key])
    }).filter((value): value is string => typeof value === 'string' && Boolean(value.trim())))].sort()
    return <label key={key}>{label}
      <input list={`${id}-${key}`} value={selector[key] ?? ''} placeholder="Any" onChange={(event) => {
        const next = { ...selector }
        if (event.target.value.trim()) next[key] = event.target.value
        else delete next[key]
        onChange({ streamName, selector: next })
      }} />
      <datalist id={`${id}-${key}`}>{options.map((option) => <option key={option} value={option} />)}</datalist>
    </label>
  }

  return <div className="scenario-meaning-picker">
    <label><span className="inline-heading">Stream <InfoTip label="About choosing by meaning" text="Leave an attribute blank to allow any value. Column names may differ between sessions; the meaning is resolved when the scenario is evaluated. Catalog matches do not establish a unique match in each session." /></span>
      <select aria-label="Stream" value={streamName} onChange={(event) => onChange({ streamName: event.target.value, selector })}>
        {streams.map((stream) => <option key={stream} value={stream}>{stream}</option>)}
      </select>
    </label>
    {fields.map(field)}
    <details className="scenario-meaning-details" open={[...extraFields, ...customFields].some(([key]) => key in selector) || undefined}>
      <summary>More meaning attributes</summary>
      <div className="scenario-meaning-fields">{[...extraFields, ...customFields].map(field)}</div>
    </details>
    {catalog && Object.keys(selector).length > 0 && <p className="condition-help">
      {matches.length ? `Matching catalog entries: ${matches.slice(0, 8).map((entry) => `${entry.column}${entry.unit ? ` (${entry.unit})` : ''}`).join(', ')}${matches.length > 8 ? ', …' : ''}.` : 'No matching metadata in this library. The selector is retained for use with other sessions.'}
    </p>}
  </div>
}
