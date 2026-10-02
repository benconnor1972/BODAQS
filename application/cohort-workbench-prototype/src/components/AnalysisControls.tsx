import { ChevronLeft, ChevronRight, FileClock, Users } from 'lucide-react'
import type { ReactNode } from 'react'
import { InfoTip } from './Common'

export type AnalysisEntityOption = {
  id: string
  kind: 'session' | 'grouping'
  label: string
  color?: string
  memberCount?: number
}

export type AnalysisScenarioOption = {
  id: string
  label: string
  disabled?: boolean
}

export function AnalysisControlDrawer({
  collapsed,
  summary,
  infoText,
  onToggle,
  children,
}: {
  collapsed: boolean
  summary: string
  infoText: string
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <aside className={`viz-control-drawer${collapsed ? ' collapsed' : ''}`} aria-label="Select and filter">
      {collapsed ? (
        <button className="viz-control-drawer-rail" type="button" onClick={onToggle}>
          <ChevronRight size={15} />
          <span>Select and filter</span>
        </button>
      ) : (
        <section className="viz-control-panel">
          <button className="viz-control-panel-header" type="button" onClick={onToggle}>
            <span>
              <strong>Select and Filter <InfoTip text={infoText} /></strong>
              <small>{summary}</small>
            </span>
            <ChevronLeft size={16} />
          </button>
          <div className="viz-control-panel-body">{children}</div>
        </section>
      )}
    </aside>
  )
}

export function AnalysisEntityPicker({
  entities,
  selectedIds,
  onToggle,
}: {
  entities: AnalysisEntityOption[]
  selectedIds: string[]
  onToggle: (id: string) => void
}) {
  return (
    <div className="viz-filter-group">
      <strong>Sessions and groups</strong>
      <div className="viz-entity-chips">
        {entities.map((entity) => {
          const selected = selectedIds.includes(entity.id)
          return (
            <button
              aria-pressed={selected}
              className={`viz-entity-chip${selected ? ' selected' : ''}${entity.kind === 'grouping' ? ' grouping' : ''}`}
              key={entity.id}
              type="button"
              onClick={() => onToggle(entity.id)}
              style={entity.color ? { borderColor: entity.color } : undefined}
            >
              {entity.color && <span className="color-dot" style={{ backgroundColor: entity.color }} />}
              <span className="viz-entity-type-glyph" title={entity.kind === 'grouping' ? `${entity.memberCount ?? 0} pooled sessions` : 'Session'}>
                {entity.kind === 'grouping' ? <Users size={14} /> : <FileClock size={14} />}
              </span>
              <span className="viz-entity-chip-label">{entity.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function AnalysisEndPicker({
  ends,
  selectedIds,
  onToggle,
}: {
  ends: Array<{ id: string; label: string; color: string }>
  selectedIds: string[]
  onToggle: (id: string) => void
}) {
  return (
    <section className="viz-mode-filter-control">
      <strong>Ends</strong>
      <div className="viz-entity-chips">
        {ends.map((end) => (
          <button
            aria-pressed={selectedIds.includes(end.id)}
            className={`viz-entity-chip end-chip${selectedIds.includes(end.id) ? ' selected' : ''}`}
            key={end.id}
            onClick={() => onToggle(end.id)}
            type="button"
          >
            <span className="color-dot" style={{ backgroundColor: end.color }} />
            <span>{end.label}</span>
          </button>
        ))}
      </div>
    </section>
  )
}

export function AnalysisScenarioPicker({
  options,
  selectedIds,
  onToggle,
  ariaLabel = 'Scenario populations',
  optionAriaLabelPrefix = 'Include',
}: {
  options: AnalysisScenarioOption[]
  selectedIds: string[]
  onToggle: (id: string, checked: boolean) => void
  ariaLabel?: string
  optionAriaLabelPrefix?: string
}) {
  return (
    <div className="viz-scenario-picker" aria-label={ariaLabel}>
      {options.map((option) => (
        <label className="viz-scenario-option" key={option.id}>
          <input
            aria-label={`${optionAriaLabelPrefix} ${option.label}`}
            checked={selectedIds.includes(option.id)}
            disabled={option.disabled}
            onChange={(event) => onToggle(option.id, event.currentTarget.checked)}
            type="checkbox"
          />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  )
}

export function AnalysisControlCard({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="viz-mode-filter-control">
      <strong>{title}</strong>
      {hint && <small>{hint}</small>}
      {children}
    </section>
  )
}
