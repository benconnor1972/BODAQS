import type { ReactNode } from 'react'

export function UnsavedChangesDialog({
  actionLabel,
  canSave,
  onSave,
  onDiscard,
  onCancel,
}: {
  actionLabel: string
  canSave: boolean
  onSave: () => void
  onDiscard: () => void
  onCancel: () => void
}) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onCancel}>
      <section
        className="modal unsaved-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="unsaved-dialog-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h2 id="unsaved-dialog-title">Unsaved Study Set changes</h2>
        </div>
        <div className="modal-content unsaved-dialog-content">
          <p>
            The current Study Set has unsaved changes. Save them before you {actionLabel}, discard
            them, or cancel and keep editing.
          </p>
          {!canSave && (
            <p className="modal-note">
              Save is unavailable until the Study Set has a name and at least one session.
            </p>
          )}
          <div className="dialog-actions">
            <DialogButton className="primary-action" disabled={!canSave} onClick={onSave}>
              Save
            </DialogButton>
            <DialogButton className="danger-action" onClick={onDiscard}>
              Discard
            </DialogButton>
            <DialogButton className="secondary-action" onClick={onCancel}>
              Cancel
            </DialogButton>
          </div>
        </div>
      </section>
    </div>
  )
}

function DialogButton({
  children,
  className,
  disabled = false,
  onClick,
}: {
  children: ReactNode
  className: string
  disabled?: boolean
  onClick: () => void
}) {
  return (
    <button className={className} disabled={disabled} onClick={onClick} type="button">
      {children}
    </button>
  )
}
