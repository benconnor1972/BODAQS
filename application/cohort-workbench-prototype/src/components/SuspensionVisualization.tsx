import { useEffect, useState, type ReactNode } from 'react'
import * as d3 from 'd3'
import { ChevronDown, ChevronUp } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionByRef, sessionRefId } from '../domain/studySets'
import type {
  SessionRecord,
  SignalQueryResponse,
  SignalQuerySignalRequest,
  SessionTrackMatchRecord,
  StudySessionRef,
  StudySet,
  TableQueryRow,
  TrackRecord,
  TrackpointRecord,
} from '../domain/types'

const FRONT_COLOR = '#008c95'
const REAR_COLOR = '#101820'
const UNKNOWN_COLOR = '#8b9793'
const COMPRESSION_EVENT_TYPE = 'compressions_all'
const REBOUND_EVENT_TYPE = 'rebounds_all'
const SCATTER_X_METRIC = 'm_stroke_disp_max'
const COMPRESSION_Y_METRIC = 'm_interval_vel_max'
const REBOUND_Y_METRIC = 'm_interval_vel_min'

const SIGNAL_REQUESTS: SignalQuerySignalRequest[] = [
  { role: 'front_displacement', selector: { end: 'front', quantity: 'disp_norm', unit: '1' } },
  { role: 'rear_displacement', selector: { end: 'rear', quantity: 'disp_norm', unit: '1' } },
  { role: 'front_velocity', selector: { end: 'front', quantity: 'vel', unit: 'mm/s' } },
  { role: 'rear_velocity', selector: { end: 'rear', quantity: 'vel', unit: 'mm/s' } },
]

type VisualizationEntity = {
  id: string
  kind: 'session' | 'grouping'
  label: string
  color?: string
  sessionRefs: StudySessionRef[]
}

type VisualizationData = {
  timeBySession: Record<string, number[]>
  signalsBySession: Record<string, Record<string, number[]>>
  events: TableQueryRow[]
  metrics: TableQueryRow[]
  warnings: string[]
}

type LoadState =
  | { status: 'idle'; message: string }
  | { status: 'loading'; message: string }
  | { status: 'ready'; message: string; data: VisualizationData }
  | { status: 'error'; message: string }

type ComparisonLayout = 'entities' | 'ends'
type ScopeMode = 'whole_session' | 'sector'

type TrackSector = {
  id: string
  label: string
  order: number
  startTrackpoint: TrackpointRecord
  endTrackpoint: TrackpointRecord
  lengthM: number
}

type SectorExpansionConfig = {
  quantity: 'displacement' | 'velocity'
  title: string
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
}

