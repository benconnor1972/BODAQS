import { useDeferredValue, useEffect, useMemo, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react'
import * as d3 from 'd3'
import { Activity, ChevronDown, ChevronUp } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionByRef, sessionRefId } from '../domain/studySets'
import type {
  SessionRecord,
  SignalQuerySignalRequest,
  SessionTrackMatchRecord,
  StudySessionRef,
  StudySet,
  TableQueryRow,
  TrackRecord,
  TrackpointRecord,
} from '../domain/types'
import { InfoTip } from './Common'

const FRONT_COLOR = '#008c95'
const REAR_COLOR = '#101820'
const UNKNOWN_COLOR = '#8b9793'
const ENTITY_SERIES_COLORS = ['#008c95', '#101820', '#4f7477', '#6faeaa', '#6f7b80', '#b88a43', '#2d5f64', '#9aa7a3']
const COMPRESSION_EVENT_TYPE = 'compressions_all'
const REBOUND_EVENT_TYPE = 'rebounds_all'
const SCATTER_X_METRIC = 'm_stroke_disp_max'
const STROKE_LENGTH_METRIC = 'm_stroke_disp_range'
const COMPRESSION_Y_METRIC = 'm_interval_vel_max'
const REBOUND_Y_METRIC = 'm_interval_vel_min'
const VELOCITY_METRIC_SPEC = { compressionMetricName: COMPRESSION_Y_METRIC, reboundMetricName: REBOUND_Y_METRIC }
const STROKE_LENGTH_METRIC_SPEC = { compressionMetricName: STROKE_LENGTH_METRIC, reboundMetricName: STROKE_LENGTH_METRIC }
const VELOCITY_DOMAIN_LIMITS = [1000, 2000, 5000, 10000]
const STROKE_LENGTH_DOMAIN_LIMITS = [100, 150, 200, 250]
const WHOLE_SESSION_DISTRIBUTION_BINS = 20
const SECTOR_DISTRIBUTION_BINS = 15
const VELOCITY_STATS_FORMATTER = formatMetricValueWithUnit('mm/s')
const STROKE_LENGTH_STATS_FORMATTER = formatMetricValueWithUnit('mm')

const SIGNAL_REQUESTS: SignalQuerySignalRequest[] = [
  { role: 'front_displacement', selector: { end: 'front', quantity: 'disp_norm', unit: '1' } },
  { role: 'rear_displacement', selector: { end: 'rear', quantity: 'disp_norm', unit: '1' } },
  { role: 'activity_mask', selector: { kind: 'qc', quantity: 'mask' } },
]
const ACTIVITY_SIGNAL_ROLES = new Set(['activity_mask', 'inactive_mask_qc', 'inactive_mask', 'active_mask_qc'])
const INACTIVE_MASK_ROLES = ['inactive_mask_qc', 'inactive_mask']
const ACTIVE_MASK_ROLES = ['active_mask_qc']

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
  eventTriggerTimeByKey: Record<string, number>
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
type SuspensionEnd = 'front' | 'rear'
type DistributionChartKind = 'histogram' | 'mirrored_velocity'
type DistributionStatsMode = 'basic' | 'displacement'
type MirroredMetricSpec = { compressionMetricName: string; reboundMetricName: string }
type TimeWindow = { startS: number; endS: number }
type TimeWindowsBySession = Record<string, TimeWindow>

type SuspensionVisualizationSettings = {
  selectedEntityIds: string[]
  knownSessionEntityIds: string[]
  collapsedPanels: string[]
  comparisonLayout: ComparisonLayout
  scopeMode: ScopeMode
  selectedTrackId: string | null
  selectedEnds: SuspensionEnd[]
  selectedSectorIds: string[]
  timeWindowsBySession: TimeWindowsBySession
  excludeInactivePeriods: boolean
}

type CachedSessionVisualizationData = {
  sessionRef: StudySessionRef
  time: number[]
  signals: Record<string, number[]>
  events: TableQueryRow[]
  metrics: TableQueryRow[]
  warnings: string[]
}

type TimedTableRow = {
  row: TableQueryRow
  triggerTimeS: number
}

type HistogramBin = {
  x0: number
  x1: number
  proportion: number
  count: number
  total: number
}

type MirroredHistogramBins = {
  compression: HistogramBin[]
  rebound: HistogramBin[]
}

type ActivityInterval = {
  startS: number
  endS: number
}

type ScatterPoint = {
  x: number
  y: number
  role: 'front' | 'rear' | 'unknown'
}

type SectorInterval = {
  startS: number
  endS: number
}

const visualizationSettingsCache = new Map<string, SuspensionVisualizationSettings>()
const visualizationSessionCacheByDataSource = new WeakMap<LibraryDataSource, Map<string, CachedSessionVisualizationData>>()
const monotonicTimeArrayCache = new WeakMap<number[], boolean>()
const rowTimeIndexCache = new WeakMap<TableQueryRow[], TimedTableRow[]>()
const entitySignalValuesCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const rowSessionGroupCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const entityRowsCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const metricMirroredValueCache = new WeakMap<TableQueryRow[], Map<string, number[]>>()
const histogramBinCache = new WeakMap<number[], Map<string, HistogramBin[]>>()
const mirroredHistogramBinCache = new WeakMap<number[], Map<string, MirroredHistogramBins>>()
const scatterPointCache = new WeakMap<TableQueryRow[], Map<string, ScatterPoint[]>>()
const sectorValuesForSessionCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const sectorValuesForEntityCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const rowsInSectorsForEntityCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const percentValuesCache = new WeakMap<number[], number[]>()
const sectorIntervalCache = new WeakMap<TrackRecord, Map<string, SectorInterval | null>>()
const lastSectorIdCache = new WeakMap<TrackRecord, string | null>()
const trackObjectIdCache = new WeakMap<TrackRecord, number>()
const activeMaskCache = new WeakMap<VisualizationData, Map<string, boolean[] | null>>()
let nextTrackObjectId = 1

type TrackSector = {
  id: string
  label: string
  order: number
  startTrackpoint: TrackpointRecord
  endTrackpoint: TrackpointRecord
  lengthM: number
}

type DistributionRole = {
  key: SuspensionEnd
  label: string
  signalRole: string
  color: string
}

