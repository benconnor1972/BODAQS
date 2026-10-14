import { X } from 'lucide-react'
import { groupingColors } from '../domain/studySets'

export function TagTiles({ tags, onRemove, disabled = false }: {
  tags: string[]
  onRemove?: (tag: string) => void
  disabled?: boolean
}) {
  return <div className="session-tag-list">{tags.map((tag) => (
    <span className="group-chip session-tag-tile" style={{ borderColor: groupingColors[0] }} key={tag}>
      <span>{tag}</span>
      {onRemove && <button type="button" disabled={disabled} aria-label={`Remove tag ${tag}`} onClick={() => onRemove(tag)}><X size={12} /></button>}
    </span>
  ))}</div>
}
