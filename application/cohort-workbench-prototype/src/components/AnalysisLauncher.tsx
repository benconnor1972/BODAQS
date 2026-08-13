import { AlertTriangle, Ban, CheckCircle2, CircleX, HelpCircle, Loader2, Play, ShieldAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type {
  AnalysisAdequacyResult,
  AnalysisAdequacyStatus,
  AnalysisRequirementRecord,
  AnalysisRequirementTier,
  AnalysisViewRecord,
  StudySet,
  TrackRecord,
} from '../domain/types'
import { IconButton } from './Common'

type AnalysisLauncherItem = {
  view: AnalysisViewRecord
  adequacy: AnalysisAdequacyResult | null
  error: string
}

const REQUIREMENT_TIERS: AnalysisRequirementTier[] = ['required', 'recommended', 'optional']

export function AnalysisLauncher({
  studySet,
  tracks,
  dataSource,
  onClose,
  onOpenAnalysis,
}: {
  studySet: StudySet
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
  onClose: () => void
  onOpenAnalysis: (viewId: string, studySet: StudySet) => void
}) {
  const [items, setItems] = useState<AnalysisLauncherItem[]>([])
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setNotice('')
      try {
        let views = await listViews(dataSource)
        if (views.length === 0) {
          views = [fallbackSimpleSuspensionView()]
          setNotice('No analysis views were returned by the library API, so the built-in Simple Suspension entry is shown.')
        }

        const resolvedItems = await Promise.all(
          views.map(async (view) => {
            if (!dataSource.evaluateAnalysisAdequacy) {
              return {
                view,
                adequacy: null,
                error: 'This data source cannot evaluate analysis adequacy.',
              }
            }
            try {
              return {
                view,
                adequacy: await dataSource.evaluateAnalysisAdequacy(view.id, studySet),
                error: '',
              }
            } catch (error) {
              return {
                view,
                adequacy: null,
                error: error instanceof Error ? error.message : 'Could not evaluate analysis adequacy.',
              }
            }
          }),
        )

        if (!cancelled) {
          setItems(resolvedItems)
        }
      } catch (error) {
        if (!cancelled) {
          setNotice(
            error instanceof Error
              ? `Could not load analysis views from the API: ${error.message}`
              : 'Could not load analysis views from the API.',
          )
          setItems([
            {
              view: fallbackSimpleSuspensionView(),
              adequacy: null,
              error: 'Adequacy was not evaluated. You can still open the prototype analysis view.',
            },
          ])
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [dataSource, studySet])

  return (
    <div className="analysis-launcher">
      <section className="analysis-launcher-intro">
        <div className="analysis-launcher-title-row">
          <h3>{studySet.displayName || 'Untitled Study Set'}</h3>
        </div>
        <ScopeList studySet={studySet} tracks={tracks} />
        <dl className="analysis-scope-summary">
          <dt>Sessions</dt>
          <dd>{studySet.sessions.length}</dd>
          <dt>Groups</dt>
          <dd>{studySet.groupings.length}</dd>
          <dt>Tracks</dt>
          <dd>{studySet.trackIds.length}</dd>
        </dl>
        <div className="analysis-launcher-close">
          <IconButton label="Close" onClick={onClose} icon={<X size={18} />} />
        </div>
      </section>

      {notice && <p className="modal-status warning">{notice}</p>}

      {loading ? (
        <div className="analysis-loading" aria-live="polite">
          <Loader2 size={18} />
          Checking available analysis views...
        </div>
      ) : (
        <div className="analysis-view-list">
          {items.map((item) => (
            <AnalysisViewCard
              key={item.view.id}
              item={item}
              onOpen={() => onOpenAnalysis(item.view.id, studySet)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function AnalysisViewCard({ item, onOpen }: { item: AnalysisLauncherItem; onOpen: () => void }) {
  const status = item.adequacy?.status ?? 'unknown'
  const statusMeta = analysisStatusMeta(status)
  const isSupported = item.view.id === 'simple-suspension' || item.view.id === 'track-analysis-lap-timing'
  const isBlocked = item.adequacy?.status === 'blocked'
  const canOpen = isSupported && !isBlocked

  return (
    <article className={`analysis-view-card analysis-status-${status}`}>
      <div className="analysis-view-card-header">
        <div>
          <p className="analysis-view-category">{item.view.category || 'Analysis'}</p>
          <h3>{item.view.displayName}</h3>
        </div>
        <div className="analysis-view-card-header-actions">
          <span className={`analysis-status-badge analysis-status-badge-${status}`}>
            {statusMeta.icon}
            {statusMeta.label}
          </span>
          <button className="primary-action compact-row-action" disabled={!canOpen} onClick={onOpen}>
            <Play size={16} />
            Open in tab
          </button>
        </div>
      </div>

      <p className="analysis-view-description">{item.view.description}</p>

      <section className="analysis-adequacy-section">
        {item.adequacy ? (
          <AdequacyMatrix adequacy={item.adequacy} view={item.view} />
        ) : (
          <p className="analysis-adequacy-summary">{item.error || 'Adequacy has not been evaluated for this view.'}</p>
        )}
        {item.adequacy?.messages.length ? (
          <ul className="analysis-message-list">
            {item.adequacy.messages.slice(0, 4).map((message, index) => (
              <li key={`${message.code}-${index}`} className={`analysis-message-${message.level}`}>
                {message.message}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {(!isSupported || isBlocked) && (
        <div className="analysis-view-actions">
          {!isSupported && <span className="subtle">This view is registered but not implemented in the prototype yet.</span>}
          {isBlocked && <span className="subtle">This scope is missing required data for this analysis.</span>}
        </div>
      )}
    </article>
  )
}

function AdequacyMatrix({ adequacy, view }: { adequacy: AnalysisAdequacyResult; view: AnalysisViewRecord }) {
  const criteriaBySession = adequacy.sessionResults.map((session) =>
    new Map(session.criteria.map((criterion) => [criterion.requirementId, criterion])),
  )
  const scopeCriteria = new Map(adequacy.scopeCriteria.map((criterion) => [criterion.requirementId, criterion]))
  const tiers = REQUIREMENT_TIERS.map((tier) => ({
    tier,
    sessionRequirements: (view.requirements[tier] ?? []).filter((requirement) =>
      criteriaBySession.some((criteria) => criteria.has(requirement.requirementId)),
    ),
    scopeRequirements: (view.requirements[tier] ?? []).filter((requirement) => scopeCriteria.has(requirement.requirementId)),
  })).filter((entry) => entry.sessionRequirements.length || entry.scopeRequirements.length)

  return (
    <div className="analysis-adequacy-matrix" aria-label="Adequacy by criterion and session">
      {tiers.map(({ tier, sessionRequirements, scopeRequirements }) => (
        <div className="analysis-adequacy-tier" key={tier}>
          <span className="analysis-adequacy-tier-label">{tier}</span>
          <div className="analysis-adequacy-criterion-list">
            {sessionRequirements.map((requirement) => (
              <AdequacyCriterionRow
                key={requirement.requirementId}
                requirement={requirement}
                sessionCriteria={criteriaBySession.map((criteria) => criteria.get(requirement.requirementId) ?? null)}
              />
            ))}
            {scopeRequirements.map((requirement) => (
              <AdequacyScopeCriterionRow
                criterion={scopeCriteria.get(requirement.requirementId)!}
                key={requirement.requirementId}
                requirement={requirement}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function ScopeList({ studySet, tracks }: { studySet: StudySet; tracks: TrackRecord[] }) {
  const tracksById = new Map(tracks.map((track) => [track.id, track]))

  if (studySet.sessions.length === 0 && studySet.trackIds.length === 0) {
    return <p className="analysis-scope-list empty">No sessions or tracks are in scope.</p>
  }

  return (
    <div className="analysis-scope-list">
      {studySet.sessions.length > 0 && (
        <ul aria-label="Sessions in scope">
          {studySet.sessions.map((session) => (
            <li key={`session-${session.libraryId}-${session.sessionKey}`}>{session.label}</li>
          ))}
        </ul>
      )}
      {studySet.trackIds.length > 0 && (
        <ul aria-label="Tracks in scope">
          {studySet.trackIds.map((trackId) => (
            <li key={`track-${trackId}`}>{tracksById.get(trackId)?.name || trackId}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function AdequacyCriterionRow({
  requirement,
  sessionCriteria,
}: {
  requirement: AnalysisRequirementRecord
  sessionCriteria: Array<AnalysisAdequacyResult['sessionResults'][number]['criteria'][number] | null>
}) {
  return (
    <div className="analysis-adequacy-criterion-row">
      <span title={requirement.description}>{requirement.label}</span>
      <div className="analysis-adequacy-marks">
        {sessionCriteria.map((criterion, index) => (
          <AdequacyMark criterion={criterion} key={index} requirement={requirement} />
        ))}
      </div>
    </div>
  )
}

function AdequacyScopeCriterionRow({
  requirement,
  criterion,
}: {
  requirement: AnalysisRequirementRecord
  criterion: AnalysisAdequacyResult['scopeCriteria'][number]
}) {
  return (
    <div className="analysis-adequacy-criterion-row scope">
      <span title={requirement.description}>{requirement.label}</span>
      <div className="analysis-adequacy-marks">
        <AdequacyMark criterion={criterion} requirement={requirement} />
      </div>
    </div>
  )
}

function AdequacyMark({
  criterion,
  requirement,
}: {
  criterion: AnalysisAdequacyResult['scopeCriteria'][number] | null
  requirement: AnalysisRequirementRecord
}) {
  const met = criterion?.met === true
  const detail = criterion?.detail || 'This criterion was not evaluated for the session.'
  return (
    <span
      aria-label={`${requirement.label}: ${met ? 'met' : 'not met'}. ${detail}`}
      className={`analysis-adequacy-mark ${met ? 'met' : `unmet unmet-${requirement.tier}`}`}
      role="img"
      title={`${requirement.label}: ${met ? 'met' : 'not met'}. ${detail}`}
    >
      {met ? <CheckCircle2 size={16} /> : <CircleX size={16} />}
    </span>
  )
}

function analysisStatusMeta(status: AnalysisAdequacyStatus) {
  if (status === 'ready') {
    return { label: 'Ready', icon: <CheckCircle2 size={15} /> }
  }
  if (status === 'partial') {
    return { label: 'Partial', icon: <ShieldAlert size={15} /> }
  }
  if (status === 'warning') {
    return { label: 'Warning', icon: <AlertTriangle size={15} /> }
  }
  if (status === 'blocked') {
    return { label: 'Blocked', icon: <Ban size={15} /> }
  }
  return { label: 'Unknown', icon: <HelpCircle size={15} /> }
}

async function listViews(dataSource: LibraryDataSource) {
  if (!dataSource.listAnalysisViews) {
    return [fallbackSimpleSuspensionView()]
  }
  return dataSource.listAnalysisViews()
}

function fallbackSimpleSuspensionView(): AnalysisViewRecord {
  return {
    id: 'simple-suspension',
    displayName: 'Simple Suspension Analysis',
    category: 'Suspension',
    description: 'Compare wheel displacement, wheel velocity, stroke length, event counts, and simple compression/rebound metrics.',
    route: 'simple-suspension',
    adequacyPolicy: 'fallback',
    requirements: {
      required: [
        {
          requirementId: 'wheel_motion_data',
          label: 'Wheel motion data',
          tier: 'required',
          description: 'At least one suspension end needs usable wheel displacement data and velocity evidence.',
        },
      ],
      recommended: [
        {
          requirementId: 'event_metrics',
          label: 'Event metrics',
          tier: 'recommended',
          description: 'Compression and rebound metrics unlock the distribution and scatter panels.',
        },
      ],
      optional: [
        {
          requirementId: 'gps_and_tracks',
          label: 'GPS and tracks',
          tier: 'optional',
          description: 'GPS and tracks unlock sector-based comparisons.',
        },
      ],
    },
  }
}
