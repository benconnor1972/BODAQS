import { X } from 'lucide-react'
import { libraryName } from '../domain/sessionCatalog'
import { noteSummary } from '../domain/studySets'
import type { LibraryRecord, ModalState } from '../domain/types'
import { IconButton } from './Common'
import { NoteBadge, QcBadge } from './StatusBadges'

export function Modal({
  state,
  libraries,
  onClose,
}: {
  state: ModalState
  libraries: LibraryRecord[]
  onClose: () => void
}) {
  if (!state) {
    return null
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>{modalTitle(state)}</h2>
          <IconButton label="Close" onClick={onClose} icon={<X size={18} />} />
        </div>
        <div className="modal-content">{modalContent(state, libraries)}</div>
      </section>
    </div>
  )
}

function modalTitle(state: NonNullable<ModalState>) {
  if (state.kind === 'session') {
    return `${state.session.name}: ${state.tab}`
  }
  if (state.kind === 'track') {
    return state.track.name
  }
  return state.mode === 'analyze' ? `Analyze ${state.studySet.displayName || 'Study Set'}` : state.studySet.displayName
}

function modalContent(state: NonNullable<ModalState>, libraries: LibraryRecord[]) {
  if (state.kind === 'session') {
    if (state.tab === 'note') {
      return (
        <dl className="detail-list">
          <dt>Note status</dt>
          <dd>
            <NoteBadge status={state.session.noteStatus} />
          </dd>
          <dt>Bike</dt>
          <dd>{state.session.bike}</dd>
          <dt>Rider</dt>
          <dd>{state.session.rider}</dd>
          <dt>Summary</dt>
          <dd>{noteSummary(state.session.noteStatus)}</dd>
        </dl>
      )
    }
    if (state.tab === 'qc') {
      return (
        <div>
          <QcBadge session={state.session} />
          {state.session.qcAlerts.length === 0 ? (
            <p className="modal-note">No QC warnings recorded in this fixture.</p>
          ) : (
            <ul className="alert-list">
              {state.session.qcAlerts.map((alert) => (
                <li key={alert}>{alert}</li>
              ))}
            </ul>
          )}
        </div>
      )
    }
    return (
      <dl className="detail-list">
        <dt>Library</dt>
        <dd>{libraryName(libraries, state.session.libraryId)}</dd>
        <dt>Run ID</dt>
        <dd>{state.session.runId}</dd>
        <dt>Session ID</dt>
        <dd>{state.session.sessionId}</dd>
        <dt>Preprocessing profile</dt>
        <dd>{state.session.preprocessingProfile}</dd>
        <dt>Firmware</dt>
        <dd>{state.session.firmware}</dd>
        <dt>Event schema</dt>
        <dd>{state.session.eventSchema}</dd>
        <dt>Source archive</dt>
        <dd>{state.session.sourceArchive}</dd>
        <dt>Signals</dt>
        <dd>{state.session.signals.join(', ')}</dd>
      </dl>
    )
  }

  if (state.kind === 'track') {
    return (
      <dl className="detail-list">
        <dt>Track ID</dt>
        <dd>{state.track.id}</dd>
        <dt>Library</dt>
        <dd>{libraryName(libraries, state.track.libraryId)}</dd>
        <dt>Points</dt>
        <dd>{state.track.pointCount}</dd>
        <dt>Distance</dt>
        <dd>{state.track.distanceKm.toFixed(1)} km</dd>
      </dl>
    )
  }

  return (
    <div>
      <dl className="detail-list">
        <dt>Study Set ID</dt>
        <dd>{state.studySet.id ?? 'unsaved temporary Study Set'}</dd>
        <dt>Revision</dt>
        <dd>{state.studySet.saved ? state.studySet.revision : 'unsaved'}</dd>
        <dt>Sessions</dt>
        <dd>{state.studySet.sessions.length}</dd>
        <dt>Groupings</dt>
        <dd>{state.studySet.groupings.length}</dd>
        <dt>Tracks</dt>
        <dd>{state.studySet.trackIds.length}</dd>
        <dt>Provenance</dt>
        <dd>{state.studySet.provenance || 'Created interactively'}</dd>
      </dl>
      {state.mode === 'analyze' && (
        <p className="modal-note">Analysis navigation is reserved for the next prototype pass.</p>
      )}
    </div>
  )
}