export function SuspensionVisualization({
  studySet,
  sessions,
  tracks,
  dataSource,
}: {
  studySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
}) {
  const entities = visualizationEntities(studySet)
  const baseStudySetTracks = tracks.filter((track) => studySet.trackIds.includes(track.id))
  const [visualizationTrackMatches, setVisualizationTrackMatches] = useState<SessionTrackMatchRecord[] | null>(null)
  const [visualizationTrackMatchesLoading, setVisualizationTrackMatchesLoading] = useState(false)
  const studySetTracks = mergeTrackMatches(baseStudySetTracks, visualizationTrackMatches)
  const studySetTrackKey = studySetTracks.map((track) => `${track.id}:${track.revision}`).join('|')
  const studySetKey = stableStudySetKey(studySet)
  const trackMatchKey = stableTrackMatchKey(studySet)
  const [selectedEntityIds, setSelectedEntityIds] = useState<string[]>(() =>
    entities.filter((entity) => entity.kind === 'session').map((entity) => entity.id),
  )
  const [collapsedPanels, setCollapsedPanels] = useState<string[]>([])
  const [comparisonLayout, setComparisonLayout] = useState<ComparisonLayout>('entities')
  const [scopeMode, setScopeMode] = useState<ScopeMode>('whole_session')
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(() => studySetTracks[0]?.id ?? null)
  const [expandedSectorPanel, setExpandedSectorPanel] = useState<SectorExpansionConfig | null>(null)
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle', message: 'Select entities to visualize.' })

  useEffect(() => {
    setSelectedEntityIds(visualizationEntities(studySet).filter((entity) => entity.kind === 'session').map((entity) => entity.id))
  }, [studySetKey])

  useEffect(() => {
    if (!dataSource.listTrackMatches || studySet.sessions.length === 0 || studySet.trackIds.length === 0) {
      setVisualizationTrackMatches(null)
      setVisualizationTrackMatchesLoading(false)
      return
    }

    let cancelled = false
    async function loadVisualizationTrackMatches() {
      setVisualizationTrackMatchesLoading(true)
      try {
        const matches = await dataSource.listTrackMatches?.(studySet)
        if (!cancelled) {
          setVisualizationTrackMatches(matches ?? [])
          setVisualizationTrackMatchesLoading(false)
        }
      } catch {
        if (!cancelled) {
          setVisualizationTrackMatches(null)
          setVisualizationTrackMatchesLoading(false)
        }
      }
    }

    void loadVisualizationTrackMatches()
    return () => {
      cancelled = true
    }
  }, [dataSource, studySet, trackMatchKey])

  useEffect(() => {
    setSelectedTrackId((current) => {
      if (current && studySetTracks.some((track) => track.id === current)) {
        return current
      }
      return studySetTracks[0]?.id ?? null
    })
    if (studySetTracks.length === 0) {
      setScopeMode('whole_session')
    }
  }, [studySetKey, studySetTrackKey])

  const selectedEntities = entities.filter((entity) => selectedEntityIds.includes(entity.id))
  const selectedEntityKey = selectedEntityIds.join('|')
  const selectedTrack = studySetTracks.find((track) => track.id === selectedTrackId) ?? studySetTracks[0] ?? null
  const sectors = selectedTrack ? trackSectors(selectedTrack) : []

  useEffect(() => {
    let cancelled = false
    async function loadData() {
      const activeEntities = visualizationEntities(studySet).filter((entity) => selectedEntityIds.includes(entity.id))
      if (activeEntities.length === 0) {
        setLoadState({ status: 'idle', message: 'Select at least one session or grouping to visualize.' })
        return
      }
      setLoadState({ status: 'loading', message: 'Loading suspension visualization data...' })
      try {
        const data = await loadVisualizationData(activeEntities, dataSource)
        if (!cancelled) {
          setLoadState({ status: 'ready', message: 'Visualization data loaded.', data })
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : String(error)
          setLoadState({ status: 'error', message })
        }
      }
    }

    void loadData()
    return () => {
      cancelled = true
    }
  }, [dataSource, selectedEntityKey, studySet, studySetKey])

  const data = loadState.status === 'ready' ? loadState.data : null

  function toggleEntity(entityId: string) {
    setSelectedEntityIds((current) =>
      current.includes(entityId) ? current.filter((id) => id !== entityId) : [...current, entityId],
    )
  }

  function togglePanel(panelId: string) {
    setCollapsedPanels((current) =>
      current.includes(panelId) ? current.filter((id) => id !== panelId) : [...current, panelId],
    )
  }

  return (
    <div className="suspension-viz">
      <header className="suspension-viz-hero">
        <div>
          <p className="eyebrow">Browser-native quick view</p>
          <h3>{studySet.displayName || 'Current Study Set'}</h3>
          <p>
            Suspension comparison using Study Set entities. Groupings are available but deselected by default and pool
            their member sessions when enabled. Sector mode is scaffolded as the next comparison layer.
          </p>
        </div>
        <div className="suspension-viz-legend">
          <span>
            <i style={{ background: FRONT_COLOR }} />
            Front
          </span>
          <span>
            <i style={{ background: REAR_COLOR }} />
            Rear
          </span>
        </div>
      </header>

      <section className="viz-entity-selector" aria-label="Visualization entities">
        <div className="viz-selector-header">
          <strong>Visualization entities</strong>
          <span className="subtle">{selectedEntities.length} active</span>
        </div>
        <div className="viz-entity-chips">
          {entities.map((entity) => {
            const selected = selectedEntityIds.includes(entity.id)
            return (
              <button
                className={`viz-entity-chip${selected ? ' selected' : ''}${entity.kind === 'grouping' ? ' grouping' : ''}`}
                key={entity.id}
                type="button"
                onClick={() => toggleEntity(entity.id)}
                style={entity.color ? { borderColor: entity.color } : undefined}
              >
                {entity.color && <span className="color-dot" style={{ backgroundColor: entity.color }} />}
                <span>{entity.label}</span>
                <small>{entity.kind === 'grouping' ? `${entity.sessionRefs.length} pooled` : 'session'}</small>
              </button>
            )
          })}
        </div>
      </section>

      <ScopeModeControl
        value={scopeMode}
        onChange={setScopeMode}
        tracks={studySetTracks}
        selectedTrackId={selectedTrack?.id ?? null}
        onTrackChange={setSelectedTrackId}
        sectors={sectors}
      />

      <ComparisonLayoutToggle value={comparisonLayout} onChange={setComparisonLayout} />

      {loadState.status === 'loading' && <div className="viz-status">{loadState.message}</div>}
      {loadState.status === 'error' && <div className="viz-status warning">Could not load visualization data: {loadState.message}</div>}
      {loadState.status === 'idle' && <div className="viz-status">{loadState.message}</div>}

      {data && data.warnings.length > 0 && (
        <div className="viz-status warning">
          {data.warnings.slice(0, 3).map((warning) => String(warning)).join(' | ')}
          {data.warnings.length > 3 ? ` | ${data.warnings.length - 3} more warning(s)` : ''}
        </div>
      )}

      {data && (
        <div className="viz-panel-stack">
          <VisualizationPanel
            id="displacement"
            title="Displacement distribution"
            subtitle="Normalized displacement, fixed 0-1 axis."
            collapsed={collapsedPanels.includes('displacement')}
            onToggle={() => togglePanel('displacement')}
          >
            {scopeMode === 'sector' ? (
              <SectorDistributionScaffold
                quantity="displacement"
                entities={selectedEntities}
                data={data}
                selectedTrack={selectedTrack}
                sectors={sectors}
                frontRole="front_displacement"
                rearRole="rear_displacement"
                xDomain={[0, 1]}
                xLabel="Normalized displacement"
                bins={32}
                trackMatchesLoading={visualizationTrackMatchesLoading}
                onExpand={() =>
                  setExpandedSectorPanel({
                    quantity: 'displacement',
                    title: 'Displacement sector distributions',
                    frontRole: 'front_displacement',
                    rearRole: 'rear_displacement',
                    xDomain: [0, 1],
                    xLabel: 'Normalized displacement',
                    bins: 44,
                  })
                }
              />
            ) : (
              <DistributionEntityStrip
                layout={comparisonLayout}
                entities={selectedEntities}
                data={data}
                frontRole="front_displacement"
                rearRole="rear_displacement"
                xDomain={[0, 1]}
                xLabel="Normalized displacement"
                bins={44}
                yMax={panelHistogramYMax(selectedEntities, data, ['front_displacement', 'rear_displacement'], [0, 1], 44)}
                sessions={sessions}
                showStats
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="velocity"
            title="Velocity distribution"
            subtitle="Velocity histograms use a shared symmetric axis."
            collapsed={collapsedPanels.includes('velocity')}
            onToggle={() => togglePanel('velocity')}
          >
            {scopeMode === 'sector' ? (
              <SectorDistributionScaffold
                quantity="velocity"
                entities={selectedEntities}
                data={data}
                selectedTrack={selectedTrack}
                sectors={sectors}
                frontRole="front_velocity"
                rearRole="rear_velocity"
                xDomain={[-2000, 2000]}
                xLabel="Velocity (mm/s)"
                bins={36}
                trackMatchesLoading={visualizationTrackMatchesLoading}
                onExpand={() =>
                  setExpandedSectorPanel({
                    quantity: 'velocity',
                    title: 'Velocity sector distributions',
                    frontRole: 'front_velocity',
                    rearRole: 'rear_velocity',
                    xDomain: [-2000, 2000],
                    xLabel: 'Velocity (mm/s)',
                    bins: 56,
                  })
                }
              />
            ) : (
              <DistributionEntityStrip
                layout={comparisonLayout}
                entities={selectedEntities}
                data={data}
                frontRole="front_velocity"
                rearRole="rear_velocity"
                xDomain={[-2000, 2000]}
                xLabel="Velocity (mm/s)"
                bins={56}
                yMax={panelHistogramYMax(selectedEntities, data, ['front_velocity', 'rear_velocity'], [-2000, 2000], 56)}
                sessions={sessions}
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="events"
            title="Event counts"
            subtitle="Tabular counts by event type and signal role."
            collapsed={collapsedPanels.includes('events')}
            onToggle={() => togglePanel('events')}
          >
            <EventCountStrip entities={selectedEntities} data={data} />
          </VisualizationPanel>

          <VisualizationPanel
            id="compression"
            title="Compression metrics"
            subtitle={`${SCATTER_X_METRIC} vs ${COMPRESSION_Y_METRIC}; front/rear on one chart.`}
            collapsed={collapsedPanels.includes('compression')}
            onToggle={() => togglePanel('compression')}
          >
            {scopeMode === 'sector' ? (
              <SectorDeferredNotice label="Compression metrics" />
            ) : (
              <ScatterEntityStrip
                layout={comparisonLayout}
                entities={selectedEntities}
                data={data}
                eventType={COMPRESSION_EVENT_TYPE}
                xMetric={SCATTER_X_METRIC}
                yMetric={COMPRESSION_Y_METRIC}
                yLabel="Compression velocity"
                showRegression
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="rebound"
            title="Rebound metrics"
            subtitle={`${SCATTER_X_METRIC} vs ${REBOUND_Y_METRIC}; front/rear on one chart.`}
            collapsed={collapsedPanels.includes('rebound')}
            onToggle={() => togglePanel('rebound')}
          >
            {scopeMode === 'sector' ? (
              <SectorDeferredNotice label="Rebound metrics" />
            ) : (
              <ScatterEntityStrip
                layout={comparisonLayout}
                entities={selectedEntities}
                data={data}
                eventType={REBOUND_EVENT_TYPE}
                xMetric={SCATTER_X_METRIC}
                yMetric={REBOUND_Y_METRIC}
                yLabel="Rebound velocity"
                showRegression
              />
            )}
          </VisualizationPanel>
        </div>
      )}

      {expandedSectorPanel && data && selectedTrack && (
        <SectorExpansionModal
          config={expandedSectorPanel}
          data={data}
          entities={selectedEntities}
          onClose={() => setExpandedSectorPanel(null)}
          sectors={sectors}
          selectedTrack={selectedTrack}
          trackMatchesLoading={visualizationTrackMatchesLoading}
        />
      )}
    </div>
  )
}

function ComparisonLayoutToggle({
  value,
  onChange,
}: {
  value: ComparisonLayout
  onChange: (value: ComparisonLayout) => void
}) {
  return (
    <section className="viz-layout-toggle" aria-label="Comparison layout">
      <div>
        <strong>Comparison layout</strong>
        <span>Choose which dimension becomes the horizontal facet.</span>
      </div>
      <div className="viz-layout-buttons">
        <button
          className={value === 'entities' ? 'active' : ''}
          type="button"
          onClick={() => onChange('entities')}
        >
          Entities as columns
          <small>Front/rear together</small>
        </button>
        <button
          className={value === 'ends' ? 'active' : ''}
          type="button"
          onClick={() => onChange('ends')}
        >
          Ends as columns
          <small>Entities together</small>
        </button>
      </div>
    </section>
  )
}

function ScopeModeControl({
  value,
  onChange,
  tracks,
  selectedTrackId,
  onTrackChange,
  sectors,
}: {
  value: ScopeMode
  onChange: (value: ScopeMode) => void
  tracks: TrackRecord[]
  selectedTrackId: string | null
  onTrackChange: (trackId: string | null) => void
  sectors: TrackSector[]
}) {
  const hasTracks = tracks.length > 0
  return (
    <section className="viz-scope-control" aria-label="Visualization scope">
      <div className="viz-scope-main">
        <div>
          <strong>Visualization scope</strong>
          <span>
            {value === 'sector'
              ? 'Sector mode is scaffolded for displacement and velocity; chart slicing lands in the next slice.'
              : 'Whole-session mode uses all matching samples/events from each selected entity.'}
          </span>
        </div>
        <div className="viz-layout-buttons">
          <button
            className={value === 'whole_session' ? 'active' : ''}
            type="button"
            onClick={() => onChange('whole_session')}
          >
            Whole session
            <small>Current charts</small>
          </button>
          <button
            className={value === 'sector' ? 'active' : ''}
            type="button"
            disabled={!hasTracks}
            onClick={() => onChange('sector')}
          >
            By sector
            <small>{hasTracks ? 'Track ordered' : 'No track attached'}</small>
          </button>
        </div>
      </div>
      {value === 'sector' && (
        <div className="viz-sector-config">
          <label>
            Track
            <select
              value={selectedTrackId ?? ''}
              onChange={(event) => onTrackChange(event.target.value || null)}
              disabled={!hasTracks}
            >
              {tracks.map((track) => (
                <option value={track.id} key={track.id}>
                  {track.name} ({track.trackpoints.length} trackpoints)
                </option>
              ))}
            </select>
          </label>
          <div className="viz-sector-summary">
            <strong>{sectors.length}</strong>
            <span>trackpoint-bounded sector(s) available</span>
          </div>
        </div>
      )}
    </section>
  )
}

function VisualizationPanel({
  id,
  title,
  subtitle,
  collapsed,
  onToggle,
  children,
}: {
  id: string
  title: string
  subtitle: string
  collapsed: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <section className={`viz-panel${collapsed ? ' collapsed' : ''}`} aria-labelledby={`viz-panel-${id}`}>
      <button className="viz-panel-header" type="button" onClick={onToggle}>
        <span>
          <strong id={`viz-panel-${id}`}>{title}</strong>
          <small>{subtitle}</small>
        </span>
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {!collapsed && children}
    </section>
  )
}

function DistributionEntityStrip({
  layout,
  entities,
  data,
  frontRole,
  rearRole,
  xDomain,
  xLabel,
  bins,
  yMax,
  sessions,
  showStats = false,
}: {
  layout: ComparisonLayout
  entities: VisualizationEntity[]
  data: VisualizationData
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
  sessions: SessionRecord[]
  showStats?: boolean
}) {
  if (layout === 'ends') {
    return (
      <DistributionEndStrip
        entities={entities}
        data={data}
        frontRole={frontRole}
        rearRole={rearRole}
        xDomain={xDomain}
        xLabel={xLabel}
        bins={bins}
        yMax={yMax}
      />
    )
  }

  return (
    <div className="viz-entity-strip">
      {entities.map((entity) => {
        const front = entitySignalValues(entity, data, frontRole)
        const rear = entitySignalValues(entity, data, rearRole)
        return (
          <article className="viz-entity-tile" key={entity.id}>
            <EntityTileHeader entity={entity} sessions={sessions} />
            <HistogramOverlayChart
              front={front}
              rear={rear}
              xDomain={xDomain}
              xLabel={xLabel}
              bins={bins}
              yMax={yMax}
            />
            {showStats && <DisplacementStats front={front} rear={rear} />}
          </article>
        )
      })}
    </div>
  )
}

function DistributionEndStrip({
  entities,
  data,
  frontRole,
  rearRole,
  xDomain,
  xLabel,
  bins,
  yMax,
}: {
  entities: VisualizationEntity[]
  data: VisualizationData
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
}) {
  const roles = [
    { key: 'front', label: 'Front', signalRole: frontRole },
    { key: 'rear', label: 'Rear', signalRole: rearRole },
  ] as const
  return (
    <div className="viz-entity-strip">
      {roles.map((role) => {
        const series = entities.map((entity, index) => ({
          id: entity.id,
          label: entity.label,
          color: entityColor(entity, index),
          values: entitySignalValues(entity, data, role.signalRole),
        }))
        return (
          <article className="viz-entity-tile viz-end-tile" key={role.key}>
            <EndTileHeader label={role.label} />
            <MultiHistogramChart series={series} xDomain={xDomain} xLabel={xLabel} bins={bins} yMax={yMax} />
            <EntitySeriesLegend
              series={series.map((item) => ({
                id: item.id,
                label: item.label,
                color: item.color,
                count: item.values.length,
              }))}
              emptyLabel="No matching signals"
            />
          </article>
        )
      })}
    </div>
  )
}

function SectorDistributionScaffold({
  quantity,
  entities,
  data,
  selectedTrack,
  sectors,
  frontRole,
  rearRole,
  xDomain,
  xLabel,
  bins,
  trackMatchesLoading,
  onExpand,
}: {
  quantity: 'displacement' | 'velocity'
  entities: VisualizationEntity[]
  data: VisualizationData
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
  trackMatchesLoading: boolean
  onExpand?: () => void
}) {
  if (!selectedTrack) {
    return (
      <div className="viz-sector-empty">
        <strong>No track attached to this Study Set.</strong>
        <span>Attach a track in the workbench before sector-based {quantity} comparison can be built.</span>
      </div>
    )
  }
  if (sectors.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>{selectedTrack.name} has fewer than two ordered trackpoints.</strong>
        <span>Sector charts need at least two trackpoints so the browser can form trackpoint-bounded sectors.</span>
      </div>
    )
  }
  const yMax = sectorHistogramYMax(entities, data, selectedTrack, sectors, [frontRole, rearRole], xDomain, bins)
  const intervalEntityCount = entities.filter((entity) => entityHasSectorIntervals(entity, selectedTrack, sectors)).length
  return (
    <div className="viz-sector-scaffold">
      <div className="viz-sector-scaffold-note">
        <div className="viz-sector-scaffold-note-text">
          <strong>Sector chart scaffold</strong>
          <span>
            {selectedTrack.name}: {sectors.length} sector(s), {entities.length} active entity/entities. Samples are
            assigned from trackpoint crossing-time intervals. {intervalEntityCount} active entity/entities currently have
            usable sector intervals.
          </span>
        </div>
        {onExpand && (
          <button className="viz-sector-expand-button" type="button" onClick={onExpand}>
            Expand detail view
          </button>
        )}
      </div>
      <div className="viz-entity-strip">
        {entities.map((entity) => {
          const hasSectorSamples = entityHasSectorSamples(entity, data, selectedTrack, sectors, [frontRole, rearRole])
          const hasIntervals = entityHasSectorIntervals(entity, selectedTrack, sectors)
          if (!hasSectorSamples && trackMatchesLoading && !hasIntervals) {
            return (
              <article className="viz-entity-tile viz-sector-tile" key={entity.id}>
                <EntityTileHeader entity={entity} />
                <div className="viz-sector-fallback-note">
                  Loading sector match intervals for this entity...
                </div>
              </article>
            )
          }
          if (!hasSectorSamples) {
            const front = entitySignalValues(entity, data, frontRole)
            const rear = entitySignalValues(entity, data, rearRole)
            return (
              <article className="viz-entity-tile viz-sector-tile" key={entity.id}>
                <EntityTileHeader entity={entity} />
                <div className="viz-sector-fallback-note">
                  No sector samples were available for this entity, so the whole-session distribution is shown.
                </div>
                <HistogramOverlayChart
                  front={front}
                  rear={rear}
                  xDomain={xDomain}
                  xLabel={xLabel}
                  bins={bins}
                  yMax={panelHistogramYMax([entity], data, [frontRole, rearRole], xDomain, bins)}
                />
              </article>
            )
          }
          return (
            <article className="viz-entity-tile viz-sector-tile" key={entity.id}>
              <EntityTileHeader entity={entity} />
              <div className="viz-sector-grid">
                <div className="viz-sector-grid-head">Sector</div>
                <div className="viz-sector-grid-head">Front</div>
                <div className="viz-sector-grid-head">Rear</div>
                {sectors.map((sector) => (
                  <SectorDistributionRow
                    bins={bins}
                    data={data}
                    entity={entity}
                    frontRole={frontRole}
                    key={sector.id}
                    rearRole={rearRole}
                    sector={sector}
                    track={selectedTrack}
                    xDomain={xDomain}
                    yMax={yMax}
                  />
                ))}
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}

function SectorExpansionModal({
  config,
  entities,
  data,
  selectedTrack,
  sectors,
  trackMatchesLoading,
  onClose,
}: {
  config: SectorExpansionConfig
  entities: VisualizationEntity[]
  data: VisualizationData
  selectedTrack: TrackRecord
  sectors: TrackSector[]
  trackMatchesLoading: boolean
  onClose: () => void
}) {
  const yMax = sectorHistogramYMax(
    entities,
    data,
    selectedTrack,
    sectors,
    [config.frontRole, config.rearRole],
    config.xDomain,
    config.bins,
  )
  const sampledEntityCount = entities.filter((entity) =>
    entityHasSectorSamples(entity, data, selectedTrack, sectors, [config.frontRole, config.rearRole]),
  ).length

  return (
    <div className="viz-expansion-backdrop" onClick={onClose} role="presentation">
      <section
        aria-label={config.title}
        aria-modal="true"
        className="viz-expansion-modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="viz-expansion-header">
          <div>
            <p className="eyebrow">Expanded sector view</p>
            <h3>{config.title}</h3>
            <p>
              {selectedTrack.name}: {sectors.length} sector(s). {sampledEntityCount} of {entities.length} active
              entity/entities currently have sector samples.
            </p>
          </div>
          <button className="viz-expansion-close" type="button" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="viz-expansion-body">
          {entities.map((entity) => {
            const hasSectorSamples = entityHasSectorSamples(entity, data, selectedTrack, sectors, [
              config.frontRole,
              config.rearRole,
            ])
            const hasIntervals = entityHasSectorIntervals(entity, selectedTrack, sectors)
            if (!hasSectorSamples && trackMatchesLoading && !hasIntervals) {
              return (
                <article className="viz-expansion-entity" key={entity.id}>
                  <EntityTileHeader entity={entity} />
                  <div className="viz-sector-fallback-note">Loading sector match intervals for this entity...</div>
                </article>
              )
            }
            if (!hasSectorSamples) {
              const front = entitySignalValues(entity, data, config.frontRole)
              const rear = entitySignalValues(entity, data, config.rearRole)
              return (
                <article className="viz-expansion-entity" key={entity.id}>
                  <EntityTileHeader entity={entity} />
                  <div className="viz-sector-fallback-note">
                    No sector samples were available for this entity, so the whole-session distribution is shown.
                  </div>
                  <HistogramOverlayChart
                    bins={config.bins}
                    front={front}
                    rear={rear}
                    xDomain={config.xDomain}
                    xLabel={config.xLabel}
                    yMax={panelHistogramYMax([entity], data, [config.frontRole, config.rearRole], config.xDomain, config.bins)}
                  />
                </article>
              )
            }

            return (
              <article className="viz-expansion-entity" key={entity.id}>
                <EntityTileHeader entity={entity} />
                <div className="viz-expansion-sector-head">
                  <span>Sector</span>
                  <span>Front</span>
                  <span>Rear</span>
                </div>
                <div className="viz-expansion-sector-stack">
                  {sectors.map((sector) => (
                    <ExpandedSectorRow
                      bins={config.bins}
                      data={data}
                      entity={entity}
                      frontRole={config.frontRole}
                      key={sector.id}
                      rearRole={config.rearRole}
                      sector={sector}
                      track={selectedTrack}
                      xDomain={config.xDomain}
                      xLabel={config.xLabel}
                      yMax={yMax}
                    />
                  ))}
                </div>
              </article>
            )
          })}
        </div>
      </section>
    </div>
  )
}

function ExpandedSectorRow({
  entity,
  data,
  track,
  sector,
  frontRole,
  rearRole,
  xDomain,
  xLabel,
  bins,
  yMax,
}: {
  entity: VisualizationEntity
  data: VisualizationData
  track: TrackRecord
  sector: TrackSector
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
}) {
  const front = sectorValuesForEntity(entity, data, track, sector, frontRole)
  const rear = sectorValuesForEntity(entity, data, track, sector, rearRole)
  return (
    <div className="viz-expansion-sector-row">
      <div className="viz-expansion-sector-label">
        <strong>{sector.label}</strong>
        <small>{formatMetres(sector.lengthM)}</small>
      </div>
      <ExpandedSectorHistogram
        color={FRONT_COLOR}
        sampleLabel="front"
        values={front}
        xDomain={xDomain}
        xLabel={xLabel}
        bins={bins}
        yMax={yMax}
      />
      <ExpandedSectorHistogram
        color={REAR_COLOR}
        sampleLabel="rear"
        values={rear}
        xDomain={xDomain}
        xLabel={xLabel}
        bins={bins}
        yMax={yMax}
      />
    </div>
  )
}

function ExpandedSectorHistogram({
  values,
  xDomain,
  xLabel,
  bins,
  yMax,
  color,
  sampleLabel,
}: {
  values: number[]
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
  color: string
  sampleLabel: string
}) {
  const width = 360
  const height = 132
  const margin = { top: 14, right: 12, bottom: 34, left: 38 }
  const clean = values.filter(Number.isFinite)
  const histogram = histogramBins(clean, xDomain, bins)
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, yMax || 1]).range([height - margin.bottom, margin.top])
  const ticks = x.ticks(5)
  return (
    <svg
      aria-label={`${sampleLabel} ${xLabel} histogram with ${clean.length} samples`}
      className="viz-expanded-histogram"
      role="img"
      viewBox={`0 0 ${width} ${height}`}
    >
      <line className="viz-axis" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
      <line className="viz-axis" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
      {ticks.map((tick) => (
        <g key={tick} transform={`translate(${x(tick)} 0)`}>
          <line className="viz-tick" y1={height - margin.bottom} y2={height - margin.bottom + 4} />
          <text className="viz-axis-label" textAnchor="middle" y={height - margin.bottom + 16}>
            {formatAxis(tick)}
          </text>
        </g>
      ))}
      {histogram.map((bin, index) => {
        const x0 = x(bin.x0)
        const x1 = x(bin.x1)
        const barWidth = Math.max(1, x1 - x0 - 1)
        return (
          <rect
            fill={color}
            fillOpacity={0.74}
            height={height - margin.bottom - y(bin.proportion)}
            key={`${bin.x0}-${index}`}
            width={barWidth}
            x={x0}
            y={y(bin.proportion)}
          />
        )
      })}
      <text className="viz-axis-title" x={(margin.left + width - margin.right) / 2} y={height - 6} textAnchor="middle">
        {xLabel}
      </text>
      <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
        Proportion
      </text>
      <text className="viz-expanded-sample-count" x={width - margin.right} y={margin.top + 5} textAnchor="end">
        n={clean.length.toLocaleString()}
      </text>
      {clean.length === 0 && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
          No sector samples
        </text>
      )}
    </svg>
  )
}

function SectorDistributionRow({
  entity,
  data,
  track,
  sector,
  frontRole,
  rearRole,
  xDomain,
  bins,
  yMax,
}: {
  entity: VisualizationEntity
  data: VisualizationData
  track: TrackRecord
  sector: TrackSector
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  bins: number
  yMax: number
}) {
  const front = sectorValuesForEntity(entity, data, track, sector, frontRole)
  const rear = sectorValuesForEntity(entity, data, track, sector, rearRole)
  return (
    <>
      <div className="viz-sector-label">
        <strong>{sector.label}</strong>
        <small>{formatMetres(sector.lengthM)}</small>
      </div>
      <div className="viz-sector-cell">
        <MiniRidgeline values={front} xDomain={xDomain} bins={bins} yMax={yMax} color={FRONT_COLOR} />
      </div>
      <div className="viz-sector-cell">
        <MiniRidgeline values={rear} xDomain={xDomain} bins={bins} yMax={yMax} color={REAR_COLOR} />
      </div>
    </>
  )
}

function SectorDeferredNotice({ label }: { label: string }) {
  return (
    <div className="viz-sector-empty">
      <strong>{label} sector mode is deferred.</strong>
      <span>
        The first sector implementation will target displacement and velocity distributions. Metric scatter can be
        faceted by sector later once the sample/event sector assignment contract is proven.
      </span>
    </div>
  )
}

function EventCountStrip({ entities, data }: { entities: VisualizationEntity[]; data: VisualizationData }) {
  return (
    <div className="viz-entity-strip">
      {entities.map((entity) => (
        <article className="viz-entity-tile compact" key={entity.id}>
          <EntityTileHeader entity={entity} />
          <EventCountTable rows={entityRows(entity, data.events)} />
        </article>
      ))}
    </div>
  )
}

function ScatterEntityStrip({
  layout,
  entities,
  data,
  eventType,
  xMetric,
  yMetric,
  yLabel,
  showRegression = false,
}: {
  layout: ComparisonLayout
  entities: VisualizationEntity[]
  data: VisualizationData
  eventType: string
  xMetric: string
  yMetric: string
  yLabel: string
  showRegression?: boolean
}) {
  const extent = scatterPanelExtent(entities, data, eventType, xMetric, yMetric)
  if (layout === 'ends') {
    return (
      <ScatterEndStrip
        entities={entities}
        data={data}
        eventType={eventType}
        xMetric={xMetric}
        yMetric={yMetric}
        yLabel={yLabel}
        extent={extent}
        showRegression={showRegression}
      />
    )
  }

  return (
    <div className="viz-entity-strip">
      {entities.map((entity) => {
        const points = scatterPoints(entityRows(entity, data.metrics), eventType, xMetric, yMetric)
        return (
          <article className="viz-entity-tile" key={entity.id}>
            <EntityTileHeader entity={entity} />
            <ScatterChart
              points={points}
              xDomain={extent.x}
              yDomain={extent.y}
              xLabel="Stroke displacement"
              yLabel={yLabel}
              showRegression={showRegression}
            />
          </article>
        )
      })}
    </div>
  )
}

function ScatterEndStrip({
  entities,
  data,
  eventType,
  xMetric,
  yMetric,
  yLabel,
  extent,
  showRegression,
}: {
  entities: VisualizationEntity[]
  data: VisualizationData
  eventType: string
  xMetric: string
  yMetric: string
  yLabel: string
  extent: { x: [number, number]; y: [number, number] }
  showRegression: boolean
}) {
  const roles = [
    { key: 'front', label: 'Front' },
    { key: 'rear', label: 'Rear' },
  ] as const
  return (
    <div className="viz-entity-strip">
      {roles.map((role) => {
        const series = entities.map((entity, index) => ({
          id: entity.id,
          label: entity.label,
          color: entityColor(entity, index),
          points: scatterPoints(entityRows(entity, data.metrics), eventType, xMetric, yMetric).filter(
            (point) => point.role === role.key,
          ),
        }))
        return (
          <article className="viz-entity-tile viz-end-tile" key={role.key}>
            <EndTileHeader label={role.label} />
            <EntityScatterChart
              series={series}
              xDomain={extent.x}
              yDomain={extent.y}
              xLabel="Stroke displacement"
              yLabel={yLabel}
              showRegression={showRegression}
            />
            <EntitySeriesLegend
              series={series.map((item) => ({
                id: item.id,
                label: item.label,
                color: item.color,
                count: item.points.length,
              }))}
              emptyLabel="No metric rows"
            />
          </article>
        )
      })}
    </div>
  )
}

function EntityTileHeader({ entity, sessions = [] }: { entity: VisualizationEntity; sessions?: SessionRecord[] }) {
  const concreteSessions = entity.sessionRefs.map((ref) => sessionByRef(ref, sessions)).filter(Boolean)
  const subtitle =
    entity.kind === 'grouping'
      ? `${entity.sessionRefs.length} pooled sessions`
      : concreteSessions[0]?.startedAt || entity.sessionRefs[0]?.sessionId
  return (
    <header className="viz-entity-tile-header">
      <strong>{entity.label}</strong>
      <small>{subtitle}</small>
    </header>
  )
}

function EndTileHeader({ label }: { label: string }) {
  return (
    <header className="viz-entity-tile-header viz-end-tile-header">
      <strong>{label}</strong>
      <small>selected entities overlaid</small>
    </header>
  )
}

function HistogramOverlayChart({
  front,
  rear,
  xDomain,
  xLabel,
  bins,
  yMax,
}: {
  front: number[]
  rear: number[]
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 180
  const margin = { top: 12, right: 12, bottom: 34, left: 34 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, yMax || 1]).range([height - margin.bottom, margin.top])
  const frontBins = histogramBins(front, xDomain, bins)
  const rearBins = histogramBins(rear, xDomain, bins)
  const barWidth = Math.max(1, (width - margin.left - margin.right) / bins)
  return (
    <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={xLabel}>
      <line className="viz-axis" x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
      <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
      {[0, 0.5, 1].map((tick) => {
        const value = xDomain[0] + (xDomain[1] - xDomain[0]) * tick
        return (
          <g key={tick}>
            <line className="viz-tick" x1={x(value)} x2={x(value)} y1={height - margin.bottom} y2={height - margin.bottom + 4} />
            <text className="viz-axis-label" x={x(value)} y={height - 14} textAnchor="middle">
              {formatAxis(value)}
            </text>
          </g>
        )
      })}
      {rearBins.map((bin) => (
        <rect
          fill={REAR_COLOR}
          fillOpacity={0.34}
          key={`rear-${bin.x0}`}
          x={x(bin.x0)}
          y={y(bin.proportion)}
          width={barWidth}
          height={height - margin.bottom - y(bin.proportion)}
        />
      ))}
      {frontBins.map((bin) => (
        <rect
          fill={FRONT_COLOR}
          fillOpacity={0.52}
          key={`front-${bin.x0}`}
          x={x(bin.x0)}
          y={y(bin.proportion)}
          width={barWidth}
          height={height - margin.bottom - y(bin.proportion)}
        />
      ))}
      <text className="viz-axis-title" x={width / 2} y={height - 1} textAnchor="middle">
        {xLabel}
      </text>
      {front.length === 0 && rear.length === 0 && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
          No matching signals
        </text>
      )}
    </svg>
  )
}

function MultiHistogramChart({
  series,
  xDomain,
  xLabel,
  bins,
  yMax,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 180
  const margin = { top: 12, right: 12, bottom: 34, left: 34 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, yMax || 1]).range([height - margin.bottom, margin.top])
  const line = d3
    .line<{ x0: number; x1: number; proportion: number }>()
    .x((bin) => x((bin.x0 + bin.x1) / 2))
    .y((bin) => y(bin.proportion))
    .curve(d3.curveStepAfter)
  const seriesBins = series.map((item) => ({
    ...item,
    bins: histogramBins(item.values, xDomain, bins),
  }))
  const allEmpty = series.every((item) => item.values.length === 0)
  return (
    <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={xLabel}>
      <line className="viz-axis" x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
      <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
      {[0, 0.5, 1].map((tick) => {
        const value = xDomain[0] + (xDomain[1] - xDomain[0]) * tick
        return (
          <g key={tick}>
            <line className="viz-tick" x1={x(value)} x2={x(value)} y1={height - margin.bottom} y2={height - margin.bottom + 4} />
            <text className="viz-axis-label" x={x(value)} y={height - 14} textAnchor="middle">
              {formatAxis(value)}
            </text>
          </g>
        )
      })}
      {seriesBins.map((item) => {
        const path = line(item.bins)
        return path ? (
          <path className="viz-series-line" d={path} key={item.id} stroke={item.color} />
        ) : null
      })}
      <text className="viz-axis-title" x={width / 2} y={height - 1} textAnchor="middle">
        {xLabel}
      </text>
      {allEmpty && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
          No matching signals
        </text>
      )}
    </svg>
  )
}

function MiniRidgeline({
  values,
  xDomain,
  bins,
  yMax,
  color,
}: {
  values: number[]
  xDomain: [number, number]
  bins: number
  yMax: number
  color: string
}) {
  const width = 126
  const height = 34
  const margin = { top: 4, right: 4, bottom: 6, left: 4 }
  const clean = values.filter(Number.isFinite)
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, yMax || 1]).range([height - margin.bottom, margin.top])
  const ridgelineBins = histogramBins(clean, xDomain, bins)
  const area = d3
    .area<{ x0: number; x1: number; proportion: number }>()
    .x((bin) => x((bin.x0 + bin.x1) / 2))
    .y0(height - margin.bottom)
    .y1((bin) => y(bin.proportion))
    .curve(d3.curveBasis)
  const path = area(ridgelineBins)
  return (
    <svg className="viz-mini-ridgeline" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${clean.length} sector samples`}>
      <line className="viz-mini-baseline" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
      {path && <path d={path} fill={color} fillOpacity={0.28} stroke={color} strokeOpacity={0.9} strokeWidth={1.4} />}
      {clean.length === 0 && (
        <text className="viz-mini-empty" x={width / 2} y={height / 2 + 3} textAnchor="middle">
          no samples
        </text>
      )}
    </svg>
  )
}

function ScatterChart({
  points,
  xDomain,
  yDomain,
  xLabel,
  yLabel,
  showRegression = false,
}: {
  points: Array<{ x: number; y: number; role: 'front' | 'rear' | 'unknown' }>
  xDomain: [number, number]
  yDomain: [number, number]
  xLabel: string
  yLabel: string
  showRegression?: boolean
}) {
  const width = 324
  const height = 210
  const margin = { top: 12, right: 12, bottom: 42, left: 44 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain(yDomain).range([height - margin.bottom, margin.top])
  const regressions = showRegression ? roleRegressions(points, xDomain) : []
  return (
    <>
      <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${xLabel} by ${yLabel}`}>
        <line className="viz-axis" x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
        <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
        {regressions.map((fit) => (
          <line
            className="viz-fit-line"
            key={fit.role}
            stroke={roleColor(fit.role)}
            x1={x(fit.x0)}
            x2={x(fit.x1)}
            y1={y(fit.y0)}
            y2={y(fit.y1)}
          />
        ))}
        {points.map((point, index) => (
          <circle
            cx={x(point.x)}
            cy={y(point.y)}
            fill={roleColor(point.role)}
            fillOpacity={0.72}
            key={`${point.role}-${index}`}
            r={2.7}
          />
        ))}
        <text className="viz-axis-title" x={width / 2} y={height - 6} textAnchor="middle">
          {xLabel}
        </text>
        <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
          {yLabel}
        </text>
        {points.length === 0 && (
          <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
            No metric rows
          </text>
        )}
      </svg>
      {showRegression && (
        <RegressionSummary regressions={regressions} points={points} />
      )}
    </>
  )
}

function EntityScatterChart({
  series,
  xDomain,
  yDomain,
  xLabel,
  yLabel,
  showRegression = false,
}: {
  series: Array<{ id: string; label: string; color: string; points: Array<{ x: number; y: number }> }>
  xDomain: [number, number]
  yDomain: [number, number]
  xLabel: string
  yLabel: string
  showRegression?: boolean
}) {
  const width = 324
  const height = 210
  const margin = { top: 12, right: 12, bottom: 42, left: 44 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain(yDomain).range([height - margin.bottom, margin.top])
  const regressions = showRegression ? seriesRegressions(series, xDomain) : []
  const allEmpty = series.every((item) => item.points.length === 0)
  return (
    <>
      <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${xLabel} by ${yLabel}`}>
        <line className="viz-axis" x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
        <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
        {regressions.map((fit) => (
          <line
            className="viz-fit-line"
            key={fit.id}
            stroke={fit.color}
            x1={x(fit.x0)}
            x2={x(fit.x1)}
            y1={y(fit.y0)}
            y2={y(fit.y1)}
          />
        ))}
        {series.flatMap((item) =>
          item.points.map((point, index) => (
            <circle
              cx={x(point.x)}
              cy={y(point.y)}
              fill={item.color}
              fillOpacity={0.72}
              key={`${item.id}-${index}`}
              r={2.7}
            />
          )),
        )}
        <text className="viz-axis-title" x={width / 2} y={height - 6} textAnchor="middle">
          {xLabel}
        </text>
        <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
          {yLabel}
        </text>
        {allEmpty && (
          <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
            No metric rows
          </text>
        )}
      </svg>
      {showRegression && <SeriesRegressionSummary regressions={regressions} series={series} />}
    </>
  )
}

function RegressionSummary({
  regressions,
  points,
}: {
  regressions: LinearRegressionFit[]
  points: Array<{ x: number; y: number; role: 'front' | 'rear' | 'unknown' }>
}) {
  if (points.length === 0) {
    return null
  }
  const missing = (['front', 'rear'] as const).filter(
    (role) => points.some((point) => point.role === role) && !regressions.some((fit) => fit.role === role),
  )
  return (
    <div className="viz-regression-summary" aria-label="Best-fit summaries">
      {regressions.map((fit) => (
        <div key={fit.role}>
          <span style={{ background: roleColor(fit.role) }} />
          <strong>{formatRole(fit.role)}</strong>
          <small>
            y = {formatSlope(fit.slope)}x {formatIntercept(fit.intercept)}; R<sup>2</sup> = {fit.rSquared.toFixed(2)}
          </small>
        </div>
      ))}
      {missing.map((role) => (
        <div key={role}>
          <span style={{ background: roleColor(role) }} />
          <strong>{formatRole(role)}</strong>
          <small>not enough variation for fit</small>
        </div>
      ))}
    </div>
  )
}

function SeriesRegressionSummary({
  regressions,
  series,
}: {
  regressions: SeriesRegressionFit[]
  series: Array<{ id: string; label: string; color: string; points: Array<{ x: number; y: number }> }>
}) {
  if (series.every((item) => item.points.length === 0)) {
    return null
  }
  const missing = series.filter(
    (item) => item.points.length > 0 && !regressions.some((fit) => fit.id === item.id),
  )
  return (
    <div className="viz-regression-summary" aria-label="Best-fit summaries">
      {regressions.map((fit) => (
        <div key={fit.id}>
          <span style={{ background: fit.color }} />
          <strong>{fit.label}</strong>
          <small>
            y = {formatSlope(fit.slope)}x {formatIntercept(fit.intercept)}; R<sup>2</sup> = {fit.rSquared.toFixed(2)}
          </small>
        </div>
      ))}
      {missing.map((item) => (
        <div key={item.id}>
          <span style={{ background: item.color }} />
          <strong>{item.label}</strong>
          <small>not enough variation for fit</small>
        </div>
      ))}
    </div>
  )
}

function EntitySeriesLegend({
  series,
  emptyLabel,
}: {
  series: Array<{ id: string; label: string; color: string; count: number }>
  emptyLabel: string
}) {
  if (series.length === 0) {
    return <div className="viz-series-legend muted">{emptyLabel}</div>
  }
  return (
    <div className="viz-series-legend" aria-label="Entity series">
      {series.map((item) => (
        <div key={item.id}>
          <span style={{ background: item.color }} />
          <strong>{item.label}</strong>
          <small>{item.count ? `${item.count} rows` : emptyLabel}</small>
        </div>
      ))}
    </div>
  )
}

function EventCountTable({ rows }: { rows: TableQueryRow[] }) {
  const counts = eventCounts(rows)
  return (
    <table className="viz-count-table">
      <thead>
        <tr>
          <th>Event</th>
          <th>Front</th>
          <th>Rear</th>
          <th>Unknown</th>
        </tr>
      </thead>
      <tbody>
        {counts.length === 0 && (
          <tr>
            <td colSpan={4}>No events</td>
          </tr>
        )}
        {counts.map((row) => (
          <tr key={row.eventType}>
            <td>{row.eventType}</td>
            <td>{row.front || '-'}</td>
            <td>{row.rear || '-'}</td>
            <td>{row.unknown || '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DisplacementStats({ front, rear }: { front: number[]; rear: number[] }) {
  return (
    <div className="viz-stat-grid">
      <RoleStats label="Front" values={front} />
      <RoleStats label="Rear" values={rear} />
    </div>
  )
}

function RoleStats({ label, values }: { label: string; values: number[] }) {
  const stats = distributionStats(values)
  return (
    <dl>
      <dt>{label}</dt>
      <dd>median {formatPercent(stats.median)}</dd>
      <dd>95th {formatPercent(stats.p95)}</dd>
      <dd>max {formatPercent(stats.max)}</dd>
    </dl>
  )
}

async function loadVisualizationData(
  entities: VisualizationEntity[],
  dataSource: LibraryDataSource,
): Promise<VisualizationData> {
  const sessionRefs = uniqueSessionRefs(entities.flatMap((entity) => entity.sessionRefs))
  const refsByLibrary = groupRefsByLibrary(sessionRefs)
  const signalResponses: SignalQueryResponse[] = []
  const eventRows: TableQueryRow[] = []
  const metricRows: TableQueryRow[] = []
  const warnings: string[] = []

  for (const [libraryId, refs] of refsByLibrary.entries()) {
    const [signals, events, metrics] = await Promise.all([
      dataSource.querySignals(libraryId, { sessions: refs, signals: SIGNAL_REQUESTS }),
      dataSource.queryEvents(libraryId, { sessions: refs }),
      dataSource.queryMetrics(libraryId, {
        sessions: refs,
        eventTypes: [COMPRESSION_EVENT_TYPE, REBOUND_EVENT_TYPE],
      }),
    ])
    signalResponses.push(signals)
    eventRows.push(...events.rows)
    metricRows.push(...metrics.rows)
    warnings.push(...signals.warnings.map((warning) => warningMessage(warning)))
    warnings.push(...events.warnings.map((warning) => warningMessage(warning)))
    warnings.push(...metrics.warnings.map((warning) => warningMessage(warning)))
  }

  return {
    timeBySession: signalResponsesToTimeMap(signalResponses, warnings),
    signalsBySession: signalResponsesToMap(signalResponses, warnings),
    events: eventRows,
    metrics: metricRows,
    warnings: warnings.filter(Boolean),
  }
}

function visualizationEntities(studySet: StudySet): VisualizationEntity[] {
  const sessionEntities = studySet.sessions.map((sessionRef) => ({
    id: sessionRefId(sessionRef),
    kind: 'session' as const,
    label: sessionRef.label || sessionRef.sessionId,
    sessionRefs: [{ ...sessionRef }],
  }))
  const groupingEntities = studySet.groupings.map((grouping) => {
    const sessionRefs = grouping.sessionRefs
      .map((refId) => studySet.sessions.find((sessionRef) => sessionRefId(sessionRef) === refId))
      .filter((sessionRef): sessionRef is StudySessionRef => Boolean(sessionRef))
      .map((sessionRef) => ({ ...sessionRef }))
    return {
      id: `grouping:${grouping.id}`,
      kind: 'grouping' as const,
      label: grouping.name,
      color: grouping.color,
      sessionRefs,
    }
  })
  return [...sessionEntities, ...groupingEntities]
}

function mergeTrackMatches(tracks: TrackRecord[], matches: SessionTrackMatchRecord[] | null) {
  if (matches === null) {
    return tracks
  }
  const matchesByTrack = new Map<string, SessionTrackMatchRecord[]>()
  for (const match of matches) {
    const trackMatches = matchesByTrack.get(match.trackId) ?? []
    trackMatches.push(match)
    matchesByTrack.set(match.trackId, trackMatches)
  }
  return tracks.map((track) => ({
    ...track,
    matchSummaries: matchesByTrack.get(track.id) ?? [],
  }))
}

function signalResponsesToTimeMap(responses: SignalQueryResponse[], warnings: string[]) {
  const out: Record<string, number[]> = {}
  for (const response of responses) {
    for (const session of response.sessions) {
      const key = sessionRefId(session.sessionRef)
      if (!session.time) {
        warnings.push(`${session.sessionRef.label || key}: signal payload has no time column; sector mode is unavailable.`)
        out[key] = []
        continue
      }
      out[key] = numericValues(session.time.values)
    }
  }
  return out
}

function signalResponsesToMap(responses: SignalQueryResponse[], warnings: string[]) {
  const out: Record<string, Record<string, number[]>> = {}
  for (const response of responses) {
    for (const session of response.sessions) {
      const key = sessionRefId(session.sessionRef)
      if (!session.sampling.distributionCorrect) {
        warnings.push(`${session.sessionRef.label || key}: signal payload is not distribution-correct.`)
      }
      out[key] = out[key] ?? {}
      for (const signal of session.signals) {
        out[key][signal.role] = numericValues(signal.values)
      }
    }
  }
  return out
}

function entitySignalValues(entity: VisualizationEntity, data: VisualizationData, role: string) {
  return entity.sessionRefs.flatMap((sessionRef) => data.signalsBySession[sessionRefId(sessionRef)]?.[role] ?? [])
}

function entityRows(entity: VisualizationEntity, rows: TableQueryRow[]) {
  const refs = new Set(entity.sessionRefs.map(sessionRefId))
  return rows.filter((row) => refs.has(sessionRefId(row.sessionRef)))
}

function panelHistogramYMax(
  entities: VisualizationEntity[],
  data: VisualizationData,
  roles: string[],
  xDomain: [number, number],
  bins: number,
) {
  let yMax = 0
  for (const entity of entities) {
    for (const role of roles) {
      for (const bin of histogramBins(entitySignalValues(entity, data, role), xDomain, bins)) {
        yMax = Math.max(yMax, bin.proportion)
      }
    }
  }
  return yMax || 1
}

function histogramBins(values: number[], xDomain: [number, number], bins: number) {
  const clean = values.filter((value) => Number.isFinite(value) && value >= xDomain[0] && value <= xDomain[1])
  const generator = d3.bin().domain(xDomain).thresholds(bins)
  return generator(clean).map((bin) => ({
    x0: bin.x0 ?? xDomain[0],
    x1: bin.x1 ?? xDomain[1],
    proportion: clean.length ? bin.length / clean.length : 0,
  }))
}

function scatterPanelExtent(
  entities: VisualizationEntity[],
  data: VisualizationData,
  eventType: string,
  xMetric: string,
  yMetric: string,
) {
  const points = entities.flatMap((entity) => scatterPoints(entityRows(entity, data.metrics), eventType, xMetric, yMetric))
  return {
    x: paddedExtent(points.map((point) => point.x), [0, 100]),
    y: paddedExtent(points.map((point) => point.y), [-1500, 1500]),
  }
}

function scatterPoints(rows: TableQueryRow[], eventType: string, xMetric: string, yMetric: string) {
  return rows
    .filter((row) => eventTypeMatches(row.eventType, eventType))
    .map((row) => ({
      x: numericField(row.fields[xMetric]),
      y: numericField(row.fields[yMetric]),
      role: row.signalRole,
    }))
    .filter((point): point is { x: number; y: number; role: 'front' | 'rear' | 'unknown' } =>
      Number.isFinite(point.x) && Number.isFinite(point.y),
    )
}

function trackSectors(track: TrackRecord): TrackSector[] {
  const points = [...track.trackpoints].sort((a, b) => a.stationM - b.stationM)
  const sectors: TrackSector[] = []
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index]
    const end = points[index + 1]
    sectors.push({
      id: `${start.id}:${end.id}`,
      label: `${start.name} to ${end.name}`,
      order: index,
      startTrackpoint: start,
      endTrackpoint: end,
      lengthM: Math.max(0, end.stationM - start.stationM),
    })
  }
  return sectors
}

function sectorHistogramYMax(
  entities: VisualizationEntity[],
  data: VisualizationData,
  track: TrackRecord,
  sectors: TrackSector[],
  roles: string[],
  xDomain: [number, number],
  bins: number,
) {
  let yMax = 0
  for (const entity of entities) {
    for (const sector of sectors) {
      for (const role of roles) {
        const values = sectorValuesForEntity(entity, data, track, sector, role)
        for (const bin of histogramBins(values, xDomain, bins)) {
          yMax = Math.max(yMax, bin.proportion)
        }
      }
    }
  }
  return yMax || 1
}

function sectorValuesForEntity(
  entity: VisualizationEntity,
  data: VisualizationData,
  track: TrackRecord,
  sector: TrackSector,
  role: string,
) {
  return entity.sessionRefs.flatMap((sessionRef) => sectorValuesForSession(sessionRef, data, track, sector, role))
}

function entityHasSectorIntervals(entity: VisualizationEntity, track: TrackRecord, sectors: TrackSector[]) {
  return entity.sessionRefs.some((sessionRef) =>
    sectors.some((sector) => Boolean(sectorTimeInterval(track, sessionRef, sector))),
  )
}

function entityHasSectorSamples(
  entity: VisualizationEntity,
  data: VisualizationData,
  track: TrackRecord,
  sectors: TrackSector[],
  roles: string[],
) {
  return sectors.some((sector) =>
    roles.some((role) => sectorValuesForEntity(entity, data, track, sector, role).length > 0),
  )
}

function sectorValuesForSession(
  sessionRef: StudySessionRef,
  data: VisualizationData,
  track: TrackRecord,
  sector: TrackSector,
  role: string,
) {
  const key = sessionRefId(sessionRef)
  const values = data.signalsBySession[key]?.[role] ?? []
  const times = data.timeBySession[key] ?? []
  if (values.length === 0 || times.length === 0) {
    return []
  }
  const interval = sectorTimeInterval(track, sessionRef, sector)
  if (!interval) {
    return []
  }
  const endInclusive = isLastSector(track, sector)
  const limit = Math.min(values.length, times.length)
  return bestSectorValues(times, values, limit, interval, endInclusive)
}

function bestSectorValues(
  times: number[],
  values: number[],
  limit: number,
  interval: { startS: number; endS: number },
  endInclusive: boolean,
) {
  const firstFiniteTime = times.find((time) => Number.isFinite(time))
  const rawOffset = typeof firstFiniteTime === 'number' && Number.isFinite(firstFiniteTime) ? firstFiniteTime : 0
  const candidates = [1, 1 / 1000, 1 / 1_000_000, 1 / 1_000_000_000].flatMap((scale) => [
    { scale, offsetS: 0 },
    { scale, offsetS: rawOffset * scale },
  ])
  let best: number[] = []
  for (const candidate of candidates) {
    const collected = collectSectorValues(times, values, limit, interval, endInclusive, candidate.scale, candidate.offsetS)
    if (collected.length > best.length) {
      best = collected
    }
  }
  return best
}

function collectSectorValues(
  times: number[],
  values: number[],
  limit: number,
  interval: { startS: number; endS: number },
  endInclusive: boolean,
  timeScale: number,
  timeOffsetS: number,
) {
  const out: number[] = []
  for (let index = 0; index < limit; index += 1) {
    const time = times[index]
    const value = values[index]
    if (!Number.isFinite(time) || !Number.isFinite(value)) {
      continue
    }
    const relativeTime = time * timeScale - timeOffsetS
    const inSector = relativeTime >= interval.startS && (endInclusive ? relativeTime <= interval.endS : relativeTime < interval.endS)
    if (inSector) {
      out.push(value)
    }
  }
  return out
}

function sectorTimeInterval(track: TrackRecord, sessionRef: StudySessionRef, sector: TrackSector) {
  const match = trackMatchForSession(track, sessionRef)
  if (!match || !['matched', 'partial', 'ambiguous'].includes(match.status)) {
    return null
  }
  const start = crossingTime(match, sector.startTrackpoint.id)
  const end = crossingTime(match, sector.endTrackpoint.id)
  if (start === null || end === null || start === end) {
    return null
  }
  return {
    startS: Math.min(start, end),
    endS: Math.max(start, end),
  }
}

function trackMatchForSession(track: TrackRecord, sessionRef: StudySessionRef) {
  const key = sessionRefId(sessionRef)
  return track.matchSummaries.find((match) => match.sessionRefId === key) ?? null
}

function crossingTime(match: NonNullable<ReturnType<typeof trackMatchForSession>>, trackpointId: string) {
  const result = match.trackpointResults.find((item) => item.trackpointId === trackpointId)
  return result?.crossed && typeof result.crossingTimeS === 'number' && Number.isFinite(result.crossingTimeS)
    ? result.crossingTimeS
    : null
}

function isLastSector(track: TrackRecord, sector: TrackSector) {
  const sectors = trackSectors(track)
  return sectors[sectors.length - 1]?.id === sector.id
}

type LinearRegressionFit = {
  role: 'front' | 'rear'
  slope: number
  intercept: number
  rSquared: number
  x0: number
  x1: number
  y0: number
  y1: number
}

type SeriesRegressionFit = {
  id: string
  label: string
  color: string
  slope: number
  intercept: number
  rSquared: number
  x0: number
  x1: number
  y0: number
  y1: number
}

type RegressionStats = Omit<LinearRegressionFit, 'role'>

function roleRegressions(
  points: Array<{ x: number; y: number; role: 'front' | 'rear' | 'unknown' }>,
  xDomain: [number, number],
): LinearRegressionFit[] {
  return (['front', 'rear'] as const)
    .map((role) => linearRegression(points.filter((point) => point.role === role), role, xDomain))
    .filter((fit): fit is LinearRegressionFit => Boolean(fit))
}

function seriesRegressions(
  series: Array<{ id: string; label: string; color: string; points: Array<{ x: number; y: number }> }>,
  xDomain: [number, number],
): SeriesRegressionFit[] {
  return series
    .map((item) => {
      const stats = linearRegressionStats(item.points, xDomain)
      return stats ? { id: item.id, label: item.label, color: item.color, ...stats } : null
    })
    .filter((fit): fit is SeriesRegressionFit => Boolean(fit))
}

function linearRegression(
  points: Array<{ x: number; y: number }>,
  role: 'front' | 'rear',
  xDomain: [number, number],
): LinearRegressionFit | null {
  const stats = linearRegressionStats(points, xDomain)
  return stats ? { role, ...stats } : null
}

function linearRegressionStats(points: Array<{ x: number; y: number }>, xDomain: [number, number]): RegressionStats | null {
  if (points.length < 2) {
    return null
  }
  const meanX = d3.mean(points, (point) => point.x)
  const meanY = d3.mean(points, (point) => point.y)
  if (meanX === undefined || meanY === undefined) {
    return null
  }
  let numerator = 0
  let denominator = 0
  for (const point of points) {
    const dx = point.x - meanX
    numerator += dx * (point.y - meanY)
    denominator += dx * dx
  }
  if (denominator === 0) {
    return null
  }
  const slope = numerator / denominator
  const intercept = meanY - slope * meanX
  let residualSum = 0
  let totalSum = 0
  for (const point of points) {
    const predicted = slope * point.x + intercept
    residualSum += (point.y - predicted) ** 2
    totalSum += (point.y - meanY) ** 2
  }
  const rSquared = totalSum === 0 ? 1 : Math.max(0, Math.min(1, 1 - residualSum / totalSum))
  const roleXExtent = paddedExtent(points.map((point) => point.x), xDomain)
  const x0 = Math.max(xDomain[0], roleXExtent[0])
  const x1 = Math.min(xDomain[1], roleXExtent[1])
  return {
    slope,
    intercept,
    rSquared,
    x0,
    x1,
    y0: slope * x0 + intercept,
    y1: slope * x1 + intercept,
  }
}

function eventCounts(rows: TableQueryRow[]) {
  const counts = new Map<string, { eventType: string; front: number; rear: number; unknown: number }>()
  for (const row of rows) {
    const key = row.eventType || row.setId || 'unknown'
    const current = counts.get(key) ?? { eventType: key, front: 0, rear: 0, unknown: 0 }
    current[row.signalRole] += 1
    counts.set(key, current)
  }
  return Array.from(counts.values()).sort((a, b) => a.eventType.localeCompare(b.eventType))
}

function uniqueSessionRefs(refs: StudySessionRef[]) {
  const seen = new Set<string>()
  const out: StudySessionRef[] = []
  for (const ref of refs) {
    const key = sessionRefId(ref)
    if (!seen.has(key)) {
      seen.add(key)
      out.push(ref)
    }
  }
  return out
}

function groupRefsByLibrary(refs: StudySessionRef[]) {
  const out = new Map<string, StudySessionRef[]>()
  for (const ref of refs) {
    out.set(ref.libraryId, [...(out.get(ref.libraryId) ?? []), ref])
  }
  return out
}

function distributionStats(values: number[]) {
  const clean = [...values].filter(Number.isFinite).sort((a, b) => a - b)
  return {
    median: quantile(clean, 0.5),
    p95: quantile(clean, 0.95),
    max: clean.length ? clean[clean.length - 1] : null,
  }
}

function quantile(values: number[], q: number) {
  if (values.length === 0) {
    return null
  }
  return d3.quantileSorted(values, q) ?? null
}

function paddedExtent(values: number[], fallback: [number, number]): [number, number] {
  const clean = values.filter(Number.isFinite)
  if (clean.length === 0) {
    return fallback
  }
  const min = Math.min(...clean)
  const max = Math.max(...clean)
  if (min === max) {
    const span = Math.abs(min) || 1
    return [min - span * 0.5, max + span * 0.5]
  }
  const pad = (max - min) * 0.08
  return [min - pad, max + pad]
}

function numericValues(values: Array<number | null>) {
  return values.map((value) => (typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN))
}

function numericField(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : Number.NaN
}

function roleColor(role: 'front' | 'rear' | 'unknown') {
  if (role === 'front') {
    return FRONT_COLOR
  }
  if (role === 'rear') {
    return REAR_COLOR
  }
  return UNKNOWN_COLOR
}

function entityColor(entity: VisualizationEntity, index: number) {
  return entity.color || d3.schemeTableau10[index % d3.schemeTableau10.length] || UNKNOWN_COLOR
}

function eventTypeMatches(value: string, target: string) {
  return value === target || value.startsWith(`${target}_`) || value.startsWith(`${target}>`)
}

function stableStudySetKey(studySet: StudySet) {
  return JSON.stringify({
    id: studySet.id,
    revision: studySet.revision,
    sessions: studySet.sessions.map(sessionRefId),
    groupings: studySet.groupings.map((grouping) => [grouping.id, grouping.sessionRefs]),
    trackIds: studySet.trackIds,
  })
}

function stableTrackMatchKey(studySet: StudySet) {
  return JSON.stringify({
    sessions: studySet.sessions.map((sessionRef) => ({
      libraryId: sessionRef.libraryId,
      sessionKey: sessionRef.sessionKey,
      runId: sessionRef.runId,
      sessionId: sessionRef.sessionId,
    })),
    trackIds: studySet.trackIds,
  })
}

function warningMessage(warning: Record<string, unknown>) {
  const message = typeof warning.message === 'string' ? warning.message : JSON.stringify(warning)
  const role = typeof warning.role === 'string' ? `${warning.role}: ` : ''
  const session = typeof warning.session_key === 'string' ? `${warning.session_key} ` : ''
  return `${session}${role}${message}`
}

function formatPercent(value: number | null) {
  return value === null ? '-' : `${(value * 100).toFixed(0)}%`
}

function formatAxis(value: number) {
  if (Math.abs(value) >= 1000) {
    return `${Math.round(value)}`
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

function formatMetres(value: number) {
  if (!Number.isFinite(value)) {
    return '-'
  }
  return value >= 1000 ? `${(value / 1000).toFixed(2)} km` : `${value.toFixed(0)} m`
}

function formatRole(role: 'front' | 'rear' | 'unknown') {
  return role.charAt(0).toUpperCase() + role.slice(1)
}

function formatSlope(value: number) {
  if (Math.abs(value) >= 100) {
    return value.toFixed(1)
  }
  if (Math.abs(value) >= 10) {
    return value.toFixed(2)
  }
  return value.toFixed(3)
}

function formatIntercept(value: number) {
  const sign = value < 0 ? '-' : '+'
  const magnitude = Math.abs(value)
  const formatted = magnitude >= 100 ? magnitude.toFixed(0) : magnitude >= 10 ? magnitude.toFixed(1) : magnitude.toFixed(2)
  return `${sign} ${formatted}`
}
