import { useState } from 'react'
import { emptyAnnotationFilter, type AnnotationFilterSelection } from '../domain/annotationFilters'

export function AnnotationFilters({ knownTags, value, onChange, onSave, canSave }: {
  knownTags: string[]
  value: AnnotationFilterSelection
  onChange: (selection: AnnotationFilterSelection) => void
  onSave: () => void
  canSave: boolean
}) {
  const [search, setSearch] = useState('')
  const active = value.tags.length > 0 || value.issues !== ''
  const options = [...new Set([...knownTags, ...value.tags])].sort().filter((tag) => tag.includes(search.trim().toLowerCase()))
  return <details className="session-annotation-filters">
    <summary>Tags and user issues{active ? ` (${value.tags.length} tags${value.issues ? ', issue filter' : ''})` : ''}</summary>
    <div className="session-annotation-filter-controls">
      <label>User issues<select value={value.issues} onChange={(event) => onChange({ ...value, issues: event.target.value as AnnotationFilterSelection['issues'] })}>
        <option value="">All sessions</option><option value="gps">GPS issue flagged</option><option value="qa">QA issue flagged</option><option value="any">Any issue flagged</option><option value="none">No user issues flagged</option>
      </select></label>
      <label>Tag matching<select value={value.tagMatch} onChange={(event) => onChange({ ...value, tagMatch: event.target.value as 'in' | 'all' })}><option value="in">Any selected tag</option><option value="all">All selected tags</option></select></label>
      <label>Find tags<input value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <div className="session-annotation-tag-options">{options.length ? options.map((tag) => <label key={tag}><input type="checkbox" checked={value.tags.includes(tag)} onChange={() => onChange({ ...value, tags: value.tags.includes(tag) ? value.tags.filter((item) => item !== tag) : [...value.tags, tag] })} />{tag}</label>) : <span>No matching tags</span>}</div>
      <button className="secondary-action compact" type="button" disabled={!active} onClick={() => onChange(emptyAnnotationFilter)}>Clear tags and issues</button>
      <button className="secondary-action compact" type="button" disabled={!active || !canSave} onClick={onSave}>Save as filter...</button>
    </div>
  </details>
}
