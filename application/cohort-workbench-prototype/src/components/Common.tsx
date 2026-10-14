import { Info } from 'lucide-react'
import { useId, type ReactNode } from 'react'

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
  tone = 'neutral',
}: {
  label: string
  onClick?: () => void
  icon: ReactNode
  disabled?: boolean
  tone?: 'neutral' | 'good' | 'warning' | 'alert'
}) {
  return (
    <button
      className={`icon-button icon-${tone}`}
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

export function InfoTip({ label = 'More information', text }: { label?: string; text: string }) {
  const id = useId()
  return (
    <span className="info-tip">
      <span className="info-tip-button" role="img" tabIndex={0} aria-label={label} aria-describedby={id} title={text}
        onClick={(event) => { event.preventDefault(); event.stopPropagation() }}>
        <Info size={13} />
      </span>
      <span className="info-tip-bubble" role="tooltip" id={id}>
        {text}
      </span>
    </span>
  )
}
