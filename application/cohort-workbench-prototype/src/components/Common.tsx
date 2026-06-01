import type { ReactNode } from 'react'

export function PanelTitle({
  icon,
  title,
  action,
}: {
  icon: ReactNode
  title: string
  action: ReactNode
}) {
  return (
    <div className="panel-title">
      <div>
        {icon}
        <span>{title}</span>
      </div>
      {action}
    </div>
  )
}

export function IconButton({
  label,
  onClick,
  icon,
  disabled = false,
}: {
  label: string
  onClick?: () => void
  icon: ReactNode
  disabled?: boolean
}) {
  return (
    <button
      className="icon-button"
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      disabled={disabled}
    >
      {icon}
    </button>
  )
}

export function SummaryTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="summary-tile">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}
