import { AlertTriangle, Ban, CheckCircle2, HelpCircle, Loader2, Play, ShieldAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type {
  AnalysisAdequacyResult,
  AnalysisAdequacyStatus,
  AnalysisRequirementRecord,
  AnalysisRequirementTier,
  AnalysisViewRecord,
  StudySet,
} from '../domain/types'

type AnalysisLauncherItem = {
  view: AnalysisViewRecord
  adequacy: AnalysisAdequacyResult | null
  error: string
}

const REQUIREMENT_TIERS: AnalysisRequirementTier[] = ['required', 'recommended', 'optional']

export function AnalysisLauncher({
  studySet,
  dataSource,
  onOpenAnalysis,
}: {
  studySet: StudySet
  dataSource: LibraryDataSource
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
        <div>
          <p className="modal-kicker">Analysis launcher</p>
          <h3>{studySet.displayName || 'Untitled Study Set'}</h3>
          <p>
            Choose an analysis view for the current scope. The adequacy check reports whether the selected sessions
            have the required and recommended data for that view. Opening a view creates a separate browser tab so the
            Library Browser remains available.
          </p>
          <p className="analysis-route-note">
            {studySet.id && studySet.saved
              ? 'This saved Study Set opens with a reloadable analysis route.'
              : 'This unsaved scope opens with a temporary browser-local route.'}
          </p>
        </div>
        <dl className="analysis-scope-summary">
          <dt>Sessions</dt>
          <dd>{studySet.sessions.length}</dd>
          <dt>Groups</dt>
          <dd>{studySet.groupings.length}</dd>
          <dt>Tracks</dt>
          <dd>{studySet.trackIds.length}</dd>
        </dl>
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
  const isSupported = item.view.id === 'simple-suspension'
  const isBlocked = item.adequacy?.status === 'blocked'
  const canOpen = isSupported && !isBlocked

  return (
    <article className={`analysis-view-card analysis-status-${status}`}>
      <div className="analysis-view-card-header">
        <div>
          <p className="analysis-view-category">{item.view.category || 'Analysis'}</p>
          <h3>{item.view.displayName}</h3>
        </div>
        <span className={`analysis-status-badge analysis-status-badge-${status}`}>
          {statusMeta.icon}
          {statusMeta.label}
        </span>
      </div>

      <p className="analysis-view-description">{item.view.description}</p>

      <div className="analysis-view-grid">
        <section>
          <h4>Requirements</h4>
          <div className="analysis-requirement-list">
            {REQUIREMENT_TIERS.map((tier) => (
              <RequirementTier key={tier} tier={tier} requirements={item.view.requirements[tier] ?? []} />
            ))}
          </div>
        </section>

        <section>
          <h4>Adequacy</h4>
          <p className="analysis-adequacy-summary">
            {item.adequacy?.summary || item.error || 'Adequacy has not been evaluated for this view.'}
          </p>
          {item.adequacy && (
            <dl className="analysis-adequacy-counts">
              <dt>Total</dt>
              <dd>{item.adequacy.totalSessionCount}</dd>
              <dt>Usable</dt>
              <dd>{item.adequacy.usableSessionCount}</dd>
              <dt>Blocked</dt>
              <dd>{item.adequacy.blockedSessionCount}</dd>
            </dl>
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
      </div>

      <div className="analysis-view-actions">
        {!isSupported && <span className="subtle">This view is registered but not implemented in the prototype yet.</span>}
        {isBlocked && <span className="subtle">This scope is missing required data for this analysis.</span>}
        <button className="primary-action compact-row-action" disabled={!canOpen} onClick={onOpen}>
          <Play size={16} />
          Open in tab
        </button>
      </div>
    </article>
  )
}

function RequirementTier({
  tier,
  requirements,
}: {
  tier: AnalysisRequirementTier
  requirements: AnalysisRequirementRecord[]
}) {
  if (requirements.length === 0) {
    return null
  }
  return (
    <div className={`analysis-requirement-tier analysis-requirement-${tier}`}>
      <span>{tier}</span>
      <ul>
        {requirements.map((requirement) => (
          <li key={requirement.requirementId} title={requirement.description}>
            {requirement.label}
          </li>
        ))}
      </ul>
    </div>
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