export function SuspensionVisualization({
  studySet,
  sessions,
  tracks,
  dataSource,
  onInspectSignals,
}: {
  studySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
  onInspectSignals?: (sessionRef: StudySessionRef, window: TimeWindow) => void
}) {
  const entities = visualizationEntities(studySet)
  const baseStudySetTracks = tracks.filter((track) => studySet.trackIds.includes(track.id))
  const [visualizationTrackMatches, setVisualizationTrackMatches] = useState<SessionTrackMatchRecord[] | null>(null)
  const [visualizationTrackMatchesLoading, setVisualizationTrackMatchesLoading] = useState(false)
  const studySetTracks = mergeTrackMatches(baseStudySetTracks, visualizationTrackMatches)
  const studySetTrackKey = studySetTracks.map((track) => `${track.id}:${track.revision}`).join('|')
  const studySetKey = stableStudySetKey(studySet)
  const trackMatchKey = stableTrackMatchKey(studySet)
  const settingsCacheKey = visualizationSettingsKey(studySet)
  const initialSettings = restoredVisualizationSettings(settingsCacheKey, entities, studySetTracks)
  const [selectedEntityIds, setSelectedEntityIds] = useState<string[]>(() =>
    initialSettings.selectedEntityIds,
  )
  const [collapsedPanels, setCollapsedPanels] = useState<string[]>(initialSettings.collapsedPanels)
  const [comparisonLayout, setComparisonLayout] = useState<ComparisonLayout>(initialSettings.comparisonLayout)
  const [scopeMode, setScopeMode] = useState<ScopeMode>(initialSettings.scopeMode)
  const [selectedTrackId, setSelectedTrackId] = useState<string | null>(() => initialSettings.selectedTrackId)
  const [selectedEnds, setSelectedEnds] = useState<SuspensionEnd[]>(initialSettings.selectedEnds)
  const [selectedSectorIds, setSelectedSectorIds] = useState<string[]>(initialSettings.selectedSectorIds)
  const [timeWindowsBySession, setTimeWindowsBySession] = useState<TimeWindowsBySession>(initialSettings.timeWindowsBySession)
  const [excludeInactivePeriods, setExcludeInactivePeriods] = useState(initialSettings.excludeInactivePeriods)
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle', message: 'Select sessions or groups to visualize.' })

  useEffect(() => {
    const restored = restoredVisualizationSettings(settingsCacheKey, visualizationEntities(studySet), studySetTracks)
    setSelectedEntityIds(restored.selectedEntityIds)
    setCollapsedPanels(restored.collapsedPanels)
    setComparisonLayout(restored.comparisonLayout)
    setScopeMode(restored.scopeMode)
    setSelectedTrackId(restored.selectedTrackId)
    setSelectedEnds(restored.selectedEnds)
    setSelectedSectorIds(restored.selectedSectorIds)
    setTimeWindowsBySession(restored.timeWindowsBySession)
    setExcludeInactivePeriods(restored.excludeInactivePeriods)
  }, [settingsCacheKey, studySetKey])

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
  const selectedTrack = studySetTracks.find((track) => track.id === selectedTrackId) ?? studySetTracks[0] ?? null
  const sectors = selectedTrack ? trackSectors(selectedTrack) : []
  const sectorKey = sectors.map((sector) => sector.id).join('|')
  const selectedSectors = sectors.filter((sector) => selectedSectorIds.includes(sector.id))
  const selectedSessionRefs = uniqueSessionRefs(selectedEntities.flatMap((entity) => entity.sessionRefs))
  const studySetSessionRefs = useMemo(() => uniqueSessionRefs(studySet.sessions), [studySetKey])
  const studySetSessionKey = studySetSessionRefs.map(sessionRefId).join('|')

  useEffect(() => {
    setSelectedSectorIds((current) => {
      const validIds = new Set(sectors.map((sector) => sector.id))
      const retained = current.filter((sectorId) => validIds.has(sectorId))
      return retained.length > 0 ? retained : sectors.map((sector) => sector.id)
    })
  }, [selectedTrack?.id, sectorKey])

  useEffect(() => {
    visualizationSettingsCache.set(settingsCacheKey, {
      selectedEntityIds,
      knownSessionEntityIds: entities.filter((entity) => entity.kind === 'session').map((entity) => entity.id),
      collapsedPanels,
      comparisonLayout,
      scopeMode,
      selectedTrackId,
      selectedEnds,
      selectedSectorIds,
      timeWindowsBySession,
      excludeInactivePeriods,
    })
  }, [
    settingsCacheKey,
    studySetKey,
    selectedEntityIds,
    collapsedPanels,
    comparisonLayout,
    scopeMode,
    selectedTrackId,
    selectedEnds,
    selectedSectorIds,
    timeWindowsBySession,
    excludeInactivePeriods,
  ])

  useEffect(() => {
    let cancelled = false
    async function loadData() {
      if (studySetSessionRefs.length === 0) {
        setLoadState({ status: 'idle', message: 'Add at least one session to visualize suspension data.' })
        return
      }
      setLoadState({ status: 'loading', message: 'Loading suspension visualization data...' })
      try {
        const data = await loadVisualizationData(studySetSessionRefs, dataSource)
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
  }, [dataSource, studySetSessionKey])

  const data = loadState.status === 'ready' ? loadState.data : null
  const deferredTimeWindowsBySession = useDeferredValue(timeWindowsBySession)
  const scopedData = useMemo(
    () => (data ? applyTimeWindows(data, deferredTimeWindowsBySession) : null),
    [data, deferredTimeWindowsBySession],
  )
  const baseAnalysisData = useMemo(
    () => (data && excludeInactivePeriods ? applyActivityMask(data) : data),
    [data, excludeInactivePeriods],
  )
  const analysisData = useMemo(
    () => (scopedData && excludeInactivePeriods ? applyActivityMask(scopedData) : scopedData),
    [scopedData, excludeInactivePeriods],
  )
  const controlsCollapsed = collapsedPanels.includes('select-filter')
  const singleEntityDashboard = selectedEntities.length === 1 && scopeMode === 'whole_session'
  const panelComparisonLayout: ComparisonLayout = singleEntityDashboard ? 'entities' : comparisonLayout
  const velocityDomain = baseAnalysisData
    ? metricMagnitudeCandidateDomain(selectedEntities, baseAnalysisData, selectedEnds, VELOCITY_METRIC_SPEC, VELOCITY_DOMAIN_LIMITS)
    : ([0, 2000] as [number, number])
  const strokeLengthDomain = baseAnalysisData
    ? metricMagnitudeCandidateDomain(selectedEntities, baseAnalysisData, selectedEnds, STROKE_LENGTH_METRIC_SPEC, STROKE_LENGTH_DOMAIN_LIMITS)
    : ([0, 100] as [number, number])

  function toggleEntity(entityId: string) {
    setSelectedEntityIds((current) =>
      current.includes(entityId) ? current.filter((id) => id !== entityId) : [...current, entityId],
    )
  }

  function toggleEnd(end: SuspensionEnd) {
    setSelectedEnds((current) =>
      current.includes(end) ? current.filter((item) => item !== end) : [...current, end],
    )
  }

  function toggleSector(sectorId: string) {
    setSelectedSectorIds((current) =>
      current.includes(sectorId) ? current.filter((id) => id !== sectorId) : [...current, sectorId],
    )
  }

  function togglePanel(panelId: string) {
    setCollapsedPanels((current) =>
      current.includes(panelId) ? current.filter((id) => id !== panelId) : [...current, panelId],
    )
  }

  function setSessionTimeWindow(sessionRef: StudySessionRef, nextWindow: TimeWindow) {
    const key = sessionRefId(sessionRef)
    setTimeWindowsBySession((current) => ({
      ...current,
      [key]: nextWindow,
    }))
  }

  function resetSessionTimeWindow(sessionRef: StudySessionRef) {
    const key = sessionRefId(sessionRef)
    setTimeWindowsBySession((current) => {
      const next = { ...current }
      delete next[key]
      return next
    })
  }

  return (
    <div className="suspension-viz">
      <header className="suspension-viz-hero">
        <div>
          <h3 className="viz-heading">
            {studySet.displayName || 'Current Study Set'}
            <InfoTip text="Simple Suspension Metrics for one or more Study Set sessions or groups. Groups combine their member sessions." />
          </h3>
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

      <section className={`viz-control-panel${controlsCollapsed ? ' collapsed' : ''}`} aria-label="Select and filter">
        <button className="viz-control-panel-header" type="button" onClick={() => togglePanel('select-filter')}>
          <span>
            <strong>
              Select and Filter
              <InfoTip text="Choose which sessions, groups, ends, sectors, scope, layout, and time windows are shown in this analysis view. Study Set membership is not changed." />
            </strong>
            <small>
              {selectedEntityIds.length} sessions/groups, {selectedEnds.length} ends, {selectedSectors.length} sectors
            </small>
          </span>
          {controlsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!controlsCollapsed && (
          <div className="viz-control-panel-body">
            <VisualizationFilterChips
              entities={entities}
              scopeMode={scopeMode}
              sectors={sectors}
              selectedEndKeys={selectedEnds}
              selectedEntityIds={selectedEntityIds}
              selectedSectorIds={selectedSectorIds}
              onToggleEnd={toggleEnd}
              onToggleEntity={toggleEntity}
              onToggleSector={toggleSector}
            />

            <div className="viz-control-mode-row">
              <ScopeModeControl
                value={scopeMode}
                onChange={setScopeMode}
                tracks={studySetTracks}
                selectedTrackId={selectedTrack?.id ?? null}
                onTrackChange={setSelectedTrackId}
                sectors={sectors}
              />

              <ComparisonLayoutToggle value={comparisonLayout} onChange={setComparisonLayout} />

              <ActivityExclusionControl checked={excludeInactivePeriods} onChange={setExcludeInactivePeriods} />
            </div>

            {data && selectedSessionRefs.length > 0 && (
              <TimeWindowManager
                data={data}
                sessionRefs={selectedSessionRefs}
                sessions={sessions}
                timeWindows={timeWindowsBySession}
                onChange={setSessionTimeWindow}
                onReset={resetSessionTimeWindow}
                onResetAll={() => setTimeWindowsBySession({})}
                onInspectSignals={onInspectSignals}
              />
            )}
          </div>
        )}
      </section>

      {loadState.status === 'loading' && <div className="viz-status">{loadState.message}</div>}
      {loadState.status === 'error' && <div className="viz-status warning">Could not load visualization data: {loadState.message}</div>}
      {loadState.status === 'idle' && <div className="viz-status">{loadState.message}</div>}

      {data && data.warnings.length > 0 && (
        <div className="viz-status warning">
          {data.warnings.slice(0, 3).map((warning) => String(warning)).join(' | ')}
          {data.warnings.length > 3 ? ` | ${data.warnings.length - 3} more warning(s)` : ''}
        </div>
      )}

      {data && analysisData && baseAnalysisData && (
        <div className={`viz-panel-stack${singleEntityDashboard ? ' single-entity-dashboard' : ''}`}>
          <VisualizationPanel
            id="displacement"
            title="Wheel displacement distribution"
            subtitle="Wheel displacement, % of maximum travel, frequency distribution."
            collapsed={collapsedPanels.includes('displacement')}
            onToggle={() => togglePanel('displacement')}
          >
            {scopeMode === 'sector' ? (
              <SectorDistributionScaffold
                quantity="displacement"
                layout={comparisonLayout}
                entities={selectedEntities}
                ends={selectedEnds}
                data={analysisData}
                scaleData={baseAnalysisData}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                frontRole="front_displacement"
                rearRole="rear_displacement"
                xDomain={[0, 100]}
                xLabel="wheel displacement, % of max"
                bins={SECTOR_DISTRIBUTION_BINS}
                trackMatchesLoading={visualizationTrackMatchesLoading}
                valueTransform={percentValues}
                statsMode="displacement"
              />
            ) : (
              <DistributionGrid
                chartKind="histogram"
                layout={panelComparisonLayout}
                entities={selectedEntities}
                roles={distributionRoles('front_displacement', 'rear_displacement', selectedEnds)}
                xDomain={[0, 100]}
                xLabel="wheel displacement, % of max"
                bins={WHOLE_SESSION_DISTRIBUTION_BINS}
                yMax={distributionYMax(
                  selectedEntities,
                  distributionRoles('front_displacement', 'rear_displacement', selectedEnds),
                  (entity, role) => percentValues(entitySignalValues(entity, baseAnalysisData, role.signalRole)),
                  [0, 100],
                  WHOLE_SESSION_DISTRIBUTION_BINS,
                  'histogram',
                )}
                sessions={sessions}
                showStats
                statsMode="displacement"
                statsFormatter={formatPercentValue}
                valueForEntityRole={(entity, role) => percentValues(entitySignalValues(entity, analysisData, role.signalRole))}
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="velocity"
            title="Wheel velocity distribution"
            subtitle="Maximum vertical stroke velocity at the wheel, compression above the axis, rebound below the axis, frequency distribution."
            collapsed={collapsedPanels.includes('velocity')}
            onToggle={() => togglePanel('velocity')}
          >
            {scopeMode === 'sector' ? (
              <SectorMetricDistributionScaffold
                data={analysisData}
                scaleData={baseAnalysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={comparisonLayout}
                metricSpec={VELOCITY_METRIC_SPEC}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xLabel="stroke maximum wheel velocity (mm/s)"
                bins={SECTOR_DISTRIBUTION_BINS}
                domainCandidates={VELOCITY_DOMAIN_LIMITS}
                statsFormatter={VELOCITY_STATS_FORMATTER}
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <DistributionGrid
                chartKind="mirrored_velocity"
                layout={panelComparisonLayout}
                entities={selectedEntities}
                roles={distributionRoles('', '', selectedEnds)}
                xDomain={velocityDomain}
                xLabel="stroke maximum wheel velocity (mm/s)"
                bins={WHOLE_SESSION_DISTRIBUTION_BINS}
                yMax={distributionYMax(
                  selectedEntities,
                  distributionRoles('', '', selectedEnds),
                  (entity, role) => metricMirroredValuesForEntityEnd(entity, baseAnalysisData, role.key, VELOCITY_METRIC_SPEC),
                  velocityDomain,
                  WHOLE_SESSION_DISTRIBUTION_BINS,
                  'mirrored_velocity',
                )}
                sessions={sessions}
                showStats
                statsFormatter={VELOCITY_STATS_FORMATTER}
                statsTransform={Math.abs}
                valueForEntityRole={(entity, role) => metricMirroredValuesForEntityEnd(entity, analysisData, role.key, VELOCITY_METRIC_SPEC)}
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="stroke-length"
            title="Wheel stroke length distribution"
            subtitle="Vertical stroke length at the wheel, compression above the axis, rebound below the axis, frequency distribution."
            collapsed={collapsedPanels.includes('stroke-length')}
            onToggle={() => togglePanel('stroke-length')}
          >
            {scopeMode === 'sector' ? (
              <SectorMetricDistributionScaffold
                data={analysisData}
                scaleData={baseAnalysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={comparisonLayout}
                metricSpec={STROKE_LENGTH_METRIC_SPEC}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xLabel="wheel stroke length (mm)"
                bins={SECTOR_DISTRIBUTION_BINS}
                domainCandidates={STROKE_LENGTH_DOMAIN_LIMITS}
                statsFormatter={STROKE_LENGTH_STATS_FORMATTER}
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <DistributionGrid
                chartKind="mirrored_velocity"
                layout={panelComparisonLayout}
                entities={selectedEntities}
                roles={distributionRoles('', '', selectedEnds)}
                xDomain={strokeLengthDomain}
                xLabel="wheel stroke length (mm)"
                bins={WHOLE_SESSION_DISTRIBUTION_BINS}
                yMax={distributionYMax(
                  selectedEntities,
                  distributionRoles('', '', selectedEnds),
                  (entity, role) => metricMirroredValuesForEntityEnd(entity, baseAnalysisData, role.key, STROKE_LENGTH_METRIC_SPEC),
                  strokeLengthDomain,
                  WHOLE_SESSION_DISTRIBUTION_BINS,
                  'mirrored_velocity',
                )}
                sessions={sessions}
                showStats
                statsFormatter={STROKE_LENGTH_STATS_FORMATTER}
                statsTransform={Math.abs}
                valueForEntityRole={(entity, role) => metricMirroredValuesForEntityEnd(entity, analysisData, role.key, STROKE_LENGTH_METRIC_SPEC)}
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="compression"
            title="Compression metrics"
            subtitle="Compression stroke maximum displacement vs maximum velocity, at the wheel, front/rear on one chart."
            collapsed={collapsedPanels.includes('compression')}
            onToggle={() => togglePanel('compression')}
          >
            {scopeMode === 'sector' ? (
              <SectorScatterScaffold
                data={analysisData}
                ends={selectedEnds}
                entities={selectedEntities}
                eventType={COMPRESSION_EVENT_TYPE}
                layout={comparisonLayout}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xMetric={SCATTER_X_METRIC}
                yMetric={COMPRESSION_Y_METRIC}
                yLabel="Compression velocity (mm/s)"
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <ScatterEntityStrip
                layout={panelComparisonLayout}
                entities={selectedEntities}
                data={analysisData}
                eventType={COMPRESSION_EVENT_TYPE}
                xMetric={SCATTER_X_METRIC}
                yMetric={COMPRESSION_Y_METRIC}
                yLabel="Compression velocity (mm/s)"
                ends={selectedEnds}
                showRegression
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="rebound"
            title="Rebound metrics"
            subtitle="Compression stroke maximum displacement vs maximum (negative) velocity, at the wheel, front/rear on one chart."
            collapsed={collapsedPanels.includes('rebound')}
            onToggle={() => togglePanel('rebound')}
          >
            {scopeMode === 'sector' ? (
              <SectorScatterScaffold
                data={analysisData}
                ends={selectedEnds}
                entities={selectedEntities}
                eventType={REBOUND_EVENT_TYPE}
                layout={comparisonLayout}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xMetric={SCATTER_X_METRIC}
                yMetric={REBOUND_Y_METRIC}
                yLabel="Rebound velocity (mm/s)"
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <ScatterEntityStrip
                layout={panelComparisonLayout}
                entities={selectedEntities}
                data={analysisData}
                eventType={REBOUND_EVENT_TYPE}
                xMetric={SCATTER_X_METRIC}
                yMetric={REBOUND_Y_METRIC}
                yLabel="Rebound velocity (mm/s)"
                ends={selectedEnds}
                showRegression
              />
            )}
          </VisualizationPanel>

          <VisualizationPanel
            id="events"
            title="Event counts"
            subtitle="Counts of detected events by event type."
            collapsed={collapsedPanels.includes('events')}
            onToggle={() => togglePanel('events')}
          >
            {scopeMode === 'sector' ? (
              <SectorEventCountScaffold
                data={analysisData}
                ends={selectedEnds}
                entities={selectedEntities}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <EventCountStrip entities={selectedEntities} data={analysisData} ends={selectedEnds} />
            )}
          </VisualizationPanel>
        </div>
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
    <div className="viz-layout-toggle" aria-label="Comparison layout">
      <div className="viz-layout-buttons">
        <button
          className={value === 'entities' ? 'active' : ''}
          type="button"
          onClick={() => onChange('entities')}
        >
          Session vs session
          <small>Front/rear together</small>
        </button>
        <button
          className={value === 'ends' ? 'active' : ''}
          type="button"
          onClick={() => onChange('ends')}
        >
          Front vs rear
          <small>Sessions/groups together</small>
        </button>
      </div>
    </div>
  )
}

function ActivityExclusionControl({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="viz-activity-toggle">
      <input checked={checked} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      <span>
        <strong>Exclude inactive periods</strong>
        <small>Uses preprocessing activity masks when available.</small>
      </span>
    </label>
  )
}

function TimeWindowManager({
  data,
  sessionRefs,
  sessions,
  timeWindows,
  onChange,
  onReset,
  onResetAll,
  onInspectSignals,
}: {
  data: VisualizationData
  sessionRefs: StudySessionRef[]
  sessions: SessionRecord[]
  timeWindows: TimeWindowsBySession
  onChange: (sessionRef: StudySessionRef, window: TimeWindow) => void
  onReset: (sessionRef: StudySessionRef) => void
  onResetAll: () => void
  onInspectSignals?: (sessionRef: StudySessionRef, window: TimeWindow) => void
}) {
  const sessionKey = sessionRefs.map(sessionRefId).join('|')
  const [activeSessionKey, setActiveSessionKey] = useState<string | null>(() =>
    sessionRefs[0] ? sessionRefId(sessionRefs[0]) : null,
  )

  useEffect(() => {
    setActiveSessionKey((current) => {
      if (current && sessionRefs.some((sessionRef) => sessionRefId(sessionRef) === current)) {
        return current
      }
      return sessionRefs[0] ? sessionRefId(sessionRefs[0]) : null
    })
  }, [sessionKey])

  const activeSessionRef =
    sessionRefs.find((sessionRef) => sessionRefId(sessionRef) === activeSessionKey) ?? sessionRefs[0] ?? null
  const clippedCount = sessionRefs.filter((sessionRef) => Boolean(timeWindows[sessionRefId(sessionRef)])).length

  if (!activeSessionRef) {
    return null
  }

  return (
    <section className="viz-time-window-manager" aria-label="Per-session time windows">
      <div className="viz-time-window-manager-header">
        <div>
          <strong>Time windows</strong>
          <span>
            {clippedCount === 0
              ? `${sessionRefs.length} selected session(s), all full length`
              : `${clippedCount} of ${sessionRefs.length} selected session(s) clipped`}
          </span>
        </div>
        <button type="button" onClick={onResetAll} disabled={clippedCount === 0}>
          Reset all
        </button>
      </div>

      <div className="viz-time-window-session-list">
        {sessionRefs.map((sessionRef) => {
          const key = sessionRefId(sessionRef)
          const session = sessionByRef(sessionRef, sessions) ?? null
          const window = timeWindows[key] ?? null
          return (
            <button
              className={`viz-time-window-session-chip${key === sessionRefId(activeSessionRef) ? ' selected' : ''}${window ? ' clipped' : ''}`}
              key={key}
              type="button"
              onClick={() => setActiveSessionKey(key)}
            >
              <span>{sessionRef.label || session?.name || sessionRef.sessionId}</span>
              <small>{window ? `${formatTimeOffset(window.startS)} - ${formatTimeOffset(window.endS)}` : 'Full session'}</small>
            </button>
          )
        })}
      </div>

      <TimeWindowNavigator
        embedded
        data={data}
        sessionRef={activeSessionRef}
        session={sessionByRef(activeSessionRef, sessions) ?? null}
        window={timeWindows[sessionRefId(activeSessionRef)] ?? null}
        onChange={(nextWindow) => onChange(activeSessionRef, nextWindow)}
        onReset={() => onReset(activeSessionRef)}
        onInspectSignals={onInspectSignals ? (window) => onInspectSignals(activeSessionRef, window) : undefined}
      />
    </section>
  )
}

function TimeWindowNavigator({
  embedded = false,
  data,
  sessionRef,
  session,
  window,
  onChange,
  onReset,
  onInspectSignals,
}: {
  embedded?: boolean
  data: VisualizationData
  sessionRef: StudySessionRef
  session: SessionRecord | null
  window: TimeWindow | null
  onChange: (window: TimeWindow) => void
  onReset: () => void
  onInspectSignals?: (window: TimeWindow) => void
}) {
  const durationS = sessionDurationS(data, sessionRef, session)
  const disabled = durationS <= 0
  const minWindowS = Math.max(0.1, durationS / 500)
  const current = sanitizeTimeWindow(window ?? { startS: 0, endS: durationS }, durationS, minWindowS)
  const [draftWindow, setDraftWindow] = useState<TimeWindow>(current)
  const active = Boolean(window)

  useEffect(() => {
    setDraftWindow(current)
  }, [current.startS, current.endS, sessionRef.sessionKey])

  function commitDraftWindow(nextDraftWindow = draftWindow) {
    const nextWindow = sanitizeTimeWindow(nextDraftWindow, durationS, minWindowS)
    setDraftWindow(nextWindow)
    if (nextWindow.startS !== current.startS || nextWindow.endS !== current.endS) {
      onChange(nextWindow)
    }
  }

  return (
    <section className={`viz-time-window${embedded ? ' embedded' : ''}`} aria-label="Time window navigator">
      <div className="viz-time-window-header">
        <div>
          <strong>Time window</strong>
          <span>
            {sessionRef.label || session?.name || sessionRef.sessionId}: {active ? 'clipped view' : 'full session'}
          </span>
        </div>
        <div className="viz-time-window-actions">
          {onInspectSignals && (
            <button type="button" onClick={() => onInspectSignals(draftWindow)} disabled={disabled}>
              <Activity size={13} />
              Inspect signals
            </button>
          )}
          <button type="button" onClick={onReset} disabled={!active || disabled}>
            Full session
          </button>
        </div>
      </div>
      {disabled ? (
        <div className="viz-time-window-empty">No usable signal timebase is available for this session.</div>
      ) : (
        <>
          <TimeWindowOverview
            data={data}
            durationS={durationS}
            minWindowS={minWindowS}
            sessionRef={sessionRef}
            window={draftWindow}
            onChange={(nextWindow) => setDraftWindow(sanitizeTimeWindow(nextWindow, durationS, minWindowS))}
            onCommit={commitDraftWindow}
          />
          <div className="viz-time-window-readout">
            <span>Start {formatTimeOffset(draftWindow.startS)}</span>
            <span>End {formatTimeOffset(draftWindow.endS)}</span>
          </div>
        </>
      )}
    </section>
  )
}

function TimeWindowOverview({
  data,
  durationS,
  minWindowS,
  sessionRef,
  window,
  onChange,
  onCommit,
}: {
  data: VisualizationData
  durationS: number
  minWindowS: number
  sessionRef: StudySessionRef
  window: TimeWindow
  onChange: (window: TimeWindow) => void
  onCommit: (window: TimeWindow) => void
}) {
  const width = 760
  const height = 86
  const margin = { top: 10, right: 12, bottom: 20, left: 28 }
  type DragMode = 'start' | 'end' | 'move'
  type TimeWindowDrag = {
    mode: DragMode
    pointerStartS: number
    windowStartS: number
    windowEndS: number
  }
  const [drag, setDrag] = useState<TimeWindowDrag | null>(null)
  const key = sessionRefId(sessionRef)
  const times = data.timeBySession[key] ?? []
  const signals = data.signalsBySession[key] ?? {}
  const inactiveIntervals = inactiveIntervalsForSession(data, key)
  const frontPoints = overviewPoints(times, signals.front_displacement ?? [], 520)
  const rearPoints = overviewPoints(times, signals.rear_displacement ?? [], 520)
  const x = d3.scaleLinear().domain([0, durationS || 1]).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, 1]).range([height - margin.bottom, margin.top])
  const line = d3
    .line<{ timeS: number; value: number }>()
    .x((point) => x(point.timeS))
    .y((point) => y(point.value))
    .curve(d3.curveMonotoneX)
  const frontPath = line(frontPoints)
  const rearPath = line(rearPoints)
  const selectionX = x(window.startS)
  const selectionWidth = Math.max(1, x(window.endS) - selectionX)
  const handleWidth = 5
  const empty = frontPoints.length === 0 && rearPoints.length === 0

  function pointerViewX(event: PointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    return ((event.clientX - bounds.left) / Math.max(1, bounds.width)) * width
  }

  function pointerTime(event: PointerEvent<SVGSVGElement>) {
    return clamp(x.invert(pointerViewX(event)), 0, durationS)
  }

  function dragModeAt(viewX: number): DragMode | null {
    const endX = selectionX + selectionWidth
    const handleHitWidth = 12
    if (Math.abs(viewX - selectionX) <= handleHitWidth) {
      return 'start'
    }
    if (Math.abs(viewX - endX) <= handleHitWidth) {
      return 'end'
    }
    if (viewX > selectionX && viewX < endX) {
      return 'move'
    }
    return null
  }

  function windowForPointer(event: PointerEvent<SVGSVGElement>, activeDrag: TimeWindowDrag) {
    const nextPointerS = pointerTime(event)
    if (activeDrag.mode === 'start') {
      return sanitizeTimeWindow(
        { startS: clamp(nextPointerS, 0, activeDrag.windowEndS - minWindowS), endS: activeDrag.windowEndS },
        durationS,
        minWindowS,
      )
    }
    if (activeDrag.mode === 'end') {
      return sanitizeTimeWindow(
        { startS: activeDrag.windowStartS, endS: clamp(nextPointerS, activeDrag.windowStartS + minWindowS, durationS) },
        durationS,
        minWindowS,
      )
    }
    const windowWidthS = activeDrag.windowEndS - activeDrag.windowStartS
    const deltaS = nextPointerS - activeDrag.pointerStartS
    const startS = clamp(activeDrag.windowStartS + deltaS, 0, Math.max(0, durationS - windowWidthS))
    return sanitizeTimeWindow({ startS, endS: startS + windowWidthS }, durationS, minWindowS)
  }

  function handlePointerDown(event: PointerEvent<SVGSVGElement>) {
    const mode = dragModeAt(pointerViewX(event))
    if (!mode) {
      return
    }
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    setDrag({
      mode,
      pointerStartS: pointerTime(event),
      windowStartS: window.startS,
      windowEndS: window.endS,
    })
  }

  function handlePointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!drag) {
      return
    }
    event.preventDefault()
    onChange(windowForPointer(event, drag))
  }

  function handlePointerUp(event: PointerEvent<SVGSVGElement>) {
    if (!drag) {
      return
    }
    event.preventDefault()
    const nextWindow = windowForPointer(event, drag)
    onChange(nextWindow)
    onCommit(nextWindow)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setDrag(null)
  }

  function handlePointerCancel(event: PointerEvent<SVGSVGElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    setDrag(null)
  }

  return (
    <svg
      className={`viz-time-window-overview${drag ? ' dragging' : ''}`}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Session displacement overview"
      onPointerCancel={handlePointerCancel}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      {inactiveIntervals.map((interval, index) => (
        <rect
          className="viz-time-window-inactive"
          height={height - margin.top - margin.bottom}
          key={`${interval.startS}-${interval.endS}-${index}`}
          width={Math.max(1, x(clamp(interval.endS, 0, durationS)) - x(clamp(interval.startS, 0, durationS)))}
          x={x(clamp(interval.startS, 0, durationS))}
          y={margin.top}
        >
          <title>Inactive period: {formatTimeOffset(interval.startS)} - {formatTimeOffset(interval.endS)}</title>
        </rect>
      ))}
      <rect className="viz-time-window-range" x={selectionX} y={margin.top} width={selectionWidth} height={height - margin.top - margin.bottom} />
      <line className="viz-axis" x1={margin.left} y1={height - margin.bottom} x2={width - margin.right} y2={height - margin.bottom} />
      <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
      {frontPath && <path className="viz-time-window-line front" d={frontPath} />}
      {rearPath && <path className="viz-time-window-line rear" d={rearPath} />}
      {timeWindowTicks(durationS).map((tick) => {
        const value = tick.value
        return (
          <g key={value}>
            <line className="viz-tick" x1={x(value)} x2={x(value)} y1={height - margin.bottom} y2={height - margin.bottom + 4} />
            {tick.label && (
              <text className="viz-axis-label" x={x(value)} y={height - 4} textAnchor="middle">
                {formatTimeOffset(value)}
              </text>
            )}
          </g>
        )
      })}
      {empty && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2 + 4} textAnchor="middle">
          No displacement signal for overview
        </text>
      )}
      <rect
        className="viz-time-window-handle"
        x={selectionX - handleWidth / 2}
        y={margin.top}
        width={handleWidth}
        height={height - margin.top - margin.bottom}
      />
      <rect
        className="viz-time-window-handle"
        x={selectionX + selectionWidth - handleWidth / 2}
        y={margin.top}
        width={handleWidth}
        height={height - margin.top - margin.bottom}
      />
    </svg>
  )
}

function VisualizationFilterChips({
  entities,
  scopeMode,
  sectors,
  selectedEndKeys,
  selectedEntityIds,
  selectedSectorIds,
  onToggleEnd,
  onToggleEntity,
  onToggleSector,
}: {
  entities: VisualizationEntity[]
  scopeMode: ScopeMode
  sectors: TrackSector[]
  selectedEndKeys: SuspensionEnd[]
  selectedEntityIds: string[]
  selectedSectorIds: string[]
  onToggleEnd: (end: SuspensionEnd) => void
  onToggleEntity: (entityId: string) => void
  onToggleSector: (sectorId: string) => void
}) {
  const selectedSectorCount = sectors.filter((sector) => selectedSectorIds.includes(sector.id)).length
  return (
    <div
      className="viz-entity-selector"
      aria-label={`Visualization filters: ${selectedEntityIds.length} sessions/groups, ${selectedEndKeys.length} ends, ${selectedSectorCount} sectors`}
    >

      <div className="viz-filter-group">
        <strong>Sessions and groups</strong>
        <div className="viz-entity-chips">
          {entities.map((entity) => {
            const selected = selectedEntityIds.includes(entity.id)
            return (
              <button
                className={`viz-entity-chip${selected ? ' selected' : ''}${entity.kind === 'grouping' ? ' grouping' : ''}`}
                key={entity.id}
                type="button"
                onClick={() => onToggleEntity(entity.id)}
                style={entity.color ? { borderColor: entity.color } : undefined}
              >
                {entity.color && <span className="color-dot" style={{ backgroundColor: entity.color }} />}
                <span>{entity.label}</span>
                <small>{entity.kind === 'grouping' ? `${entity.sessionRefs.length} pooled` : 'session'}</small>
              </button>
            )
          })}
        </div>
      </div>

      <div className="viz-filter-group">
        <strong>Ends</strong>
        <div className="viz-entity-chips">
          {(['front', 'rear'] as const).map((end) => (
            <button
              className={`viz-entity-chip end-chip${selectedEndKeys.includes(end) ? ' selected' : ''}`}
              key={end}
              type="button"
              onClick={() => onToggleEnd(end)}
            >
              <span className="color-dot" style={{ backgroundColor: roleColor(end) }} />
              <span>{formatRole(end)}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="viz-filter-group">
        <strong className="inline-heading">
          Sectors
          <InfoTip
            text={
              scopeMode === 'sector'
                ? 'Selected sectors only are displayed and included in the overall view.'
                : 'Sector selections applied only in sector scope.'
            }
          />
        </strong>
        <div className="viz-entity-chips">
          {sectors.length === 0 && <span className="viz-filter-empty">No sectors available for the selected track.</span>}
          {sectors.map((sector) => {
            const selected = selectedSectorIds.includes(sector.id)
            return (
              <button
                className={`viz-entity-chip sector-chip${selected ? ' selected' : ''}`}
                key={sector.id}
                type="button"
                onClick={() => onToggleSector(sector.id)}
              >
                <span>{sector.label}</span>
                <small>{formatMetres(sector.lengthM)}</small>
              </button>
            )
          })}
        </div>
      </div>
    </div>
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
    <div className="viz-scope-control" aria-label="Visualization scope">
      <div className="viz-scope-main">
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
    </div>
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
          <strong className="viz-heading" id={`viz-panel-${id}`}>
            {title}
            <InfoTip text={subtitle} />
          </strong>
        </span>
        {collapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {!collapsed && children}
    </section>
  )
}

function DistributionGrid({
  chartKind,
  layout,
  entities,
  roles,
  valueForEntityRole,
  xDomain,
  xLabel,
  yLabel = 'proportion',
  bins,
  yMax,
  sessions = [],
  showStats = false,
  statsMode = 'basic',
  statsFormatter = formatPercentValue,
  statsTransform = (value: number) => value,
}: {
  chartKind: DistributionChartKind
  layout: ComparisonLayout
  entities: VisualizationEntity[]
  roles: DistributionRole[]
  valueForEntityRole: (entity: VisualizationEntity, role: DistributionRole) => number[]
  xDomain: [number, number]
  xLabel: string
  yLabel?: string
  bins: number
  yMax: number
  sessions?: SessionRecord[]
  showStats?: boolean
  statsMode?: DistributionStatsMode
  statsFormatter?: (value: number | null) => string
  statsTransform?: (value: number) => number
}) {
  if (roles.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>No ends selected.</strong>
        <span>Select front, rear, or both in the visualization filters.</span>
      </div>
    )
  }

  if (layout === 'ends') {
    return (
      <div className="viz-entity-strip responsive" style={responsiveStripStyle(roles.length, 382)}>
        {roles.map((role) => {
          const series = entities.map((entity, index) => ({
            id: entity.id,
            label: entity.label,
            color: entityColor(entity, index),
            values: valueForEntityRole(entity, role),
          }))
          return (
            <article className="viz-entity-tile viz-end-tile" key={role.key}>
              <EndTileHeader label={role.label} />
              {chartKind === 'mirrored_velocity' ? (
                <MirroredVelocityChart series={series} xDomain={xDomain} xLabel={xLabel} yLabel={yLabel} bins={bins} yMax={yMax} />
              ) : series.length <= 2 ? (
                <HistogramOverlayChart series={series} xDomain={xDomain} xLabel={xLabel} yLabel={yLabel} bins={bins} yMax={yMax} />
              ) : (
                <MultiHistogramChart series={series} xDomain={xDomain} xLabel={xLabel} yLabel={yLabel} bins={bins} yMax={yMax} />
              )}
              <EntitySeriesLegend
                series={series.map((item) => ({
                  id: item.id,
                  label: item.label,
                  color: item.color,
                  count: item.values.length,
                }))}
                emptyLabel="No matching signals"
              />
              {showStats && <DistributionStats formatter={statsFormatter} mode={statsMode} series={series} transform={statsTransform} />}
            </article>
          )
        })}
      </div>
    )
  }

  return (
    <div className="viz-entity-strip responsive" style={responsiveStripStyle(entities.length, 352)}>
      {entities.map((entity) => {
        const series = roles.map((role) => ({
          id: role.key,
          label: role.label,
          color: role.color,
          values: valueForEntityRole(entity, role),
        }))
        return (
          <article className="viz-entity-tile" key={entity.id}>
            <EntityTileHeader entity={entity} sessions={sessions} />
            {chartKind === 'mirrored_velocity' ? (
              <MirroredVelocityChart series={series} xDomain={xDomain} xLabel={xLabel} yLabel={yLabel} bins={bins} yMax={yMax} />
            ) : (
              <HistogramOverlayChart series={series} xDomain={xDomain} xLabel={xLabel} yLabel={yLabel} bins={bins} yMax={yMax} />
            )}
            {showStats && <DistributionStats formatter={statsFormatter} mode={statsMode} series={series} transform={statsTransform} />}
          </article>
        )
      })}
    </div>
  )
}

function SectorDistributionScaffold({
  quantity,
  layout,
  entities,
  ends,
  data,
  scaleData,
  selectedTrack,
  sectors,
  allSectors,
  frontRole,
  rearRole,
  xDomain,
  xLabel,
  bins,
  trackMatchesLoading,
  statsMode = 'basic',
  valueTransform = (values: number[]) => values,
}: {
  quantity: 'displacement' | 'velocity'
  layout: ComparisonLayout
  entities: VisualizationEntity[]
  ends: SuspensionEnd[]
  data: VisualizationData
  scaleData: VisualizationData
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  allSectors: TrackSector[]
  frontRole: string
  rearRole: string
  xDomain: [number, number]
  xLabel: string
  bins: number
  trackMatchesLoading: boolean
  statsMode?: DistributionStatsMode
  valueTransform?: (values: number[]) => number[]
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)

  if (!selectedTrack) {
    return (
      <div className="viz-sector-empty">
        <strong>No track attached to this Study Set.</strong>
        <span>Attach a track in the workbench before sector-based {quantity} comparison can be built.</span>
      </div>
    )
  }
  if (allSectors.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>{selectedTrack.name} has fewer than two ordered trackpoints.</strong>
        <span>Sector charts need at least two trackpoints so the browser can form trackpoint-bounded sectors.</span>
      </div>
    )
  }
  if (sectors.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>No sectors selected.</strong>
        <span>Select at least one sector in the visualization filters to build sector-mode charts.</span>
      </div>
    )
  }

  const roles = distributionRoles(frontRole, rearRole, ends)
  const chartKind: DistributionChartKind = quantity === 'velocity' ? 'mirrored_velocity' : 'histogram'
  const yMax = distributionYMax(
    entities,
    roles,
    (entity, role) => valueTransform(sectorValuesForEntityAcrossSectors(entity, scaleData, selectedTrack, sectors, role.signalRole)),
    xDomain,
    bins,
    chartKind,
  )
  const facetYMax = distributionYMax(
    entities,
    roles,
    (entity, role) =>
      sectors.flatMap((sector) => valueTransform(sectorValuesForEntity(entity, scaleData, selectedTrack, sector, role.signalRole))),
    xDomain,
    bins,
    chartKind,
  )
  const intervalEntityCount = entities.filter((entity) => entityHasSectorIntervals(entity, selectedTrack, sectors)).length
  const sampledEntityCount = entities.filter((entity) =>
    entityHasSectorSamples(entity, data, selectedTrack, sectors, roles.map((role) => role.signalRole)),
  ).length
  return (
    <div className="viz-sector-scaffold">
      <div className="viz-sector-scaffold-note">
        <div className="viz-sector-scaffold-note-text">
          <strong className="inline-heading">
            Selected-sector distribution
            <InfoTip text="Overall charts pool only the selected sectors, not the whole session. Sector matching uses the available track-match intervals for each active session or group." />
          </strong>
          <span>
            {selectedTrack.name}: {sectors.length} of {allSectors.length} sector(s) selected. {intervalEntityCount} active
            session/group(s) have usable sector intervals and {sampledEntityCount} currently have selected-sector samples.
            {trackMatchesLoading ? ' Track matches are still loading.' : ''}
          </span>
        </div>
      </div>

      <section className="viz-sector-overall">
        <header className="viz-sector-section-heading">
          <strong>Overall selected sectors</strong>
          <span>{sectors.length} sector(s) pooled</span>
        </header>
        <DistributionGrid
          bins={bins}
          chartKind={chartKind}
          entities={entities}
          layout={layout}
          roles={roles}
          showStats={statsMode !== 'basic'}
          statsMode={statsMode}
          valueForEntityRole={(entity, role) =>
            valueTransform(sectorValuesForEntityAcrossSectors(entity, data, selectedTrack, sectors, role.signalRole))
          }
          xDomain={xDomain}
          xLabel={xLabel}
          yMax={yMax}
        />
      </section>

      <section className={`viz-sector-facets${facetsCollapsed ? ' collapsed' : ''}`}>
        <button className="viz-sector-facet-toggle" type="button" onClick={() => setFacetsCollapsed((current) => !current)}>
          <span>
            <strong>Sector facets</strong>
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} vertical sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className="viz-sector-facet-stack">
            {sectors.map((sector) => (
              <article className="viz-sector-facet" key={sector.id}>
                <header className="viz-sector-section-heading">
                  <strong>{sector.label}</strong>
                  <span>{formatMetres(sector.lengthM)}</span>
                </header>
                <DistributionGrid
                  bins={bins}
                  chartKind={chartKind}
                  entities={entities}
                    layout={layout}
                    roles={roles}
                    showStats={statsMode !== 'basic'}
                    statsMode={statsMode}
                    valueForEntityRole={(entity, role) =>
                      valueTransform(sectorValuesForEntity(entity, data, selectedTrack, sector, role.signalRole))
                    }
                  xDomain={xDomain}
                  xLabel={xLabel}
                  yMax={facetYMax}
                />
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function SectorMetricDistributionScaffold({
  data,
  scaleData,
  entities,
  ends,
  layout,
  selectedTrack,
  sectors,
  allSectors,
  metricSpec,
  xLabel,
  bins,
  domainCandidates,
  statsFormatter,
  trackMatchesLoading,
}: {
  data: VisualizationData
  scaleData: VisualizationData
  entities: VisualizationEntity[]
  ends: SuspensionEnd[]
  layout: ComparisonLayout
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  allSectors: TrackSector[]
  metricSpec: MirroredMetricSpec
  xLabel: string
  bins: number
  domainCandidates: number[]
  statsFormatter: (value: number | null) => string
  trackMatchesLoading: boolean
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)
  const empty = sectorPanelEmptyState(selectedTrack, sectors, allSectors, 'metric distribution')
  if (empty) {
    return empty
  }
  const track = selectedTrack as TrackRecord
  const roles = distributionRoles('', '', ends)
  const overallRowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.metrics, data, track, sectors)
  const scaleRowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, scaleData.metrics, scaleData, track, sectors)
  const xDomain = metricMagnitudeCandidateDomainFromRows(entities, roles, scaleRowsForEntity, metricSpec, domainCandidates)
  const yMax = distributionYMax(
    entities,
    roles,
    (entity, role) => metricMirroredValuesForRows(scaleRowsForEntity(entity), role.key, metricSpec),
    xDomain,
    bins,
    'mirrored_velocity',
  )
  return (
    <div className="viz-sector-scaffold">
      <SectorRowsNote
        allSectors={allSectors}
        data={data}
        entities={entities}
        label="Selected-sector metric distribution"
        rowKind="metric"
        rows={data.metrics}
        sectors={sectors}
        selectedTrack={track}
        trackMatchesLoading={trackMatchesLoading}
      />

      <section className="viz-sector-overall">
        <header className="viz-sector-section-heading">
          <strong>Overall selected sectors</strong>
          <span>{sectors.length} sector(s) pooled by primary trigger</span>
        </header>
        <DistributionGrid
          bins={bins}
          chartKind="mirrored_velocity"
          entities={entities}
          layout={layout}
          roles={roles}
          showStats
          statsFormatter={statsFormatter}
          statsTransform={Math.abs}
          valueForEntityRole={(entity, role) => metricMirroredValuesForRows(overallRowsForEntity(entity), role.key, metricSpec)}
          xDomain={xDomain}
          xLabel={xLabel}
          yMax={yMax}
        />
      </section>

      <section className={`viz-sector-facets${facetsCollapsed ? ' collapsed' : ''}`}>
        <button className="viz-sector-facet-toggle" type="button" onClick={() => setFacetsCollapsed((current) => !current)}>
          <span>
            <strong>Sector facets</strong>
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} vertical sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className="viz-sector-facet-stack">
            {sectors.map((sector) => {
              const rowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.metrics, data, track, [sector])
              return (
                <article className="viz-sector-facet" key={sector.id}>
                  <header className="viz-sector-section-heading">
                    <strong>{sector.label}</strong>
                    <span>{formatMetres(sector.lengthM)}</span>
                  </header>
                  <DistributionGrid
                    bins={bins}
                    chartKind="mirrored_velocity"
                    entities={entities}
                    layout={layout}
                    roles={roles}
                    showStats
                    statsFormatter={statsFormatter}
                    statsTransform={Math.abs}
                    valueForEntityRole={(entity, role) => metricMirroredValuesForRows(rowsForEntity(entity), role.key, metricSpec)}
                    xDomain={xDomain}
                    xLabel={xLabel}
                    yMax={yMax}
                  />
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

function SectorScatterScaffold({
  data,
  ends,
  entities,
  eventType,
  layout,
  selectedTrack,
  sectors,
  allSectors,
  xMetric,
  yMetric,
  yLabel,
  trackMatchesLoading,
}: {
  data: VisualizationData
  ends: SuspensionEnd[]
  entities: VisualizationEntity[]
  eventType: string
  layout: ComparisonLayout
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  allSectors: TrackSector[]
  xMetric: string
  yMetric: string
  yLabel: string
  trackMatchesLoading: boolean
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)
  const empty = sectorPanelEmptyState(selectedTrack, sectors, allSectors, 'metric scatter')
  if (empty) {
    return empty
  }
  const track = selectedTrack as TrackRecord
  const overallRowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.metrics, data, track, sectors)
  return (
    <div className="viz-sector-scaffold">
      <SectorRowsNote
        allSectors={allSectors}
        data={data}
        entities={entities}
        label="Selected-sector metric scatter"
        rowKind="metric"
        rows={data.metrics}
        sectors={sectors}
        selectedTrack={track}
        trackMatchesLoading={trackMatchesLoading}
      />

      <section className="viz-sector-overall">
        <header className="viz-sector-section-heading">
          <strong>Overall selected sectors</strong>
          <span>{sectors.length} sector(s) pooled by primary trigger</span>
        </header>
        <ScatterEntityStrip
          data={data}
          ends={ends}
          entities={entities}
          eventType={eventType}
          layout={layout}
          rowsForEntity={overallRowsForEntity}
          showRegression
          xMetric={xMetric}
          yMetric={yMetric}
          yLabel={yLabel}
        />
      </section>

      <section className={`viz-sector-facets${facetsCollapsed ? ' collapsed' : ''}`}>
        <button className="viz-sector-facet-toggle" type="button" onClick={() => setFacetsCollapsed((current) => !current)}>
          <span>
            <strong>Sector facets</strong>
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} vertical sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className="viz-sector-facet-stack">
            {sectors.map((sector) => {
              const rowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.metrics, data, track, [sector])
              return (
                <article className="viz-sector-facet" key={sector.id}>
                  <header className="viz-sector-section-heading">
                    <strong>{sector.label}</strong>
                    <span>{formatMetres(sector.lengthM)}</span>
                  </header>
                  <ScatterEntityStrip
                    data={data}
                    ends={ends}
                    entities={entities}
                    eventType={eventType}
                    layout={layout}
                    rowsForEntity={rowsForEntity}
                    showRegression
                    xMetric={xMetric}
                    yMetric={yMetric}
                    yLabel={yLabel}
                  />
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

function SectorEventCountScaffold({
  data,
  ends,
  entities,
  selectedTrack,
  sectors,
  allSectors,
  trackMatchesLoading,
}: {
  data: VisualizationData
  ends: SuspensionEnd[]
  entities: VisualizationEntity[]
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  allSectors: TrackSector[]
  trackMatchesLoading: boolean
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)
  const empty = sectorPanelEmptyState(selectedTrack, sectors, allSectors, 'event counts')
  if (empty) {
    return empty
  }
  const track = selectedTrack as TrackRecord
  const overallRowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.events, data, track, sectors)
  return (
    <div className="viz-sector-scaffold">
      <SectorRowsNote
        allSectors={allSectors}
        data={data}
        entities={entities}
        label="Selected-sector event counts"
        rowKind="event"
        rows={data.events}
        sectors={sectors}
        selectedTrack={track}
        trackMatchesLoading={trackMatchesLoading}
      />

      <section className="viz-sector-overall">
        <header className="viz-sector-section-heading">
          <strong>Overall selected sectors</strong>
          <span>{sectors.length} sector(s) pooled by primary trigger</span>
        </header>
        <EventCountStrip data={data} ends={ends} entities={entities} rowsForEntity={overallRowsForEntity} />
      </section>

      <section className={`viz-sector-facets${facetsCollapsed ? ' collapsed' : ''}`}>
        <button className="viz-sector-facet-toggle" type="button" onClick={() => setFacetsCollapsed((current) => !current)}>
          <span>
            <strong>Sector facets</strong>
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} vertical sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className="viz-sector-facet-stack">
            {sectors.map((sector) => {
              const rowsForEntity = (entity: VisualizationEntity) => rowsInSectorsForEntity(entity, data.events, data, track, [sector])
              return (
                <article className="viz-sector-facet" key={sector.id}>
                  <header className="viz-sector-section-heading">
                    <strong>{sector.label}</strong>
                    <span>{formatMetres(sector.lengthM)}</span>
                  </header>
                  <EventCountStrip data={data} ends={ends} entities={entities} rowsForEntity={rowsForEntity} />
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

function SectorRowsNote({
  allSectors,
  data,
  entities,
  label,
  rowKind,
  rows,
  sectors,
  selectedTrack,
  trackMatchesLoading,
}: {
  allSectors: TrackSector[]
  data: VisualizationData
  entities: VisualizationEntity[]
  label: string
  rowKind: string
  rows: TableQueryRow[]
  sectors: TrackSector[]
  selectedTrack: TrackRecord
  trackMatchesLoading: boolean
}) {
  const intervalEntityCount = entities.filter((entity) => entityHasSectorIntervals(entity, selectedTrack, sectors)).length
  const rowCount = entities.reduce(
    (total, entity) => total + rowsInSectorsForEntity(entity, rows, data, selectedTrack, sectors).length,
    0,
  )
  return (
    <div className="viz-sector-scaffold-note">
      <div className="viz-sector-scaffold-note-text">
        <strong className="inline-heading">
          {label}
          <InfoTip text={`${rowKind[0].toUpperCase()}${rowKind.slice(1)} rows are assigned to selected sectors by primary trigger time.`} />
        </strong>
        <span>
          {selectedTrack.name}: {sectors.length} of {allSectors.length} sector(s) selected. {rowCount} {rowKind} row(s).
          {intervalEntityCount} active session/group(s) have usable sector intervals.
          {trackMatchesLoading ? ' Track matches are still loading.' : ''}
        </span>
      </div>
    </div>
  )
}

function sectorPanelEmptyState(
  selectedTrack: TrackRecord | null,
  sectors: TrackSector[],
  allSectors: TrackSector[],
  label: string,
) {
  if (!selectedTrack) {
    return (
      <div className="viz-sector-empty">
        <strong>No track attached to this Study Set.</strong>
        <span>Attach a track in the workbench before sector-based {label} can be built.</span>
      </div>
    )
  }
  if (allSectors.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>{selectedTrack.name} has fewer than two ordered trackpoints.</strong>
        <span>Sector charts need at least two trackpoints so the browser can form trackpoint-bounded sectors.</span>
      </div>
    )
  }
  if (sectors.length === 0) {
    return (
      <div className="viz-sector-empty">
        <strong>No sectors selected.</strong>
        <span>Select at least one sector in the visualization filters to build sector-mode {label}.</span>
      </div>
    )
  }
  return null
}

function EventCountStrip({
  entities,
  data,
  ends,
  rowsForEntity,
}: {
  entities: VisualizationEntity[]
  data: VisualizationData
  ends: SuspensionEnd[]
  rowsForEntity?: (entity: VisualizationEntity) => TableQueryRow[]
}) {
  return (
    <div className="viz-entity-strip responsive" style={responsiveStripStyle(entities.length, 330)}>
      {entities.map((entity) => (
        <article className="viz-entity-tile compact" key={entity.id}>
          <EntityTileHeader entity={entity} />
          <EventCountTable rows={rowsForEntity ? rowsForEntity(entity) : entityRows(entity, data.events)} ends={ends} />
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
  ends,
  rowsForEntity,
  showRegression = false,
}: {
  layout: ComparisonLayout
  entities: VisualizationEntity[]
  data: VisualizationData
  eventType: string
  xMetric: string
  yMetric: string
  yLabel: string
  ends: SuspensionEnd[]
  rowsForEntity?: (entity: VisualizationEntity) => TableQueryRow[]
  showRegression?: boolean
}) {
  const rowProvider = rowsForEntity ?? ((entity: VisualizationEntity) => entityRows(entity, data.metrics))
  const extent = scatterPanelExtent(entities, eventType, xMetric, yMetric, ends, rowProvider)
  if (layout === 'ends') {
    return (
      <ScatterEndStrip
        ends={ends}
        entities={entities}
        eventType={eventType}
        xMetric={xMetric}
        yMetric={yMetric}
        yLabel={yLabel}
        extent={extent}
        rowsForEntity={rowProvider}
        showRegression={showRegression}
      />
    )
  }

  return (
    <div className="viz-entity-strip responsive" style={responsiveStripStyle(entities.length, 352)}>
      {entities.map((entity) => {
        const points = scatterPoints(rowProvider(entity), eventType, xMetric, yMetric).filter(
          (point) => point.role !== 'unknown' && ends.includes(point.role),
        )
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
  ends,
  entities,
  eventType,
  xMetric,
  yMetric,
  yLabel,
  extent,
  rowsForEntity,
  showRegression,
}: {
  ends: SuspensionEnd[]
  entities: VisualizationEntity[]
  eventType: string
  xMetric: string
  yMetric: string
  yLabel: string
  extent: { x: [number, number]; y: [number, number] }
  rowsForEntity: (entity: VisualizationEntity) => TableQueryRow[]
  showRegression: boolean
}) {
  const roles = distributionRoles('', '', ends)
  return (
    <div className="viz-entity-strip responsive" style={responsiveStripStyle(roles.length, 382)}>
      {roles.map((role) => {
        const series = entities.map((entity, index) => ({
          id: entity.id,
          label: entity.label,
          color: entityColor(entity, index),
          points: scatterPoints(rowsForEntity(entity), eventType, xMetric, yMetric).filter(
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
      <small>selected sessions/groups overlaid</small>
    </header>
  )
}

function responsiveStripStyle(count: number, minTileWidth: number): CSSProperties {
  const safeCount = Math.max(1, count)
  const gapPx = 10
  const maxTileWidth =
    safeCount === 1
      ? `clamp(${minTileWidth}px, 32%, 560px)`
      : safeCount === 2
        ? `clamp(${minTileWidth}px, 48%, 640px)`
        : `var(--viz-target-tile-width)`
  return {
    '--viz-min-tile-width': `${minTileWidth}px`,
    '--viz-max-tile-width': maxTileWidth,
    '--viz-target-tile-width': `calc((100% - ${(safeCount - 1) * gapPx}px) / ${safeCount})`,
  } as CSSProperties
}

function histogramBarGeometry(
  x: d3.ScaleLinear<number, number>,
  bin: { x0: number; x1: number },
  seriesIndex = 0,
  seriesCount = 1,
) {
  const binX0 = x(bin.x0)
  const binX1 = x(bin.x1)
  const fullWidth = Math.max(1, binX1 - binX0)
  const gap = Math.min(1, fullWidth * 0.18)
  const slotWidth = Math.max(1, (fullWidth - gap) / Math.max(1, seriesCount))
  return {
    width: slotWidth,
    x: binX0 + gap / 2 + slotWidth * seriesIndex,
  }
}

function histogramBinTitle(label: string, bin: HistogramBin, xLabel: string, directionLabel = '') {
  const direction = directionLabel ? `${directionLabel}\n` : ''
  return `${label}\n${direction}${xLabel}: ${formatAxis(bin.x0)}-${formatAxis(bin.x1)}\nproportion: ${formatProportion(bin.proportion)}\ncount: ${bin.count}/${bin.total}`
}

function histogramSeriesTitle(label: string, bins: HistogramBin[], sampleCount: number, xLabel: string, directionLabel = '') {
  const peak = bins.reduce<HistogramBin | null>((current, bin) => (!current || bin.proportion > current.proportion ? bin : current), null)
  const direction = directionLabel ? `${directionLabel}\n` : ''
  return peak
    ? `${label}\n${direction}${sampleCount} sample(s)\npeak ${xLabel}: ${formatAxis(peak.x0)}-${formatAxis(peak.x1)}\npeak proportion: ${formatProportion(peak.proportion)}`
    : `${label}\n${direction}No samples`
}

function scatterPointTitle(
  label: string,
  xLabel: string,
  yLabel: string,
  point: { x: number; y: number; role?: 'front' | 'rear' | 'unknown' },
) {
  const role = point.role ? `\nend: ${formatRole(point.role)}` : ''
  return `${label}${role}\n${xLabel}: ${formatAxis(point.x)}\n${yLabel}: ${formatAxis(point.y)}`
}

function HistogramOverlayChart({
  series,
  xDomain,
  xLabel,
  yLabel,
  bins,
  yMax,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 180
  const margin = { top: 12, right: 12, bottom: 34, left: 34 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const seriesBins = series.map((item) => ({
    ...item,
    bins: histogramBins(item.values, xDomain, bins),
  }))
  const localYMax =
    Math.max(...seriesBins.flatMap((item) => item.bins.map((bin) => bin.proportion)), 0) || yMax || 1
  const y = d3.scaleLinear().domain([0, localYMax]).range([height - margin.bottom, margin.top])
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
      {seriesBins.map((item, seriesIndex) =>
        item.bins.map((bin) => {
          const bar = histogramBarGeometry(x, bin, seriesIndex, Math.max(1, seriesBins.length))
          return (
            <rect
              className="viz-histogram-bar"
              fill={item.color}
              fillOpacity={0.3}
              key={`${item.id}-${bin.x0}`}
              stroke={item.color}
              strokeOpacity={0.66}
              width={bar.width}
              x={bar.x}
              y={y(bin.proportion)}
              height={height - margin.bottom - y(bin.proportion)}
            >
              <title>{histogramBinTitle(item.label, bin, xLabel)}</title>
            </rect>
          )
        }),
      )}
      <text className="viz-axis-title" x={width / 2} y={height - 1} textAnchor="middle">
        {xLabel}
      </text>
      <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
        {yLabel}
      </text>
      {allEmpty && (
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
  yLabel,
  bins,
  yMax,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 180
  const margin = { top: 12, right: 12, bottom: 34, left: 34 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const seriesBins = series.map((item) => ({
    ...item,
    bins: histogramBins(item.values, xDomain, bins),
  }))
  const localYMax =
    Math.max(...seriesBins.flatMap((item) => item.bins.map((bin) => bin.proportion)), 0) || yMax || 1
  const y = d3.scaleLinear().domain([0, localYMax]).range([height - margin.bottom, margin.top])
  const line = d3
    .line<{ x0: number; x1: number; proportion: number }>()
    .x((bin) => x((bin.x0 + bin.x1) / 2))
    .y((bin) => y(bin.proportion))
    .curve(d3.curveStepAfter)
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
          <path className="viz-series-line" d={path} key={item.id} stroke={item.color}>
            <title>{histogramSeriesTitle(item.label, item.bins, item.values.length, xLabel)}</title>
          </path>
        ) : null
      })}
      <text className="viz-axis-title" x={width / 2} y={height - 1} textAnchor="middle">
        {xLabel}
      </text>
      <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
        {yLabel}
      </text>
      {allEmpty && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
          No matching signals
        </text>
      )}
    </svg>
  )
}

function MirroredVelocityChart({
  series,
  xDomain,
  xLabel,
  yLabel,
  bins,
  yMax,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 202
  const margin = { top: 22, right: 12, bottom: 34, left: 38 }
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const mirroredBins = series.map((item) => ({
    ...item,
    ...mirroredVelocityBins(item.values, xDomain, bins),
  }))
  const localYMax =
    Math.max(...mirroredBins.flatMap((item) => [...item.compression, ...item.rebound].map((bin) => bin.proportion)), 0) ||
    yMax ||
    1
  const y = d3.scaleLinear().domain([-localYMax, localYMax]).range([height - margin.bottom, margin.top])
  const line = d3
    .line<{ x0: number; x1: number; proportion: number }>()
    .x((bin) => x((bin.x0 + bin.x1) / 2))
    .y((bin) => y(bin.proportion))
    .curve(d3.curveStepAfter)
  const mirroredLine = d3
    .line<{ x0: number; x1: number; proportion: number }>()
    .x((bin) => x((bin.x0 + bin.x1) / 2))
    .y((bin) => y(-bin.proportion))
    .curve(d3.curveStepAfter)
  const allEmpty = series.every((item) => item.values.length === 0)
  const renderBars = series.length <= 2
  const seriesCount = Math.max(1, series.length)
  return (
    <svg className="viz-chart viz-mirrored-velocity-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={xLabel}>
      <line className="viz-axis" x1={margin.left} y1={y(0)} x2={width - margin.right} y2={y(0)} />
      <line className="viz-axis" x1={margin.left} y1={margin.top} x2={margin.left} y2={height - margin.bottom} />
      {[0, 0.5, 1].map((tick) => {
        const value = xDomain[0] + (xDomain[1] - xDomain[0]) * tick
        return (
          <g key={tick}>
            <line className="viz-tick" x1={x(value)} x2={x(value)} y1={y(0)} y2={y(0) + 4} />
            <text className="viz-axis-label" x={x(value)} y={height - 14} textAnchor="middle">
              {formatAxis(value)}
            </text>
          </g>
        )
      })}
      <text className="viz-mirror-label" x={margin.left + 4} y={margin.top + 3}>
        Compression
      </text>
      <text className="viz-mirror-label" x={margin.left + 4} y={height - margin.bottom - 8}>
        Rebound
      </text>
      {renderBars
        ? mirroredBins.map((item, seriesIndex) => (
            <g key={item.id}>
              {item.compression.map((bin) => {
                const bar = histogramBarGeometry(x, bin, seriesIndex, seriesCount)
                return (
                  <rect
                    className="viz-histogram-bar"
                    fill={item.color}
                    fillOpacity={0.36}
                    height={y(0) - y(bin.proportion)}
                    key={`compression-${item.id}-${bin.x0}`}
                    stroke={item.color}
                    strokeOpacity={0.7}
                    width={bar.width}
                    x={bar.x}
                    y={y(bin.proportion)}
                  >
                    <title>{histogramBinTitle(item.label, bin, xLabel, 'Compression')}</title>
                  </rect>
                )
              })}
              {item.rebound.map((bin) => {
                const bar = histogramBarGeometry(x, bin, seriesIndex, seriesCount)
                return (
                  <rect
                    className="viz-histogram-bar"
                    fill={item.color}
                    fillOpacity={0.36}
                    height={y(-bin.proportion) - y(0)}
                    key={`rebound-${item.id}-${bin.x0}`}
                    stroke={item.color}
                    strokeOpacity={0.7}
                    width={bar.width}
                    x={bar.x}
                    y={y(0)}
                  >
                    <title>{histogramBinTitle(item.label, bin, xLabel, 'Rebound')}</title>
                  </rect>
                )
              })}
            </g>
          ))
        : mirroredBins.map((item) => {
            const compressionPath = line(item.compression)
            const reboundPath = mirroredLine(item.rebound)
            return (
              <g key={item.id}>
                {compressionPath && (
                  <path className="viz-series-line" d={compressionPath} stroke={item.color}>
                    <title>{histogramSeriesTitle(item.label, item.compression, item.values.filter((value) => value >= 0).length, xLabel, 'Compression')}</title>
                  </path>
                )}
                {reboundPath && (
                  <path className="viz-series-line" d={reboundPath} stroke={item.color}>
                    <title>{histogramSeriesTitle(item.label, item.rebound, item.values.filter((value) => value < 0).length, xLabel, 'Rebound')}</title>
                  </path>
                )}
              </g>
            )
          })}
      <text className="viz-axis-title" x={width / 2} y={height - 1} textAnchor="middle">
        {xLabel}
      </text>
      <text className="viz-axis-title" transform={`translate(12 ${height / 2}) rotate(-90)`} textAnchor="middle">
        {yLabel}
      </text>
      {allEmpty && (
        <text className="viz-empty-chart" x={width / 2} y={height / 2} textAnchor="middle">
          No matching signals
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
            fillOpacity={0.38}
            key={`${point.role}-${index}`}
            r={2.7}
          >
            <title>{scatterPointTitle(formatRole(point.role), xLabel, yLabel, point)}</title>
          </circle>
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
              fillOpacity={0.38}
              key={`${item.id}-${index}`}
              r={2.7}
            >
              <title>{scatterPointTitle(item.label, xLabel, yLabel, point)}</title>
            </circle>
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
    <div className="viz-series-legend" aria-label="Session and group series">
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

function EventCountTable({ rows, ends }: { rows: TableQueryRow[]; ends: SuspensionEnd[] }) {
  const counts = eventCounts(rows)
  return (
    <table className="viz-count-table">
      <thead>
        <tr>
          <th>Event</th>
          {ends.includes('front') && <th>Front</th>}
          {ends.includes('rear') && <th>Rear</th>}
          <th>Unknown</th>
        </tr>
      </thead>
      <tbody>
        {counts.length === 0 && (
          <tr>
            <td colSpan={ends.length + 2}>No events</td>
          </tr>
        )}
        {counts.map((row) => (
          <tr key={row.eventType}>
            <td>{row.eventType}</td>
            {ends.includes('front') && <td>{row.front || '-'}</td>}
            {ends.includes('rear') && <td>{row.rear || '-'}</td>}
            <td>{row.unknown || '-'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DistributionStats({
  formatter,
  mode = 'basic',
  series,
  transform,
}: {
  formatter: (value: number | null) => string
  mode?: DistributionStatsMode
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  transform: (value: number) => number
}) {
  return (
    <div className="viz-stat-grid">
      {series.map((item) => (
        <RoleStats
          color={item.color}
          formatter={formatter}
          key={item.id}
          label={item.label}
          mode={mode}
          transform={transform}
          values={item.values}
        />
      ))}
    </div>
  )
}

function RoleStats({
  color,
  formatter,
  label,
  mode,
  transform,
  values,
}: {
  color: string
  formatter: (value: number | null) => string
  label: string
  mode: DistributionStatsMode
  transform: (value: number) => number
  values: number[]
}) {
  const stats = distributionStats(values.map(transform))
  const displacementStats = mode === 'displacement'
  return (
    <dl>
      <dt>
        <span style={{ backgroundColor: color }} />
        {label}
      </dt>
      {displacementStats && <dd>dynamic sag {formatter(stats.mean)}</dd>}
      <dd>median {formatter(stats.median)}</dd>
      <dd>95th {formatter(stats.p95)}</dd>
      <dd>max {formatter(stats.max)}</dd>
      {displacementStats && <dd>IQR {formatter(stats.iqr)}</dd>}
      {displacementStats && <dd>skew {formatSkew(stats.skew)}</dd>}
    </dl>
  )
}

async function loadVisualizationData(
  requestedSessionRefs: StudySessionRef[],
  dataSource: LibraryDataSource,
): Promise<VisualizationData> {
  const sessionRefs = uniqueSessionRefs(requestedSessionRefs)
  const sessionCache = visualizationSessionCache(dataSource)
  const missingSessionRefs = sessionRefs.filter((sessionRef) => !sessionCache.has(sessionRefId(sessionRef)))

  for (const [libraryId, refs] of groupRefsByLibrary(missingSessionRefs).entries()) {
    const [signals, events, metrics] = await Promise.all([
      dataSource.querySignals(libraryId, { sessions: refs, signals: SIGNAL_REQUESTS }),
      dataSource.queryEvents(libraryId, { sessions: refs }),
      dataSource.queryMetrics(libraryId, {
        sessions: refs,
        eventTypes: [COMPRESSION_EVENT_TYPE, REBOUND_EVENT_TYPE],
      }),
    ])
    const requestWarnings = [
      ...signals.warnings.filter((warning) => !activitySignalWarning(warning)).map((warning) => warningMessage(warning)),
      ...events.warnings.map((warning) => warningMessage(warning)),
      ...metrics.warnings.map((warning) => warningMessage(warning)),
    ].filter(Boolean)
    const fetchedSessions = new Map<string, CachedSessionVisualizationData>()
    for (const ref of refs) {
      const key = sessionRefId(ref)
      fetchedSessions.set(key, {
        sessionRef: { ...ref },
        time: [],
        signals: {},
        events: [],
        metrics: [],
        warnings: [...requestWarnings],
      })
    }
    for (const session of signals.sessions) {
      const key = sessionRefId(session.sessionRef)
      const cached = fetchedSessions.get(key) ?? {
        sessionRef: { ...session.sessionRef },
        time: [],
        signals: {},
        events: [],
        metrics: [],
        warnings: [...requestWarnings],
      }
      if (!session.time) {
        cached.warnings.push(`${session.sessionRef.label || key}: signal payload has no time column; sector mode is unavailable.`)
        cached.time = []
      } else {
        cached.time = normalizeSignalTimes(numericValues(session.time.values))
      }
      if (!session.sampling.distributionCorrect) {
        cached.warnings.push(`${session.sessionRef.label || key}: signal payload is not distribution-correct.`)
      }
      for (const signal of session.signals) {
        const role = normalizedActivitySignalRole(signal.column, signal.role)
        cached.signals[role] = numericValues(signal.values)
      }
      fetchedSessions.set(key, cached)
    }

    const eventRowsBySession = rowsGroupedBySession(events.rows)
    const metricRowsBySession = rowsGroupedBySession(metrics.rows)
    for (const [key, cached] of fetchedSessions.entries()) {
      cached.events = eventRowsBySession.get(key) ?? []
      cached.metrics = metricRowsBySession.get(key) ?? []
      cached.warnings = uniqueStrings(cached.warnings)
      sessionCache.set(key, cached)
    }
  }

  const cachedSessions = sessionRefs.map((sessionRef) => sessionCache.get(sessionRefId(sessionRef)) ?? emptyCachedSession(sessionRef))
  const eventRows = cachedSessions.flatMap((session) => session.events)
  const metricRows = cachedSessions.flatMap((session) => session.metrics)

  return {
    timeBySession: Object.fromEntries(cachedSessions.map((session) => [sessionRefId(session.sessionRef), session.time])),
    signalsBySession: Object.fromEntries(cachedSessions.map((session) => [sessionRefId(session.sessionRef), session.signals])),
    events: eventRows,
    eventTriggerTimeByKey: eventTriggerTimeMap(eventRows),
    metrics: metricRows,
    warnings: uniqueStrings(cachedSessions.flatMap((session) => session.warnings).filter(Boolean)),
  }
}

function visualizationSessionCache(dataSource: LibraryDataSource) {
  const cached = visualizationSessionCacheByDataSource.get(dataSource)
  if (cached) {
    return cached
  }
  const next = new Map<string, CachedSessionVisualizationData>()
  visualizationSessionCacheByDataSource.set(dataSource, next)
  return next
}

function emptyCachedSession(sessionRef: StudySessionRef): CachedSessionVisualizationData {
  return {
    sessionRef: { ...sessionRef },
    time: [],
    signals: {},
    events: [],
    metrics: [],
    warnings: [],
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

function visualizationSettingsKey(studySet: StudySet) {
  if (studySet.id) {
    return `study-set:${studySet.id}`
  }
  if (studySet.provenance.startsWith('Temporary one-session Study Set')) {
    return `temporary:${stableStudySetKey(studySet)}`
  }
  const name = studySet.displayName.trim() || 'untitled'
  const provenance = studySet.provenance.trim() || 'interactive'
  return `unsaved:${name}:${provenance}`
}

function restoredVisualizationSettings(
  cacheKey: string,
  entities: VisualizationEntity[],
  tracks: TrackRecord[],
): SuspensionVisualizationSettings {
  const cached = visualizationSettingsCache.get(cacheKey)
  const defaultSelectedEntityIds = entities.filter((entity) => entity.kind === 'session').map((entity) => entity.id)
  const selectedEntityIds = cached
    ? normalizedSelectedEntityIds(cached.selectedEntityIds, cached.knownSessionEntityIds, defaultSelectedEntityIds, entities)
    : defaultSelectedEntityIds
  const validTrackIds = new Set(tracks.map((track) => track.id))
  const selectedTrackId = cached?.selectedTrackId && validTrackIds.has(cached.selectedTrackId)
    ? cached.selectedTrackId
    : tracks[0]?.id ?? null
  return {
    selectedEntityIds,
    knownSessionEntityIds: defaultSelectedEntityIds,
    collapsedPanels: cached?.collapsedPanels ? [...cached.collapsedPanels] : [],
    comparisonLayout: cached?.comparisonLayout ?? 'entities',
    scopeMode: cached?.scopeMode ?? 'whole_session',
    selectedTrackId,
    selectedEnds: normalizedSelectedEnds(cached?.selectedEnds),
    selectedSectorIds: cached?.selectedSectorIds ? [...cached.selectedSectorIds] : [],
    timeWindowsBySession: cached?.timeWindowsBySession ? { ...cached.timeWindowsBySession } : {},
    excludeInactivePeriods: cached?.excludeInactivePeriods ?? true,
  }
}

function normalizedSelectedEntityIds(
  cachedEntityIds: string[],
  knownSessionEntityIds: string[],
  defaultSessionEntityIds: string[],
  entities: VisualizationEntity[],
) {
  const validEntityIds = new Set(entities.map((entity) => entity.id))
  const cachedEntityIdSet = new Set(cachedEntityIds)
  const knownSessionEntityIdSet = new Set(knownSessionEntityIds)
  const retained = cachedEntityIds.filter((entityId) => validEntityIds.has(entityId))
  const addedSessionIds = defaultSessionEntityIds.filter(
    (entityId) => !cachedEntityIdSet.has(entityId) && !knownSessionEntityIdSet.has(entityId),
  )
  return [...retained, ...addedSessionIds]
}

function normalizedSelectedEnds(value: SuspensionEnd[] | undefined) {
  const validEnds = new Set<SuspensionEnd>(['front', 'rear'])
  const ends = (value ?? ['front', 'rear']).filter((end): end is SuspensionEnd => validEnds.has(end))
  return ends.length > 0 ? ends : (['front', 'rear'] as SuspensionEnd[])
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

function eventTriggerTimeMap(rows: TableQueryRow[]) {
  const out: Record<string, number> = {}
  for (const row of rows) {
    const key = tableRowEventKey(row)
    if (!key || out[key] !== undefined) {
      continue
    }
    const triggerTimeS = firstNumericField(
      row.fields.trigger_time_s,
      row.fields.primary_trigger_time_s,
      row.fields.t0_time,
      row.fields.time_s,
    )
    if (triggerTimeS !== null) {
      out[key] = triggerTimeS
    }
  }
  return out
}

function applyTimeWindows(data: VisualizationData, timeWindows: TimeWindowsBySession): VisualizationData {
  const windowSessionKeys = Object.keys(timeWindows)
  if (windowSessionKeys.length === 0) {
    return data
  }
  const windowedSessions = new Set(windowSessionKeys)
  const signalsBySession: Record<string, Record<string, number[]>> = {}
  const timeBySession: Record<string, number[]> = {}
  for (const [key, signals] of Object.entries(data.signalsBySession)) {
    const times = data.timeBySession[key] ?? []
    const window = timeWindows[key] ?? null
    if (!window) {
      signalsBySession[key] = signals
      timeBySession[key] = times
      continue
    }
    const range = timeWindowIndexRange(times, window)
    timeBySession[key] = times.slice(range.startIndex, range.endIndex)
    signalsBySession[key] = {}
    for (const [role, values] of Object.entries(signals)) {
      signalsBySession[key][role] = values.slice(range.startIndex, range.endIndex)
    }
  }
  for (const [key, times] of Object.entries(data.timeBySession)) {
    if (timeBySession[key]) {
      continue
    }
    const window = timeWindows[key] ?? null
    if (!window) {
      timeBySession[key] = times
      continue
    }
    const range = timeWindowIndexRange(times, window)
    timeBySession[key] = times.slice(range.startIndex, range.endIndex)
  }
  return {
    ...data,
    timeBySession,
    signalsBySession,
    events: filterRowsByTimeWindows(data.events, data, timeWindows, windowedSessions),
    metrics: filterRowsByTimeWindows(data.metrics, data, timeWindows, windowedSessions),
  }
}

function applyActivityMask(data: VisualizationData): VisualizationData {
  const signalsBySession: Record<string, Record<string, number[]>> = {}
  const timeBySession: Record<string, number[]> = {}
  let changed = false
  for (const [key, times] of Object.entries(data.timeBySession)) {
    const signals = data.signalsBySession[key] ?? {}
    const activeMask = activeMaskForSession(data, key)
    if (!activeMask || times.length === 0) {
      timeBySession[key] = times
      signalsBySession[key] = signals
      continue
    }
    const indexes = activeIndexes(activeMask, times.length)
    if (indexes.length === times.length) {
      timeBySession[key] = times
      signalsBySession[key] = signals
      continue
    }
    changed = true
    timeBySession[key] = indexes.map((index) => times[index])
    signalsBySession[key] = Object.fromEntries(
      Object.entries(signals).map(([role, values]) => [role, indexes.map((index) => values[index] ?? Number.NaN)]),
    )
  }
  for (const [key, signals] of Object.entries(data.signalsBySession)) {
    if (!signalsBySession[key]) {
      signalsBySession[key] = signals
    }
  }
  if (!changed) {
    return data
  }
  return {
    ...data,
    timeBySession,
    signalsBySession,
    events: filterRowsByActivity(data.events, data),
    metrics: filterRowsByActivity(data.metrics, data),
  }
}

function activeMaskForSession(data: VisualizationData, sessionKey: string): boolean[] | null {
  const cached = activeMaskCache.get(data)
  if (cached?.has(sessionKey)) {
    return cached.get(sessionKey) ?? null
  }
  const signals = data.signalsBySession[sessionKey]
  if (!signals) {
    cacheActiveMask(data, sessionKey, null)
    return null
  }
  for (const role of INACTIVE_MASK_ROLES) {
    const values = signals[role]
    if (hasUsableMask(values)) {
      const mask = values.map((value) => !maskValueTruthy(value))
      cacheActiveMask(data, sessionKey, mask)
      return mask
    }
  }
  for (const role of ACTIVE_MASK_ROLES) {
    const values = signals[role]
    if (hasUsableMask(values)) {
      const mask = values.map(maskValueTruthy)
      cacheActiveMask(data, sessionKey, mask)
      return mask
    }
  }
  cacheActiveMask(data, sessionKey, null)
  return null
}

function cacheActiveMask(data: VisualizationData, sessionKey: string, mask: boolean[] | null) {
  const cached = activeMaskCache.get(data)
  if (cached) {
    cached.set(sessionKey, mask)
  } else {
    activeMaskCache.set(data, new Map([[sessionKey, mask]]))
  }
}

function normalizedActivitySignalRole(column: string, role: string) {
  return ACTIVITY_SIGNAL_ROLES.has(column) ? column : role
}

function hasUsableMask(values: number[] | undefined) {
  return Boolean(values?.some(Number.isFinite))
}

function maskValueTruthy(value: number) {
  return Number.isFinite(value) && value !== 0
}

function activeIndexes(mask: boolean[], length: number) {
  const limit = Math.min(mask.length, length)
  const indexes: number[] = []
  for (let index = 0; index < limit; index += 1) {
    if (mask[index]) {
      indexes.push(index)
    }
  }
  return indexes
}

function filterRowsByActivity(rows: TableQueryRow[], data: VisualizationData) {
  return rows.filter((row) => rowActiveAtTrigger(row, data))
}

function rowActiveAtTrigger(row: TableQueryRow, data: VisualizationData) {
  const sessionKey = sessionRefId(row.sessionRef)
  const mask = activeMaskForSession(data, sessionKey)
  const times = data.timeBySession[sessionKey] ?? []
  if (!mask || times.length === 0) {
    return true
  }
  const triggerTimeS = rowPrimaryTriggerTimeS(row, data)
  if (triggerTimeS === null) {
    return true
  }
  const index = nearestTimeIndex(times, triggerTimeS)
  return index === null ? true : mask[index] ?? true
}

function nearestTimeIndex(times: number[], target: number) {
  if (times.length === 0 || !Number.isFinite(target)) {
    return null
  }
  if (!monotonicFiniteTimeArray(times)) {
    let bestIndex = -1
    let bestDelta = Number.POSITIVE_INFINITY
    for (let index = 0; index < times.length; index += 1) {
      const time = times[index]
      if (!Number.isFinite(time)) {
        continue
      }
      const delta = Math.abs(time - target)
      if (delta < bestDelta) {
        bestDelta = delta
        bestIndex = index
      }
    }
    return bestIndex < 0 ? null : bestIndex
  }
  const upperIndex = lowerBound(times, target)
  if (upperIndex <= 0) {
    return 0
  }
  if (upperIndex >= times.length) {
    return times.length - 1
  }
  const previousDelta = Math.abs(target - times[upperIndex - 1])
  const nextDelta = Math.abs(times[upperIndex] - target)
  return previousDelta <= nextDelta ? upperIndex - 1 : upperIndex
}

function inactiveIntervalsForSession(data: VisualizationData, sessionKey: string): ActivityInterval[] {
  const times = data.timeBySession[sessionKey] ?? []
  const mask = activeMaskForSession(data, sessionKey)
  if (!mask || times.length === 0) {
    return []
  }
  const intervals: ActivityInterval[] = []
  const limit = Math.min(mask.length, times.length)
  const step = typicalTimeStep(times)
  let startIndex: number | null = null
  for (let index = 0; index < limit; index += 1) {
    if (!mask[index] && startIndex === null) {
      startIndex = index
    }
    if ((mask[index] || index === limit - 1) && startIndex !== null) {
      const endIndex = mask[index] ? index - 1 : index
      const startS = times[startIndex]
      const endS = endIndex + 1 < times.length ? times[endIndex + 1] : times[endIndex] + step
      if (Number.isFinite(startS) && Number.isFinite(endS) && endS > startS) {
        intervals.push({ startS, endS })
      }
      startIndex = null
    }
  }
  return intervals
}

function typicalTimeStep(times: number[]) {
  const diffs: number[] = []
  for (let index = 1; index < times.length; index += 1) {
    const diff = times[index] - times[index - 1]
    if (Number.isFinite(diff) && diff > 0) {
      diffs.push(diff)
      if (diffs.length >= 60) {
        break
      }
    }
  }
  return d3.median(diffs) ?? 0.02
}

function timeWindowIndexRange(times: number[], window: TimeWindow) {
  if (times.length === 0) {
    return { startIndex: 0, endIndex: 0 }
  }
  if (!monotonicFiniteTimeArray(times)) {
    return linearTimeWindowIndexRange(times, window)
  }
  return {
    startIndex: lowerBound(times, window.startS),
    endIndex: upperBound(times, window.endS),
  }
}

function monotonicFiniteTimeArray(values: number[]) {
  const cached = monotonicTimeArrayCache.get(values)
  if (cached !== undefined) {
    return cached
  }
  const monotonic = isMonotonicFinite(values)
  monotonicTimeArrayCache.set(values, monotonic)
  return monotonic
}

function isMonotonicFinite(values: number[]) {
  let previous = Number.NEGATIVE_INFINITY
  for (const value of values) {
    if (!Number.isFinite(value) || value < previous) {
      return false
    }
    previous = value
  }
  return true
}

function linearTimeWindowIndexRange(times: number[], window: TimeWindow) {
  let startIndex = -1
  let endIndex = -1
  for (let index = 0; index < times.length; index += 1) {
    const time = times[index]
    if (!Number.isFinite(time) || time < window.startS || time > window.endS) {
      continue
    }
    if (startIndex < 0) {
      startIndex = index
    }
    endIndex = index + 1
  }
  return startIndex < 0 ? { startIndex: 0, endIndex: 0 } : { startIndex, endIndex }
}

function lowerBound(values: number[], target: number) {
  let low = 0
  let high = values.length
  while (low < high) {
    const mid = Math.floor((low + high) / 2)
    if (values[mid] < target) {
      low = mid + 1
    } else {
      high = mid
    }
  }
  return low
}

function upperBound(values: number[], target: number) {
  let low = 0
  let high = values.length
  while (low < high) {
    const mid = Math.floor((low + high) / 2)
    if (values[mid] <= target) {
      low = mid + 1
    } else {
      high = mid
    }
  }
  return low
}

function filterRowsByTimeWindows(
  rows: TableQueryRow[],
  data: VisualizationData,
  timeWindows: TimeWindowsBySession,
  windowedSessions: Set<string>,
) {
  const rowsBySession = rowsGroupedBySession(rows)
  const filteredRows: TableQueryRow[] = []
  for (const [sessionKey, sessionRows] of rowsBySession.entries()) {
    if (!windowedSessions.has(sessionKey)) {
      filteredRows.push(...sessionRows)
      continue
    }
    filteredRows.push(...tableRowsInTimeWindow(sessionRows, data, timeWindows[sessionKey]))
  }
  return filteredRows
}

function tableRowsInTimeWindow(rows: TableQueryRow[], data: VisualizationData, window: TimeWindow | undefined) {
  if (!window) {
    return rows
  }
  const timedRows = timedRowsForTableRows(rows, data)
  const startIndex = lowerBoundTimedRows(timedRows, window.startS)
  const endIndex = upperBoundTimedRows(timedRows, window.endS)
  return timedRows.slice(startIndex, endIndex).map((item) => item.row)
}

function timedRowsForTableRows(rows: TableQueryRow[], data: VisualizationData) {
  const cached = rowTimeIndexCache.get(rows)
  if (cached) {
    return cached
  }
  const timedRows: TimedTableRow[] = []
  for (const row of rows) {
    const triggerTimeS = rowPrimaryTriggerTimeS(row, data)
    if (triggerTimeS !== null) {
      timedRows.push({ row, triggerTimeS })
    }
  }
  timedRows.sort((a, b) => a.triggerTimeS - b.triggerTimeS)
  rowTimeIndexCache.set(rows, timedRows)
  return timedRows
}

function lowerBoundTimedRows(values: TimedTableRow[], target: number) {
  let low = 0
  let high = values.length
  while (low < high) {
    const mid = Math.floor((low + high) / 2)
    if (values[mid].triggerTimeS < target) {
      low = mid + 1
    } else {
      high = mid
    }
  }
  return low
}

function upperBoundTimedRows(values: TimedTableRow[], target: number) {
  let low = 0
  let high = values.length
  while (low < high) {
    const mid = Math.floor((low + high) / 2)
    if (values[mid].triggerTimeS <= target) {
      low = mid + 1
    } else {
      high = mid
    }
  }
  return low
}

function sessionDurationS(data: VisualizationData, sessionRef: StudySessionRef, session: SessionRecord | null) {
  const key = sessionRefId(sessionRef)
  const extent = finiteExtent(data.timeBySession[key] ?? [])
  if (extent.count > 0) {
    return extent.max
  }
  return session && Number.isFinite(session.durationMin) ? Math.max(0, session.durationMin * 60) : 0
}

function sanitizeTimeWindow(window: TimeWindow, durationS: number, minWindowS: number) {
  if (durationS <= 0) {
    return { startS: 0, endS: 0 }
  }
  const startS = clamp(Math.min(window.startS, window.endS), 0, durationS)
  const endS = clamp(Math.max(window.startS, window.endS), 0, durationS)
  if (endS - startS >= minWindowS) {
    return { startS, endS }
  }
  const expandedEnd = clamp(startS + minWindowS, 0, durationS)
  if (expandedEnd - startS >= minWindowS) {
    return { startS, endS: expandedEnd }
  }
  return { startS: Math.max(0, durationS - minWindowS), endS: durationS }
}

function overviewPoints(times: number[], values: number[], maxPoints: number) {
  const limit = Math.min(times.length, values.length)
  const stride = Math.max(1, Math.ceil(limit / maxPoints))
  const points: Array<{ timeS: number; value: number }> = []
  for (let index = 0; index < limit; index += stride) {
    const timeS = times[index]
    const value = values[index]
    if (Number.isFinite(timeS) && Number.isFinite(value)) {
      points.push({ timeS, value })
    }
  }
  return points
}

function normalizeSignalTimes(values: number[]) {
  const extent = finiteExtent(values)
  if (extent.count === 0 || extent.first === null) {
    return values
  }
  const span = extent.max - extent.min
  const scale =
    span > 86_400 * 1_000_000 ? 1 / 1_000_000_000 : span > 86_400 * 1_000 ? 1 / 1_000_000 : span > 86_400 ? 1 / 1000 : 1
  const offset = extent.first * scale
  return values.map((value) => (Number.isFinite(value) ? value * scale - offset : Number.NaN))
}

function entitySignalValues(entity: VisualizationEntity, data: VisualizationData, role: string) {
  if (entity.sessionRefs.length === 1) {
    return data.signalsBySession[sessionRefId(entity.sessionRefs[0])]?.[role] ?? []
  }
  const key = `${entityCacheKey(entity)}|${role}`
  const cached = entitySignalValuesCache.get(data)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const values: number[] = []
  for (const sessionRef of entity.sessionRefs) {
    const sessionValues = data.signalsBySession[sessionRefId(sessionRef)]?.[role] ?? []
    values.push(...sessionValues)
  }
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(key, values)
  if (!cached) {
    entitySignalValuesCache.set(data, nextCache)
  }
  return values
}

function rowsGroupedBySession(rows: TableQueryRow[]) {
  const cached = rowSessionGroupCache.get(rows)
  if (cached) {
    return cached
  }
  const grouped = new Map<string, TableQueryRow[]>()
  for (const row of rows) {
    const key = sessionRefId(row.sessionRef)
    const current = grouped.get(key)
    if (current) {
      current.push(row)
    } else {
      grouped.set(key, [row])
    }
  }
  rowSessionGroupCache.set(rows, grouped)
  return grouped
}

function entityRows(entity: VisualizationEntity, rows: TableQueryRow[]) {
  const key = entityCacheKey(entity)
  const cached = entityRowsCache.get(rows)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const grouped = rowsGroupedBySession(rows)
  const out =
    entity.sessionRefs.length === 1
      ? grouped.get(sessionRefId(entity.sessionRefs[0])) ?? []
      : entity.sessionRefs.flatMap((sessionRef) => grouped.get(sessionRefId(sessionRef)) ?? [])
  const nextCache = cached ?? new Map<string, TableQueryRow[]>()
  nextCache.set(key, out)
  if (!cached) {
    entityRowsCache.set(rows, nextCache)
  }
  return out
}

function entityCacheKey(entity: VisualizationEntity) {
  return `${entity.id}|${entity.sessionRefs.map(sessionRefId).join(',')}`
}

function percentValues(values: number[]) {
  const cached = percentValuesCache.get(values)
  if (cached) {
    return cached
  }
  const out = values.map((value) => (Number.isFinite(value) ? value * 100 : Number.NaN))
  percentValuesCache.set(values, out)
  return out
}

function metricSpecCacheKey(metricSpec: MirroredMetricSpec) {
  return `${metricSpec.compressionMetricName}|${metricSpec.reboundMetricName}`
}

function metricMirroredValuesForEntityEnd(
  entity: VisualizationEntity,
  data: VisualizationData,
  end: SuspensionEnd,
  metricSpec: MirroredMetricSpec,
) {
  return metricMirroredValuesForRows(entityRows(entity, data.metrics), end, metricSpec)
}

function metricMirroredValuesForRows(rows: TableQueryRow[], end: SuspensionEnd, metricSpec: MirroredMetricSpec) {
  const key = `${end}|${metricSpecCacheKey(metricSpec)}`
  const cached = metricMirroredValueCache.get(rows)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const values: number[] = []
  for (const row of rows) {
    if (row.signalRole !== end) {
      continue
    }
    if (eventTypeMatches(row.eventType, COMPRESSION_EVENT_TYPE)) {
      const metricValue = numericField(row.fields[metricSpec.compressionMetricName])
      if (Number.isFinite(metricValue)) {
        values.push(Math.abs(metricValue))
      }
    } else if (eventTypeMatches(row.eventType, REBOUND_EVENT_TYPE)) {
      const metricValue = numericField(row.fields[metricSpec.reboundMetricName])
      if (Number.isFinite(metricValue)) {
        values.push(-Math.abs(metricValue))
      }
    }
  }
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(key, values)
  if (!cached) {
    metricMirroredValueCache.set(rows, nextCache)
  }
  return values
}

function metricMagnitudeCandidateDomainFromRows(
  entities: VisualizationEntity[],
  roles: DistributionRole[],
  rowsForEntity: (entity: VisualizationEntity) => TableQueryRow[],
  metricSpec: MirroredMetricSpec,
  candidates: number[],
): [number, number] {
  const values = entities.flatMap((entity) =>
    roles.flatMap((role) => metricMirroredValuesForRows(rowsForEntity(entity), role.key, metricSpec).map((value) => Math.abs(value))),
  )
  return candidateDomainContainingP95(values, candidates)
}

function metricMagnitudeCandidateDomain(
  entities: VisualizationEntity[],
  data: VisualizationData,
  ends: SuspensionEnd[],
  metricSpec: MirroredMetricSpec,
  candidates: number[],
): [number, number] {
  const values = entities.flatMap((entity) =>
    ends.flatMap((end) => metricMirroredValuesForEntityEnd(entity, data, end, metricSpec).map((value) => Math.abs(value))),
  )
  return candidateDomainContainingP95(values, candidates)
}

function candidateDomainContainingP95(values: number[], candidates: number[]): [number, number] {
  const limits = [...candidates].filter(Number.isFinite).sort((a, b) => a - b)
  const fallback = limits[0] ?? 1
  const clean = values.filter(Number.isFinite).sort((a, b) => a - b)
  if (clean.length === 0) {
    return [0, fallback]
  }
  const p95 = quantile(clean, 0.95) ?? 0
  return [0, limits.find((limit) => p95 <= limit) ?? limits[limits.length - 1] ?? fallback]
}

function distributionRoles(frontRole: string, rearRole: string, selectedEnds: SuspensionEnd[]): DistributionRole[] {
  const roles: DistributionRole[] = [
    { key: 'front', label: 'Front', signalRole: frontRole, color: FRONT_COLOR },
    { key: 'rear', label: 'Rear', signalRole: rearRole, color: REAR_COLOR },
  ]
  return roles.filter((role) => selectedEnds.includes(role.key))
}

function distributionYMax(
  entities: VisualizationEntity[],
  roles: DistributionRole[],
  valueForEntityRole: (entity: VisualizationEntity, role: DistributionRole) => number[],
  xDomain: [number, number],
  bins: number,
  chartKind: DistributionChartKind,
) {
  let yMax = 0
  for (const entity of entities) {
    for (const role of roles) {
      const values = valueForEntityRole(entity, role)
      if (chartKind === 'mirrored_velocity') {
        const mirrored = mirroredVelocityBins(values, xDomain, bins)
        for (const bin of [...mirrored.compression, ...mirrored.rebound]) {
          yMax = Math.max(yMax, bin.proportion)
        }
      } else {
        for (const bin of histogramBins(values, xDomain, bins)) {
          yMax = Math.max(yMax, bin.proportion)
        }
      }
    }
  }
  return yMax || 1
}

function mirroredVelocityBins(values: number[], xDomain: [number, number], bins: number): MirroredHistogramBins {
  const key = histogramCacheKey(xDomain, bins)
  const cached = mirroredHistogramBinCache.get(values)
  if (cached?.has(key)) {
    return cached.get(key) ?? { compression: [], rebound: [] }
  }
  const compressionValues: number[] = []
  const reboundValues: number[] = []
  for (const value of values) {
    if (!Number.isFinite(value)) {
      continue
    }
    if (value >= 0) {
      compressionValues.push(value)
    } else {
      reboundValues.push(-value)
    }
  }
  const mirrored = {
    compression: histogramBins(compressionValues, xDomain, bins),
    rebound: histogramBins(reboundValues, xDomain, bins),
  }
  const nextCache = cached ?? new Map<string, MirroredHistogramBins>()
  nextCache.set(key, mirrored)
  if (!cached) {
    mirroredHistogramBinCache.set(values, nextCache)
  }
  return mirrored
}

function histogramBins(values: number[], xDomain: [number, number], bins: number): HistogramBin[] {
  const key = histogramCacheKey(xDomain, bins)
  const cached = histogramBinCache.get(values)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const clean = values.filter((value) => Number.isFinite(value) && value >= xDomain[0] && value <= xDomain[1])
  const generator = d3.bin().domain(xDomain).thresholds(bins)
  const out = generator(clean).map((bin) => ({
    x0: bin.x0 ?? xDomain[0],
    x1: bin.x1 ?? xDomain[1],
    count: bin.length,
    total: clean.length,
    proportion: clean.length ? bin.length / clean.length : 0,
  }))
  const nextCache = cached ?? new Map<string, HistogramBin[]>()
  nextCache.set(key, out)
  if (!cached) {
    histogramBinCache.set(values, nextCache)
  }
  return out
}

function histogramCacheKey(xDomain: [number, number], bins: number) {
  return `${xDomain[0]}|${xDomain[1]}|${bins}`
}

function scatterPanelExtent(
  entities: VisualizationEntity[],
  eventType: string,
  xMetric: string,
  yMetric: string,
  ends: SuspensionEnd[],
  rowsForEntity: (entity: VisualizationEntity) => TableQueryRow[],
) {
  const points = entities.flatMap((entity) =>
    scatterPoints(rowsForEntity(entity), eventType, xMetric, yMetric).filter(
      (point) => point.role !== 'unknown' && ends.includes(point.role),
    ),
  )
  return {
    x: paddedExtent(points.map((point) => point.x), [0, 100]),
    y: paddedExtent(points.map((point) => point.y), [-1500, 1500]),
  }
}

function scatterPoints(rows: TableQueryRow[], eventType: string, xMetric: string, yMetric: string): ScatterPoint[] {
  const key = `${eventType}|${xMetric}|${yMetric}`
  const cached = scatterPointCache.get(rows)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const points: ScatterPoint[] = []
  for (const row of rows) {
    if (!eventTypeMatches(row.eventType, eventType)) {
      continue
    }
    const x = numericField(row.fields[xMetric])
    const y = numericField(row.fields[yMetric])
    if (Number.isFinite(x) && Number.isFinite(y)) {
      points.push({ x, y, role: row.signalRole })
    }
  }
  const nextCache = cached ?? new Map<string, ScatterPoint[]>()
  nextCache.set(key, points)
  if (!cached) {
    scatterPointCache.set(rows, nextCache)
  }
  return points
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

function sectorValuesForEntity(
  entity: VisualizationEntity,
  data: VisualizationData,
  track: TrackRecord,
  sector: TrackSector,
  role: string,
) {
  const key = `${entityCacheKey(entity)}|${trackObjectId(track)}|${sector.id}|${role}`
  const cached = sectorValuesForEntityCache.get(data)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const values: number[] = []
  for (const sessionRef of entity.sessionRefs) {
    values.push(...sectorValuesForSession(sessionRef, data, track, sector, role))
  }
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(key, values)
  if (!cached) {
    sectorValuesForEntityCache.set(data, nextCache)
  }
  return values
}

function sectorValuesForEntityAcrossSectors(
  entity: VisualizationEntity,
  data: VisualizationData,
  track: TrackRecord,
  sectors: TrackSector[],
  role: string,
) {
  const key = `${entityCacheKey(entity)}|${trackObjectId(track)}|${sectors.map((sector) => sector.id).join(',')}|${role}`
  const cached = sectorValuesForEntityCache.get(data)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const values: number[] = []
  for (const sector of sectors) {
    values.push(...sectorValuesForEntity(entity, data, track, sector, role))
  }
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(key, values)
  if (!cached) {
    sectorValuesForEntityCache.set(data, nextCache)
  }
  return values
}

function rowsInSectorsForEntity(
  entity: VisualizationEntity,
  rows: TableQueryRow[],
  data: VisualizationData,
  track: TrackRecord,
  sectors: TrackSector[],
) {
  const key = `${entityCacheKey(entity)}|${trackObjectId(track)}|${sectors.map((sector) => sector.id).join(',')}`
  const cached = rowsInSectorsForEntityCache.get(rows)
  if (cached?.has(key)) {
    return cached.get(key) ?? []
  }
  const sectorIntervalsBySession = sectorIntervalsForEntity(entity, track, sectors)
  const filtered = entityRows(entity, rows).filter((row) => rowInAnySectorInterval(row, data, sectorIntervalsBySession))
  const nextCache = cached ?? new Map<string, TableQueryRow[]>()
  nextCache.set(key, filtered)
  if (!cached) {
    rowsInSectorsForEntityCache.set(rows, nextCache)
  }
  return filtered
}

function sectorIntervalsForEntity(entity: VisualizationEntity, track: TrackRecord, sectors: TrackSector[]) {
  const intervalsBySession = new Map<string, Array<SectorInterval & { endInclusive: boolean }>>()
  for (const sessionRef of entity.sessionRefs) {
    const sessionIntervals: Array<SectorInterval & { endInclusive: boolean }> = []
    for (const sector of sectors) {
      const interval = sectorTimeInterval(track, sessionRef, sector)
      if (interval) {
        sessionIntervals.push({ ...interval, endInclusive: isLastSector(track, sector) })
      }
    }
    intervalsBySession.set(sessionRefId(sessionRef), sessionIntervals)
  }
  return intervalsBySession
}

function rowInAnySectorInterval(
  row: TableQueryRow,
  data: VisualizationData,
  intervalsBySession: Map<string, Array<SectorInterval & { endInclusive: boolean }>>,
) {
  const intervals = intervalsBySession.get(sessionRefId(row.sessionRef))
  if (!intervals || intervals.length === 0) {
    return false
  }
  const triggerTimeS = rowPrimaryTriggerTimeS(row, data)
  if (triggerTimeS === null) {
    return false
  }
  return intervals.some(
    (interval) =>
      triggerTimeS >= interval.startS &&
      (interval.endInclusive ? triggerTimeS <= interval.endS : triggerTimeS < interval.endS),
  )
}

function rowPrimaryTriggerTimeS(row: TableQueryRow, data: VisualizationData) {
  const direct = firstNumericField(
    row.fields.trigger_time_s,
    row.fields.primary_trigger_time_s,
    row.fields.t0_time,
    row.fields.time_s,
  )
  if (direct !== null) {
    return direct
  }
  const key = tableRowEventKey(row)
  if (!key) {
    return null
  }
  const fallbackTriggerTimeS = data.eventTriggerTimeByKey[key]
  return typeof fallbackTriggerTimeS === 'number' && Number.isFinite(fallbackTriggerTimeS) ? fallbackTriggerTimeS : null
}

function tableRowEventKey(row: TableQueryRow) {
  const eventId = textField(row.fields.event_id)
  if (!eventId) {
    return ''
  }
  const schemaId = textField(row.fields.schema_id) || row.setId || row.eventType
  return `${sessionRefId(row.sessionRef)}|${schemaId}|${eventId}`
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
  const cacheKey = `${key}|${trackObjectId(track)}|${sector.id}|${role}|${interval.startS}|${interval.endS}|${endInclusive}`
  const cached = sectorValuesForSessionCache.get(data)
  if (cached?.has(cacheKey)) {
    return cached.get(cacheKey) ?? []
  }
  const limit = Math.min(values.length, times.length)
  const sectorValues = bestSectorValues(times, values, limit, interval, endInclusive)
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(cacheKey, sectorValues)
  if (!cached) {
    sectorValuesForSessionCache.set(data, nextCache)
  }
  return sectorValues
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
  const key = `${sessionRefId(sessionRef)}|${sector.id}`
  const cached = sectorIntervalCache.get(track)
  if (cached?.has(key)) {
    return cached.get(key) ?? null
  }
  const match = trackMatchForSession(track, sessionRef)
  if (!match || !['matched', 'partial', 'ambiguous'].includes(match.status)) {
    cacheSectorInterval(track, key, null)
    return null
  }
  const start = crossingTime(match, sector.startTrackpoint.id)
  const end = crossingTime(match, sector.endTrackpoint.id)
  if (start === null || end === null || start === end) {
    cacheSectorInterval(track, key, null)
    return null
  }
  const interval = {
    startS: Math.min(start, end),
    endS: Math.max(start, end),
  }
  cacheSectorInterval(track, key, interval)
  return interval
}

function cacheSectorInterval(track: TrackRecord, key: string, interval: SectorInterval | null) {
  const cached = sectorIntervalCache.get(track)
  if (cached) {
    cached.set(key, interval)
  } else {
    sectorIntervalCache.set(track, new Map([[key, interval]]))
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
  let lastSectorId = lastSectorIdCache.get(track)
  if (lastSectorId === undefined) {
    const sectors = trackSectors(track)
    lastSectorId = sectors[sectors.length - 1]?.id ?? null
    lastSectorIdCache.set(track, lastSectorId)
  }
  return lastSectorId === sector.id
}

function trackObjectId(track: TrackRecord) {
  const cached = trackObjectIdCache.get(track)
  if (cached !== undefined) {
    return cached
  }
  const next = nextTrackObjectId
  nextTrackObjectId += 1
  trackObjectIdCache.set(track, next)
  return next
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

function uniqueStrings(values: string[]) {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of values) {
    if (!value || seen.has(value)) {
      continue
    }
    seen.add(value)
    out.push(value)
  }
  return out
}

function distributionStats(values: number[]) {
  const clean = [...values].filter(Number.isFinite).sort((a, b) => a - b)
  const q25 = quantile(clean, 0.25)
  const median = quantile(clean, 0.5)
  const q75 = quantile(clean, 0.75)
  const iqr = q25 !== null && q75 !== null ? q75 - q25 : null
  return {
    mean: clean.length ? d3.mean(clean) ?? null : null,
    median,
    p95: quantile(clean, 0.95),
    max: clean.length ? clean[clean.length - 1] : null,
    iqr,
    skew: iqr && iqr !== 0 && q25 !== null && q75 !== null && median !== null ? (q75 + q25 - 2 * median) / iqr : null,
  }
}

function quantile(values: number[], q: number) {
  if (values.length === 0) {
    return null
  }
  return d3.quantileSorted(values, q) ?? null
}

function finiteExtent(values: number[]) {
  let min = Number.POSITIVE_INFINITY
  let max = Number.NEGATIVE_INFINITY
  let first: number | null = null
  let count = 0
  for (const value of values) {
    if (!Number.isFinite(value)) {
      continue
    }
    if (first === null) {
      first = value
    }
    min = Math.min(min, value)
    max = Math.max(max, value)
    count += 1
  }
  return { count, first, min, max }
}

function paddedExtent(values: number[], fallback: [number, number]): [number, number] {
  const extent = finiteExtent(values)
  if (extent.count === 0) {
    return fallback
  }
  const { min, max } = extent
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

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function firstNumericField(...values: unknown[]) {
  for (const value of values) {
    const numeric = numericField(value)
    if (Number.isFinite(numeric)) {
      return numeric
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) {
        return parsed
      }
    }
  }
  return null
}

function textField(value: unknown) {
  if (typeof value === 'string' && value.trim()) {
    return value.trim()
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  return ''
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
  return entity.color || ENTITY_SERIES_COLORS[index % ENTITY_SERIES_COLORS.length] || UNKNOWN_COLOR
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

function activitySignalWarning(warning: Record<string, unknown>) {
  const role = textField(warning.role) || textField(warning.signal_role) || textField(warning.requested_role)
  const column = textField(warning.column) || textField(warning.requested_column)
  return ACTIVITY_SIGNAL_ROLES.has(role) || ACTIVITY_SIGNAL_ROLES.has(column)
}

function formatPercentValue(value: number | null) {
  return value === null ? '-' : `${value.toFixed(0)}%`
}

function formatMetricValue(value: number | null) {
  if (value === null) {
    return '-'
  }
  if (Math.abs(value) >= 100) {
    return value.toFixed(0)
  }
  return value.toFixed(1)
}

function formatMetricValueWithUnit(unit: string) {
  return (value: number | null) => (value === null ? '-' : `${formatMetricValue(value)} ${unit}`)
}

function formatSkew(value: number | null) {
  return value === null || !Number.isFinite(value) ? '-' : value.toFixed(2)
}

function formatProportion(value: number) {
  return `${(value * 100).toFixed(1)}%`
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

function formatTimeOffset(value: number) {
  if (!Number.isFinite(value)) {
    return '-'
  }
  if (value >= 3600) {
    const hours = Math.floor(value / 3600)
    const minutes = Math.floor((value % 3600) / 60)
    return `${hours}h ${minutes.toString().padStart(2, '0')}m`
  }
  if (value >= 60) {
    const minutes = Math.floor(value / 60)
    const seconds = Math.round(value % 60)
    return `${minutes}:${seconds.toString().padStart(2, '0')}`
  }
  return `${value.toFixed(value < 10 ? 1 : 0)}s`
}

function timeWindowTicks(durationS: number) {
  const max = Math.max(0, durationS)
  const ticks: Array<{ value: number; label: boolean }> = []
  for (let value = 0; value <= max + 0.0001; value += 10) {
    ticks.push({
      value: Math.min(value, max),
      label: shouldLabelTimeTick(value, max),
    })
  }
  if (max > 0 && (ticks.length === 0 || Math.abs(ticks[ticks.length - 1].value - max) > 0.001)) {
    ticks.push({ value: max, label: true })
  }
  return ticks
}

function shouldLabelTimeTick(value: number, durationS: number) {
  if (value === 0 || Math.abs(value - durationS) < 0.001) {
    return true
  }
  if (durationS <= 120) {
    return true
  }
  if (durationS <= 600) {
    return value % 30 === 0
  }
  return value % 60 === 0
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
