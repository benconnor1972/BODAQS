import { X } from 'lucide-react'
import { formatPercent, gpsSourceLabel } from '../domain/geospatial'
import { libraryName } from '../domain/sessionCatalog'
import { noteSummary, sessionByRef, sessionRefId } from '../domain/studySets'
import type { LibraryRecord, ModalState, SessionRecord, StudySet, TrackRecord } from '../domain/types'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { IconButton } from './Common'
import { GpsRoutePreview } from './GpsRoutePreview'
import { GpsBadge, NoteBadge, QcBadge } from './StatusBadges'

export function Modal({
  state,
  libraries,
  sessions,
  tracks,
  dataSource,
  onClose,
}: {
  state: ModalState
  libraries: LibraryRecord[]
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
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
        <div className="modal-content">{modalContent(state, libraries, sessions, tracks, dataSource)}</div>
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
  if (state.mode === 'analyze') {
    return `Analyze ${state.studySet.displayName || 'Study Set'}`
  }
  return `View ${state.studySet.displayName || 'Study Set'}`
}

function modalContent(
  state: NonNullable<ModalState>,
  libraries: LibraryRecord[],
  sessions: SessionRecord[],
  tracks: TrackRecord[],
  dataSource: LibraryDataSource,
) {
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
    if (state.tab === 'gps') {
      const summary = state.session.gpsSummary
      const primarySource = summary.sources[0]
      return (
        <div>
          <dl className="detail-list">
            <dt>GPS status</dt>
            <dd>
              <GpsBadge summary={summary} />
            </dd>
            <dt>Preferred source</dt>
            <dd>{gpsSourceLabel(summary.preferredSource)}</dd>
            <dt>Coverage</dt>
            <dd>{formatPercent(summary.timeCoverageRatio)}</dd>
            <dt>Position points</dt>
            <dd>{summary.positionPointCount}</dd>
            <dt>Timebase</dt>
            <dd>{primarySource?.timebase ?? 'unknown'}</dd>
            <dt>Nominal rate</dt>
            <dd>
              {primarySource?.nominalSampleRateHz
                ? `${primarySource.nominalSampleRateHz.toFixed(2)} Hz`
                : 'unknown'}
            </dd>
            <dt>Median gap</dt>
            <dd>{primarySource?.medianGapS ? `${primarySource.medianGapS.toFixed(1)} s` : 'unknown'}</dd>
            <dt>Max gap</dt>
            <dd>{primarySource?.maxGapS ? `${primarySource.maxGapS.toFixed(1)} s` : 'unknown'}</dd>
          </dl>
          {summary.warnings.length > 0 && (
            <ul className="alert-list">
              {summary.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
          <section className="modal-section gps-modal-preview">
            <h3>GPS Path</h3>
            <GpsRoutePreview
              session={state.session}
              dataSource={dataSource}
              selectedTracks={[]}
              currentTracks={[]}
              compact
            />
          </section>
        </div>
      )
    }
    return (
      <dl className="detail-list">
        <dt>Library</dt>
        <dd>{libraryName(libraries, state.session.libraryId)}</dd>
        <dt>Run</dt>
        <dd>{state.session.runName}</dd>
        <dt>Started</dt>
        <dd>{state.session.startedAt}</dd>
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
      <div className="study-set-view">
        <section className="modal-section">
          <dl className="detail-list">
            <dt>Track ID</dt>
            <dd>{state.track.id}</dd>
            <dt>Revision</dt>
            <dd>{state.track.revision}</dd>
            <dt>Path points</dt>
            <dd>{state.track.pointCount}</dd>
            <dt>Trackpoints</dt>
            <dd>{state.track.trackpoints.length}</dd>
            <dt>Distance</dt>
            <dd>{state.track.distanceKm.toFixed(1)} km</dd>
            <dt>Policy</dt>
            <dd>{state.track.defaultPolicyId}</dd>
          </dl>
        </section>
        <section className="modal-section">
          <h3>Trackpoints</h3>
          <div className="modal-table-shell">
            <table className="modal-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Station</th>
                  <th>Cutline</th>
                </tr>
              </thead>
              <tbody>
                {state.track.trackpoints.map((trackpoint) => (
                  <tr key={trackpoint.id}>
                    <td>{trackpoint.name}</td>
                    <td>{trackpoint.stationM.toFixed(0)} m</td>
                    <td>{trackpoint.cutlineOverride ? 'override' : 'policy default'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    )
  }

  if (state.mode === 'view') {
    return (
      <StudySetView
        studySet={state.studySet}
        libraries={libraries}
        sessions={sessions}
        tracks={tracks}
      />
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

function StudySetView({
  studySet,
  libraries,
  sessions,
  tracks,
}: {
  studySet: StudySet
  libraries: LibraryRecord[]
  sessions: SessionRecord[]
  tracks: TrackRecord[]
}) {
  const studySetTracks = tracks.filter((track) => studySet.trackIds.includes(track.id))
  const libraryCount = new Set(studySet.sessions.map((sessionRef) => sessionRef.libraryId)).size

  return (
    <div className="study-set-view">
      <section className="modal-section">
        <h3>Summary</h3>
        <dl className="detail-list compact-detail-list">
          <dt>Study Set ID</dt>
          <dd>{studySet.id ?? 'unsaved temporary Study Set'}</dd>
          <dt>Status</dt>
          <dd>{studySet.saved ? `saved revision ${studySet.revision}` : 'unsaved'}</dd>
          <dt>Sessions</dt>
          <dd>{studySet.sessions.length}</dd>
          <dt>Groupings</dt>
          <dd>{studySet.groupings.length}</dd>
          <dt>Tracks</dt>
          <dd>{studySet.trackIds.length}</dd>
          <dt>Libraries</dt>
          <dd>{libraryCount}</dd>
          <dt>Provenance</dt>
          <dd>{studySet.provenance || 'Created interactively'}</dd>
        </dl>
      </section>

      <section className="modal-section">
        <h3>Sessions</h3>
        <div className="modal-table-shell">
          <table className="modal-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Library</th>
                <th>Started</th>
                <th>Run</th>
                <th>Session ID</th>
                <th>Note</th>
                <th>QC</th>
                <th>GPS</th>
                <th>Groupings</th>
              </tr>
            </thead>
            <tbody>
              {studySet.sessions.length === 0 && (
                <tr>
                  <td className="empty-cell" colSpan={9}>
                    No sessions in this Study Set.
                  </td>
                </tr>
              )}
              {studySet.sessions.map((sessionRef) => {
                const refId = sessionRefId(sessionRef)
                const session = sessionByRef(sessionRef, sessions)
                const groupingMatches = studySet.groupings.filter((grouping) =>
                  grouping.sessionRefs.includes(refId),
                )

                return (
                  <tr key={refId}>
                    <td>{sessionRef.label}</td>
                    <td>{libraryName(libraries, sessionRef.libraryId)}</td>
                    <td>{session?.startedAt ?? '-'}</td>
                    <td>{session?.runName ?? sessionRef.runId}</td>
                    <td>{sessionRef.sessionId}</td>
                    <td>{session ? <NoteBadge status={session.noteStatus} /> : '-'}</td>
                    <td>{session ? <QcBadge session={session} /> : '-'}</td>
                    <td>{session ? <GpsBadge summary={session.gpsSummary} /> : '-'}</td>
                    <td>
                      <div className="badge-row">
                        {groupingMatches.length === 0 && <span className="subtle">none</span>}
                        {groupingMatches.map((grouping) => (
                          <span className="mini-group" style={{ borderColor: grouping.color }} key={grouping.id}>
                            {grouping.name}
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="modal-section">
        <h3>Groupings</h3>
        <div className="modal-card-grid">
          {studySet.groupings.length === 0 && <p className="empty-note">No groupings in this Study Set.</p>}
          {studySet.groupings.map((grouping) => (
            <article className="modal-card" style={{ borderColor: grouping.color }} key={grouping.id}>
              <div className="modal-card-title">
                <span className="color-dot" style={{ backgroundColor: grouping.color }} />
                <strong>{grouping.name}</strong>
                <span>{grouping.sessionRefs.length} session(s)</span>
              </div>
              <p>
                {grouping.sessionRefs
                  .map((refId) => studySet.sessions.find((sessionRef) => sessionRefId(sessionRef) === refId)?.label)
                  .filter(Boolean)
                  .join(', ') || 'No matching sessions'}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="modal-section">
        <h3>Tracks</h3>
        <div className="modal-table-shell">
          <table className="modal-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Trackpoints</th>
                <th>Distance</th>
              </tr>
            </thead>
            <tbody>
              {studySetTracks.length === 0 && (
                <tr>
                  <td className="empty-cell" colSpan={3}>
                    No tracks attached.
                  </td>
                </tr>
              )}
              {studySetTracks.map((track) => (
                <tr key={track.id}>
                  <td>{track.name}</td>
                  <td>{track.trackpoints.length}</td>
                  <td>{track.distanceKm.toFixed(1)} km</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
