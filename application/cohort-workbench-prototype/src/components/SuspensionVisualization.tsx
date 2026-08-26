import { memo, useDeferredValue, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent, type ReactNode } from 'react'
import * as d3 from 'd3'
import { Activity, ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import {
  finishSuspensionCacheDiagnostics,
  getSuspensionCacheEntry,
  getSuspensionComposedCacheEntry,
  setSuspensionCacheEntry,
  setSuspensionComposedCacheEntry,
  startSuspensionCacheDiagnostics,
  suspensionCacheLoadMessage,
  suspensionCacheNowMs,
  suspensionSessionCache,
  type SuspensionCacheDiagnostics,
} from '../data/SuspensionAnalysisCache'
import { sessionByRef, sessionRefId } from '../domain/studySets'
import type {
  SessionRecord,
  SessionBookmarkRecord,
  SessionSignalSummary,
  SignalQuerySignal,
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
const DISPLACEMENT_MM_DOMAIN_LIMITS = [100, 120, 150, 180, 200, 250]
const WHOLE_SESSION_DISTRIBUTION_BINS = 20
const SECTOR_DISTRIBUTION_BINS = 15
const CUMULATIVE_DISTRIBUTION_MAX_POINTS = 900
const PHASE_SCATTER_MAX_POINTS = 24_000
const PHASE_LINE_TARGET_HZ = 200
const PHASE_LINE_MAX_POINTS = 100_000
const PHASE_CANVAS_RAW_POINT_LIMIT = 250_000
const PHASE_DISPLACEMENT_MM_BOUNDS = [-10, 250] as const
const PHASE_DISPLACEMENT_NORMALIZED_BOUNDS = [-5, 105] as const
const PHASE_VELOCITY_BOUNDS = [-5000, 10000] as const
const PHASE_DISPLACEMENT_AXIS_STEP = 0.1
const PHASE_VELOCITY_AXIS_STEP = 10
const PHASE_DEFAULT_CONDITIONAL_DISTRIBUTION_BINS = 60
const PHASE_CONDITIONAL_LOWER_QUANTILE = 0.001
const PHASE_CONDITIONAL_UPPER_QUANTILE = 0.999
const PHASE_CONTOUR_MASS_OPTIONS = [0.5, 0.8, 0.95, 0.99, 0.999] as const
const PHASE_DEFAULT_CONTOUR_MASSES = [0.5, 0.8, 0.95]
const VISUALIZATION_SESSION_CACHE_VERSION = 3
const VELOCITY_STATS_FORMATTER = formatMetricValueWithUnit('mm/s')
const STROKE_LENGTH_STATS_FORMATTER = formatMetricValueWithUnit('mm')
const DISPLACEMENT_MM_STATS_FORMATTER = formatMetricValueWithUnit('mm')

const SIGNAL_REQUESTS: SignalQuerySignalRequest[] = [
  { role: 'activity_mask', selector: { kind: 'qc', quantity: 'mask' } },
]
const NORMALIZED_DISPLACEMENT_SIGNAL_ROLE_CONFIGS = [
  {
    role: 'front_displacement',
    label: 'Front wheel displacement',
    end: 'front',
    unitMode: 'normalized',
    selector: { end: 'front', domain: 'wheel', quantity: 'disp_norm', unit: '1' },
  },
  {
    role: 'rear_displacement',
    label: 'Rear wheel displacement',
    end: 'rear',
    unitMode: 'normalized',
    selector: { end: 'rear', domain: 'wheel', quantity: 'disp_norm', unit: '1' },
  },
] as const
const MM_DISPLACEMENT_SIGNAL_ROLE_CONFIGS = [
  {
    role: 'front_displacement_mm',
    label: 'Front wheel displacement',
    end: 'front',
    unitMode: 'mm',
    selector: { end: 'front', domain: 'wheel', quantity: 'disp', unit: 'mm' },
  },
  {
    role: 'rear_displacement_mm',
    label: 'Rear wheel displacement',
    end: 'rear',
    unitMode: 'mm',
    selector: { end: 'rear', domain: 'wheel', quantity: 'disp', unit: 'mm' },
  },
] as const
const VELOCITY_SIGNAL_ROLE_CONFIGS = [
  {
    role: 'front_velocity',
    label: 'Front wheel velocity',
    end: 'front',
    selector: { end: 'front', domain: 'wheel', quantity: 'vel', unit: 'mm/s' },
  },
  {
    role: 'rear_velocity',
    label: 'Rear wheel velocity',
    end: 'rear',
    selector: { end: 'rear', domain: 'wheel', quantity: 'vel', unit: 'mm/s' },
  },
] as const
const DISPLACEMENT_SIGNAL_ROLE_CONFIGS = [
  ...NORMALIZED_DISPLACEMENT_SIGNAL_ROLE_CONFIGS,
  ...MM_DISPLACEMENT_SIGNAL_ROLE_CONFIGS,
] as const
const NORMALIZED_DISPLACEMENT_SIGNAL_ROLES = new Set<string>(NORMALIZED_DISPLACEMENT_SIGNAL_ROLE_CONFIGS.map((config) => config.role))
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
  | { status: 'idle'; message: string; data?: VisualizationData; diagnostics?: SuspensionCacheDiagnostics }
  | { status: 'loading'; message: string; data?: VisualizationData; diagnostics?: SuspensionCacheDiagnostics }
  | { status: 'ready'; message: string; data: VisualizationData; diagnostics: SuspensionCacheDiagnostics }
  | { status: 'error'; message: string; data?: VisualizationData; diagnostics?: SuspensionCacheDiagnostics }

type ComparisonLayout = 'entities' | 'ends'
type ScopeMode = 'whole_session' | 'sector'
type SuspensionEnd = 'front' | 'rear'
type PhaseAxisRange = [number, number]
type SuspensionVisualizationMode = 'simple' | 'phase'
type PhaseRenderMode = 'density' | 'scatter' | 'line'
type PhaseChartVariant = 'phase' | 'contours' | 'velocity_given_position' | 'position_given_velocity'
type DistributionChartKind = 'histogram' | 'mirrored_velocity'
type FrequencyDisplayMode = 'histogram' | 'cumulative'
type DisplacementGlyphPlacement = 'top' | 'bottom'
type DisplacementUnitMode = 'normalized' | 'mm'
type DistributionStatsMode = 'basic' | 'displacement'
type MirroredMetricSpec = { compressionMetricName: string; reboundMetricName: string }
type TimeWindow = { startS: number; endS: number }
type TimeWindowsBySession = Record<string, TimeWindow>
type DisplacementSignalRole = (typeof DISPLACEMENT_SIGNAL_ROLE_CONFIGS)[number]['role']
type DisplacementSignalRoleConfig = (typeof DISPLACEMENT_SIGNAL_ROLE_CONFIGS)[number]
type SignalChoiceSelections = Record<string, string>
type FrequencyDisplayModes = {
  displacement: FrequencyDisplayMode
  velocity: FrequencyDisplayMode
  strokeLength: FrequencyDisplayMode
}

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
  signalChoices: SignalChoiceSelections
  frequencyDisplayModes: FrequencyDisplayModes
  showDisplacementMm: boolean
  showDisplacementStatsOnChart: boolean
  showVelocityStatsOnChart: boolean
  showStrokeLengthStatsOnChart: boolean
  phaseDensityBins: number
  phaseContourMasses: number[]
  phaseConditionalBins: number
  phaseRenderMode: PhaseRenderMode
  phaseMarkOpacity: number
  phaseScatterMarkSize: number
  phaseShowGridlines: boolean
  phaseXAxisAuto: boolean
  phaseYAxisAuto: boolean
  phaseXAxisRange: PhaseAxisRange
  phaseYAxisRange: PhaseAxisRange
  phasePositionConditionMm: PhaseAxisRange
  phasePositionConditionNormalized: PhaseAxisRange
  phaseVelocityCondition: PhaseAxisRange
}

const DEFAULT_FREQUENCY_DISPLAY_MODES: FrequencyDisplayModes = {
  displacement: 'histogram',
  velocity: 'histogram',
  strokeLength: 'histogram',
}

type CachedSessionVisualizationData = {
  sessionRef: StudySessionRef
  time: number[]
  signals: Record<string, number[]>
  events: TableQueryRow[]
  metrics: TableQueryRow[]
  warnings: string[]
}

type VisualizationLoadResult = {
  data: VisualizationData
  diagnostics: SuspensionCacheDiagnostics
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

type ConditionalHistogram = {
  bins: HistogramBin[]
  underflowCount: number
  overflowCount: number
  total: number
}

type CumulativeDistributionPoint = {
  x: number
  proportion: number
}

type CumulativeDistribution = {
  points: CumulativeDistributionPoint[]
  sortedValues: number[]
  sampleCount: number
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
const monotonicTimeArrayCache = new WeakMap<number[], boolean>()
const rowTimeIndexCache = new WeakMap<TableQueryRow[], TimedTableRow[]>()
const entitySignalValuesCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const rowSessionGroupCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const entityRowsCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const metricMirroredValueCache = new WeakMap<TableQueryRow[], Map<string, number[]>>()
const histogramBinCache = new WeakMap<number[], Map<string, HistogramBin[]>>()
const mirroredHistogramBinCache = new WeakMap<number[], Map<string, MirroredHistogramBins>>()
const cumulativeDistributionCache = new WeakMap<number[], Map<string, CumulativeDistribution>>()
const scatterPointCache = new WeakMap<TableQueryRow[], Map<string, ScatterPoint[]>>()
const sectorValuesForSessionCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const sectorValuesForEntityCache = new WeakMap<VisualizationData, Map<string, number[]>>()
const rowsInSectorsForEntityCache = new WeakMap<TableQueryRow[], Map<string, TableQueryRow[]>>()
const percentValuesCache = new WeakMap<number[], number[]>()
const sectorIntervalCache = new WeakMap<TrackRecord, Map<string, SectorInterval | null>>()
const lastSectorIdCache = new WeakMap<TrackRecord, string | null>()
const trackObjectIdCache = new WeakMap<TrackRecord, number>()
const activeMaskCache = new WeakMap<VisualizationData, Map<string, boolean[] | null>>()
const VISUALIZATION_SETTINGS_STORAGE_PREFIX = 'bodaqs.suspension-visualization.settings.'
let nextTrackObjectId = 1

type TrackSector = {
  id: string
  label: string
  order: number
  startTrackpoint: TrackpointRecord
  endTrackpoint: TrackpointRecord
  lengthM: number
}

type SignalChoiceGroup = {
  key: string
  role: DisplacementSignalRole
  roleLabel: string
  sessionLabel: string
  selectedColumn: string
  candidates: SessionSignalSummary[]
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
  bookmarkRefreshToken = 0,
  onInspectSignals,
  mode = 'simple',
}: {
  studySet: StudySet
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
  bookmarkRefreshToken?: number
  onInspectSignals?: (sessionRef: StudySessionRef, window: TimeWindow) => void
  mode?: SuspensionVisualizationMode
}) {
  const entities = useMemo(() => visualizationEntities(studySet), [studySet])
  const baseStudySetTracks = useMemo(() => tracks.filter((track) => studySet.trackIds.includes(track.id)), [studySet.trackIds, tracks])
  const [visualizationTrackMatches, setVisualizationTrackMatches] = useState<SessionTrackMatchRecord[] | null>(null)
  const [visualizationTrackMatchesLoading, setVisualizationTrackMatchesLoading] = useState(false)
  const studySetTracks = useMemo(() => mergeTrackMatches(baseStudySetTracks, visualizationTrackMatches), [baseStudySetTracks, visualizationTrackMatches])
  const studySetTrackKey = studySetTracks.map((track) => `${track.id}:${track.revision}`).join('|')
  const studySetKey = stableStudySetKey(studySet)
  const trackMatchKey = stableTrackMatchKey(studySet)
  const settingsCacheKey = visualizationSettingsKey(studySet, mode)
  const initialSettings = restoredVisualizationSettings(settingsCacheKey, entities, studySetTracks, mode)
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
  const [signalChoices, setSignalChoices] = useState<SignalChoiceSelections>(initialSettings.signalChoices)
  const [frequencyDisplayModes, setFrequencyDisplayModes] = useState<FrequencyDisplayModes>(initialSettings.frequencyDisplayModes)
  const [showDisplacementMm, setShowDisplacementMm] = useState(initialSettings.showDisplacementMm)
  const [showDisplacementStatsOnChart, setShowDisplacementStatsOnChart] = useState(initialSettings.showDisplacementStatsOnChart)
  const [showVelocityStatsOnChart, setShowVelocityStatsOnChart] = useState(initialSettings.showVelocityStatsOnChart)
  const [showStrokeLengthStatsOnChart, setShowStrokeLengthStatsOnChart] = useState(initialSettings.showStrokeLengthStatsOnChart)
  const [phaseDensityBins, setPhaseDensityBins] = useState(initialSettings.phaseDensityBins)
  const [phaseContourMasses, setPhaseContourMasses] = useState(initialSettings.phaseContourMasses)
  const [phaseConditionalBins, setPhaseConditionalBins] = useState(initialSettings.phaseConditionalBins)
  const [phaseRenderMode, setPhaseRenderMode] = useState(initialSettings.phaseRenderMode)
  const [phaseMarkOpacity, setPhaseMarkOpacity] = useState(initialSettings.phaseMarkOpacity)
  const [phaseScatterMarkSize, setPhaseScatterMarkSize] = useState(initialSettings.phaseScatterMarkSize)
  const [phaseShowGridlines, setPhaseShowGridlines] = useState(initialSettings.phaseShowGridlines)
  const [phaseXAxisAuto, setPhaseXAxisAuto] = useState(initialSettings.phaseXAxisAuto)
  const [phaseYAxisAuto, setPhaseYAxisAuto] = useState(initialSettings.phaseYAxisAuto)
  const [phaseXAxisRange, setPhaseXAxisRange] = useState<PhaseAxisRange>(initialSettings.phaseXAxisRange)
  const [phaseYAxisRange, setPhaseYAxisRange] = useState<PhaseAxisRange>(initialSettings.phaseYAxisRange)
  const [phasePositionConditionMm, setPhasePositionConditionMm] = useState<PhaseAxisRange>(initialSettings.phasePositionConditionMm)
  const [phasePositionConditionNormalized, setPhasePositionConditionNormalized] = useState<PhaseAxisRange>(initialSettings.phasePositionConditionNormalized)
  const [phaseVelocityCondition, setPhaseVelocityCondition] = useState<PhaseAxisRange>(initialSettings.phaseVelocityCondition)
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle', message: 'Select sessions or groups to visualize.' })

  useEffect(() => {
    const restored = restoredVisualizationSettings(settingsCacheKey, visualizationEntities(studySet), studySetTracks, mode)
    setSelectedEntityIds(restored.selectedEntityIds)
    setCollapsedPanels(restored.collapsedPanels)
    setComparisonLayout(restored.comparisonLayout)
    setScopeMode(restored.scopeMode)
    setSelectedTrackId(restored.selectedTrackId)
    setSelectedEnds(restored.selectedEnds)
    setSelectedSectorIds(restored.selectedSectorIds)
    setTimeWindowsBySession(restored.timeWindowsBySession)
    setExcludeInactivePeriods(restored.excludeInactivePeriods)
    setSignalChoices(restored.signalChoices)
    setFrequencyDisplayModes(restored.frequencyDisplayModes)
    setShowDisplacementMm(restored.showDisplacementMm)
    setShowDisplacementStatsOnChart(restored.showDisplacementStatsOnChart)
    setShowVelocityStatsOnChart(restored.showVelocityStatsOnChart)
    setShowStrokeLengthStatsOnChart(restored.showStrokeLengthStatsOnChart)
    setPhaseDensityBins(restored.phaseDensityBins)
    setPhaseContourMasses(restored.phaseContourMasses)
    setPhaseConditionalBins(restored.phaseConditionalBins)
    setPhaseRenderMode(restored.phaseRenderMode)
    setPhaseMarkOpacity(restored.phaseMarkOpacity)
    setPhaseScatterMarkSize(restored.phaseScatterMarkSize)
    setPhaseShowGridlines(restored.phaseShowGridlines)
    setPhaseXAxisAuto(restored.phaseXAxisAuto)
    setPhaseYAxisAuto(restored.phaseYAxisAuto)
    setPhaseXAxisRange(restored.phaseXAxisRange)
    setPhaseYAxisRange(restored.phaseYAxisRange)
    setPhasePositionConditionMm(restored.phasePositionConditionMm)
    setPhasePositionConditionNormalized(restored.phasePositionConditionNormalized)
    setPhaseVelocityCondition(restored.phaseVelocityCondition)
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

  const selectedEntities = useMemo(() => entities.filter((entity) => selectedEntityIds.includes(entity.id)), [entities, selectedEntityIds])
  const selectedTrack = useMemo(() => studySetTracks.find((track) => track.id === selectedTrackId) ?? studySetTracks[0] ?? null, [selectedTrackId, studySetTracks])
  const sectors = useMemo(() => selectedTrack ? trackSectors(selectedTrack) : [], [selectedTrack])
  const sectorKey = sectors.map((sector) => sector.id).join('|')
  const selectedSectors = useMemo(() => sectors.filter((sector) => selectedSectorIds.includes(sector.id)), [sectors, selectedSectorIds])
  const selectedSessionRefs = useMemo(() => uniqueSessionRefs(selectedEntities.flatMap((entity) => entity.sessionRefs)), [selectedEntities])
  const studySetSessionRefs = useMemo(() => uniqueSessionRefs(studySet.sessions), [studySetKey])
  const displacementUnitMode: DisplacementUnitMode = showDisplacementMm ? 'mm' : 'normalized'
  const displacementRoleConfigs = useMemo(() => displacementSignalRoleConfigs(displacementUnitMode), [displacementUnitMode])
  const studySetSessionKey = studySetSessionRefs.map(sessionRefId).join('|')
  const resolvedSignalChoices = useMemo(
    () => resolvedDisplacementSignalChoices(studySetSessionRefs, sessions, signalChoices, displacementRoleConfigs),
    [studySetSessionKey, sessions, signalChoices, displacementRoleConfigs],
  )
  const signalChoiceGroups = useMemo(
    () => duplicateDisplacementSignalChoiceGroups(studySetSessionRefs, sessions, resolvedSignalChoices, displacementRoleConfigs),
    [studySetSessionKey, sessions, resolvedSignalChoices, displacementRoleConfigs],
  )
  const signalChoiceSignature = useMemo(() => signalChoiceSelectionSignature(resolvedSignalChoices), [resolvedSignalChoices])

  useEffect(() => {
    setSelectedSectorIds((current) => {
      const validIds = new Set(sectors.map((sector) => sector.id))
      const retained = current.filter((sectorId) => validIds.has(sectorId))
      return retained.length > 0 ? retained : sectors.map((sector) => sector.id)
    })
  }, [selectedTrack?.id, sectorKey])

  useEffect(() => {
    const settings = {
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
      signalChoices,
      frequencyDisplayModes,
      showDisplacementMm,
      showDisplacementStatsOnChart,
      showVelocityStatsOnChart,
      showStrokeLengthStatsOnChart,
      phaseDensityBins,
      phaseContourMasses,
      phaseConditionalBins,
      phaseRenderMode,
      phaseMarkOpacity,
      phaseScatterMarkSize,
      phaseShowGridlines,
      phaseXAxisAuto,
      phaseYAxisAuto,
      phaseXAxisRange,
      phaseYAxisRange,
      phasePositionConditionMm,
      phasePositionConditionNormalized,
      phaseVelocityCondition,
    }
    visualizationSettingsCache.set(settingsCacheKey, settings)
    const persistenceTimer = window.setTimeout(() => persistVisualizationSettings(settingsCacheKey, settings), 180)
    return () => window.clearTimeout(persistenceTimer)
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
    signalChoices,
    frequencyDisplayModes,
    showDisplacementMm,
    showDisplacementStatsOnChart,
    showVelocityStatsOnChart,
    showStrokeLengthStatsOnChart,
    phaseDensityBins,
    phaseContourMasses,
    phaseConditionalBins,
    phaseRenderMode,
    phaseMarkOpacity,
    phaseScatterMarkSize,
    phaseShowGridlines,
    phaseXAxisAuto,
    phaseYAxisAuto,
    phaseXAxisRange,
    phaseYAxisRange,
    phasePositionConditionMm,
    phasePositionConditionNormalized,
    phaseVelocityCondition,
  ])

  useEffect(() => {
    let cancelled = false
    async function loadData() {
      if (studySetSessionRefs.length === 0) {
        setLoadState({ status: 'idle', message: 'Add at least one session to visualize suspension data.' })
        return
      }
      const missCount = visualizationCacheMissCount(dataSource, studySetSessionRefs, resolvedSignalChoices, displacementUnitMode, mode)
      setLoadState((current) => ({
        status: 'loading',
        message: current.data
          ? missCount > 0
            ? `Loading ${missCount} uncached session(s); showing existing visualization data.`
            : 'Refreshing visualization data from browser cache...'
          : 'Loading suspension visualization data...',
        data: current.data,
        diagnostics: current.diagnostics,
      }))
      try {
        const result = await loadVisualizationData(studySetSessionRefs, resolvedSignalChoices, displacementUnitMode, sessions, dataSource, mode)
        if (!cancelled) {
          setLoadState({
            status: 'ready',
            message: suspensionCacheLoadMessage(result.diagnostics),
            data: result.data,
            diagnostics: result.diagnostics,
          })
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : String(error)
          setLoadState((current) => ({
            status: 'error',
            message,
            data: current.data,
            diagnostics: current.diagnostics,
          }))
        }
      }
    }

    void loadData()
    return () => {
      cancelled = true
    }
  }, [dataSource, sessions, studySetSessionKey, signalChoiceSignature, displacementUnitMode, mode])

  const data = loadState.data ?? null
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
  const singleEntityDashboard = mode === 'simple' && selectedEntities.length === 1 && scopeMode === 'whole_session'
  const panelComparisonLayout: ComparisonLayout = singleEntityDashboard ? 'entities' : comparisonLayout
  const velocityDomain = baseAnalysisData
    ? metricMagnitudeCandidateDomain(selectedEntities, baseAnalysisData, selectedEnds, VELOCITY_METRIC_SPEC, VELOCITY_DOMAIN_LIMITS)
    : ([0, 2000] as [number, number])
  const strokeLengthDomain = baseAnalysisData
    ? metricMagnitudeCandidateDomain(selectedEntities, baseAnalysisData, selectedEnds, STROKE_LENGTH_METRIC_SPEC, STROKE_LENGTH_DOMAIN_LIMITS)
    : ([0, 100] as [number, number])
  const displacementFrontRole = showDisplacementMm ? 'front_displacement_mm' : 'front_displacement'
  const displacementRearRole = showDisplacementMm ? 'rear_displacement_mm' : 'rear_displacement'
  const phaseDisplacementRoles = useMemo<Record<SuspensionEnd, string>>(() => ({
    front: displacementFrontRole,
    rear: displacementRearRole,
  }), [displacementFrontRole, displacementRearRole])
  const displacementXDomain = showDisplacementMm && baseAnalysisData
    ? displacementMmCandidateDomain(selectedEntities, baseAnalysisData, selectedEnds, DISPLACEMENT_MM_DOMAIN_LIMITS)
    : ([0, 100] as [number, number])
  const displacementXLabel = showDisplacementMm ? 'wheel displacement (mm)' : 'wheel displacement, % of max'
  const phaseXAxisBounds = useMemo<PhaseAxisRange>(() => showDisplacementMm
    ? [...PHASE_DISPLACEMENT_MM_BOUNDS]
    : [...PHASE_DISPLACEMENT_NORMALIZED_BOUNDS], [showDisplacementMm])
  const phaseXAxisManualRange = useMemo(() => clampPhaseAxisRange(phaseXAxisRange, phaseXAxisBounds), [phaseXAxisBounds, phaseXAxisRange])
  const phaseYAxisManualRange = useMemo(() => clampPhaseAxisRange(phaseYAxisRange, [...PHASE_VELOCITY_BOUNDS]), [phaseYAxisRange])
  const phasePositionCondition = useMemo(() => showDisplacementMm
    ? clampPhaseAxisRange(phasePositionConditionMm, [...PHASE_DISPLACEMENT_MM_BOUNDS])
    : clampPhaseAxisRange(phasePositionConditionNormalized, [...PHASE_DISPLACEMENT_NORMALIZED_BOUNDS]), [phasePositionConditionMm, phasePositionConditionNormalized, showDisplacementMm])
  const setPhasePositionCondition = showDisplacementMm ? setPhasePositionConditionMm : setPhasePositionConditionNormalized
  const phaseVelocityConditionRange = useMemo(() => clampPhaseAxisRange(phaseVelocityCondition, [...PHASE_VELOCITY_BOUNDS]), [phaseVelocityCondition])
  const deferredPhasePositionCondition = useDeferredValue(phasePositionCondition)
  const deferredPhaseVelocityConditionRange = useDeferredValue(phaseVelocityConditionRange)
  const phaseAutoDomain = useMemo(() => {
    if (!analysisData) {
      return null
    }
    const visibleSectors = scopeMode === 'sector' ? selectedSectors : [null]
    const series = selectedEntities.flatMap((entity) => visibleSectors.flatMap((sector) => orderedSuspensionEnds(selectedEnds).map((end) => ({
      id: `${entity.id}-${end}-${sector?.id ?? 'all'}`,
      label: entity.label,
      color: roleColor(end),
      points: phasePointsForEntityEnd(
        entity,
        analysisData,
        end === 'front' ? displacementFrontRole : displacementRearRole,
        `${end}_velocity`,
        selectedTrack,
        sector ? [sector] : null,
        showDisplacementMm ? 1 : 100,
      ),
    }))))
    return phaseDomain(series)
  }, [analysisData, displacementFrontRole, displacementRearRole, scopeMode, selectedEnds, selectedEntities, selectedSectors, selectedTrack, showDisplacementMm])

  useEffect(() => {
    if (!phaseAutoDomain) {
      return
    }
    if (phaseXAxisAuto) {
      setPhaseXAxisRange((current) => phaseAxisRangesEqual(current, phaseAutoDomain.x) ? current : phaseAutoDomain.x)
    }
    if (phaseYAxisAuto) {
      setPhaseYAxisRange((current) => phaseAxisRangesEqual(current, phaseAutoDomain.y) ? current : phaseAutoDomain.y)
    }
  }, [phaseAutoDomain, phaseXAxisAuto, phaseYAxisAuto])
  const displacementStatsFormatter = showDisplacementMm ? DISPLACEMENT_MM_STATS_FORMATTER : formatPercentValue
  const displacementValueTransform = showDisplacementMm ? identityValues : percentValues

  function toggleEntity(entityId: string) {
    setSelectedEntityIds((current) =>
      current.includes(entityId) ? current.filter((id) => id !== entityId) : [...current, entityId],
    )
  }

  function toggleEnd(end: SuspensionEnd) {
    setSelectedEnds((current) =>
      orderedSuspensionEnds(current.includes(end) ? current.filter((item) => item !== end) : [...current, end]),
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

  function setSignalChoice(key: string, column: string) {
    setSignalChoices((current) => ({
      ...current,
      [key]: column,
    }))
  }

  function setFrequencyDisplayMode(quantity: keyof FrequencyDisplayModes, mode: FrequencyDisplayMode) {
    setFrequencyDisplayModes((current) => ({
      ...current,
      [quantity]: mode,
    }))
  }

  return (
    <div className="suspension-viz">
      <header className="suspension-viz-hero">
        <div>
          <h3 className="viz-heading">
            {studySet.displayName || 'Current Study Set'}
            <InfoTip text={mode === 'phase' ? 'Suspension displacement--velocity phase diagrams for one or more Study Set sessions or groups. Groups pool their member samples.' : 'Simple Suspension Metrics for one or more Study Set sessions or groups. Groups combine their member sessions.'} />
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

      <div className={`suspension-viz-workspace${controlsCollapsed ? ' controls-collapsed' : ''}`}>
        <aside className={`viz-control-drawer${controlsCollapsed ? ' collapsed' : ''}`} aria-label="Select and filter">
          {controlsCollapsed ? (
            <button className="viz-control-drawer-rail" type="button" onClick={() => togglePanel('select-filter')}>
              <ChevronRight size={15} />
              <span>Select and filter</span>
            </button>
          ) : (
            <section className="viz-control-panel">
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
                <ChevronLeft size={16} />
              </button>
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

                {signalChoiceGroups.length > 0 && (
                  <SignalChoiceControl groups={signalChoiceGroups} onChange={setSignalChoice} />
                )}

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
                    dataSource={dataSource}
                    bookmarkRefreshToken={bookmarkRefreshToken}
                    sessionRefs={selectedSessionRefs}
                    sessions={sessions}
                    timeWindows={timeWindowsBySession}
                    onChange={setSessionTimeWindow}
                    onReset={resetSessionTimeWindow}
                    onResetAll={() => setTimeWindowsBySession({})}
                    onInspectSignals={onInspectSignals}
                  />
                )}

                {mode === 'phase' ? (
                  <PhaseDisplayOptionsControl
                    densityBins={phaseDensityBins}
                    contourMasses={phaseContourMasses}
                    conditionalBins={phaseConditionalBins}
                    renderMode={phaseRenderMode}
                    markOpacity={phaseMarkOpacity}
                    scatterMarkSize={phaseScatterMarkSize}
                    showGridlines={phaseShowGridlines}
                    xAxisAuto={phaseXAxisAuto}
                    xAxisBounds={phaseXAxisBounds}
                    xAxisRange={phaseXAxisManualRange}
                    yAxisAuto={phaseYAxisAuto}
                    yAxisBounds={PHASE_VELOCITY_BOUNDS}
                    yAxisRange={phaseYAxisManualRange}
                    positionConditionRange={phasePositionCondition}
                    velocityConditionRange={phaseVelocityConditionRange}
                    showDisplacementMm={showDisplacementMm}
                    onDensityBinsChange={setPhaseDensityBins}
                    onContourMassesChange={setPhaseContourMasses}
                    onConditionalBinsChange={setPhaseConditionalBins}
                    onRenderModeChange={setPhaseRenderMode}
                    onMarkOpacityChange={setPhaseMarkOpacity}
                    onScatterMarkSizeChange={setPhaseScatterMarkSize}
                    onShowGridlinesChange={setPhaseShowGridlines}
                    onXAxisAutoChange={setPhaseXAxisAuto}
                    onXAxisRangeChange={setPhaseXAxisRange}
                    onYAxisAutoChange={setPhaseYAxisAuto}
                    onYAxisRangeChange={setPhaseYAxisRange}
                    onPositionConditionRangeChange={setPhasePositionCondition}
                    onVelocityConditionRangeChange={setPhaseVelocityCondition}
                    onShowDisplacementMmChange={setShowDisplacementMm}
                  />
                ) : (
                <DisplayOptionsControl
                  modes={frequencyDisplayModes}
                  onChange={setFrequencyDisplayMode}
                  onShowDisplacementMmChange={setShowDisplacementMm}
                  onShowDisplacementStatsOnChartChange={setShowDisplacementStatsOnChart}
                  onShowStrokeLengthStatsOnChartChange={setShowStrokeLengthStatsOnChart}
                  onShowVelocityStatsOnChartChange={setShowVelocityStatsOnChart}
                  showDisplacementMm={showDisplacementMm}
                  showDisplacementStatsOnChart={showDisplacementStatsOnChart}
                  showStrokeLengthStatsOnChart={showStrokeLengthStatsOnChart}
                  showVelocityStatsOnChart={showVelocityStatsOnChart}
                />
                )}
              </div>
            </section>
          )}
        </aside>

        <div className="suspension-viz-content">
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
          {mode === 'phase' ? (
            <>
            <VisualizationPanel
              id="phase-diagram"
              title="Suspension phase diagram"
              subtitle="Wheel displacement versus instantaneous wheel velocity. Positive velocity is compression; negative velocity is rebound."
              collapsed={collapsedPanels.includes('phase-diagram')}
              onToggle={() => togglePanel('phase-diagram')}
            >
              <PhaseProvenanceNote entities={selectedEntities} sessions={sessions} />
              <PhaseDiagramGrid
                variant="phase"
                data={analysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={panelComparisonLayout}
                scopeMode={scopeMode}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                displacementRoles={phaseDisplacementRoles}
                displacementScale={showDisplacementMm ? 1 : 100}
                densityBins={phaseDensityBins}
                contourMasses={phaseContourMasses}
                conditionalBins={phaseConditionalBins}
                renderMode={phaseRenderMode}
                markOpacity={phaseMarkOpacity}
                scatterMarkSize={phaseScatterMarkSize}
                showGridlines={phaseShowGridlines}
                xDomainOverride={phaseXAxisAuto ? phaseAutoDomain?.x ?? null : phaseXAxisManualRange}
                yDomainOverride={phaseYAxisAuto ? phaseAutoDomain?.y ?? null : phaseYAxisManualRange}
                logDensity
                showZeroLines
                positionConditionRange={deferredPhasePositionCondition}
                velocityConditionRange={deferredPhaseVelocityConditionRange}
                xLabel={displacementXLabel}
              />
            </VisualizationPanel>
            <VisualizationPanel
              id="phase-contours"
              title="Probability-mass contours"
              subtitle="Sample-weighted outline contours at the selected probability masses."
              collapsed={collapsedPanels.includes('phase-contours')}
              onToggle={() => togglePanel('phase-contours')}
            >
              <PhaseDiagramGrid
                variant="contours"
                data={analysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={panelComparisonLayout}
                scopeMode={scopeMode}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                displacementRoles={phaseDisplacementRoles}
                displacementScale={showDisplacementMm ? 1 : 100}
                densityBins={phaseDensityBins}
                contourMasses={phaseContourMasses}
                conditionalBins={phaseConditionalBins}
                renderMode={phaseRenderMode}
                markOpacity={phaseMarkOpacity}
                scatterMarkSize={phaseScatterMarkSize}
                showGridlines={phaseShowGridlines}
                xDomainOverride={phaseXAxisAuto ? phaseAutoDomain?.x ?? null : phaseXAxisManualRange}
                yDomainOverride={phaseYAxisAuto ? phaseAutoDomain?.y ?? null : phaseYAxisManualRange}
                logDensity
                showZeroLines
                positionConditionRange={deferredPhasePositionCondition}
                velocityConditionRange={deferredPhaseVelocityConditionRange}
                xLabel={displacementXLabel}
              />
            </VisualizationPanel>
            <VisualizationPanel
              id="phase-velocity-given-position"
              title="Velocity conditional on position"
              subtitle={`Normalized velocity distributions for samples with displacement from ${formatPhaseAxisRangeValue(phasePositionCondition[0])} to ${formatPhaseAxisRangeValue(phasePositionCondition[1])}${showDisplacementMm ? ' mm' : '%'}. The chart range uses the 0.1st to 99.9th percentiles; excluded tails are reported on the chart.`}
              collapsed={collapsedPanels.includes('phase-velocity-given-position')}
              onToggle={() => togglePanel('phase-velocity-given-position')}
            >
              <PhaseDiagramGrid
                variant="velocity_given_position"
                data={analysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={panelComparisonLayout}
                scopeMode={scopeMode}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                displacementRoles={phaseDisplacementRoles}
                displacementScale={showDisplacementMm ? 1 : 100}
                densityBins={phaseDensityBins}
                contourMasses={phaseContourMasses}
                conditionalBins={phaseConditionalBins}
                renderMode={phaseRenderMode}
                markOpacity={phaseMarkOpacity}
                scatterMarkSize={phaseScatterMarkSize}
                showGridlines={phaseShowGridlines}
                xDomainOverride={phaseXAxisAuto ? phaseAutoDomain?.x ?? null : phaseXAxisManualRange}
                yDomainOverride={phaseYAxisAuto ? phaseAutoDomain?.y ?? null : phaseYAxisManualRange}
                logDensity
                showZeroLines
                positionConditionRange={deferredPhasePositionCondition}
                velocityConditionRange={deferredPhaseVelocityConditionRange}
                xLabel={displacementXLabel}
              />
            </VisualizationPanel>
            <VisualizationPanel
              id="phase-position-given-velocity"
              title="Position conditional on velocity"
              subtitle={`Normalized position distributions for samples with velocity from ${formatPhaseAxisRangeValue(phaseVelocityConditionRange[0])} to ${formatPhaseAxisRangeValue(phaseVelocityConditionRange[1])} mm/s. The chart range uses the 0.1st to 99.9th percentiles; excluded tails are reported on the chart.`}
              collapsed={collapsedPanels.includes('phase-position-given-velocity')}
              onToggle={() => togglePanel('phase-position-given-velocity')}
            >
              <PhaseDiagramGrid
                variant="position_given_velocity"
                data={analysisData}
                entities={selectedEntities}
                ends={selectedEnds}
                layout={panelComparisonLayout}
                scopeMode={scopeMode}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                displacementRoles={phaseDisplacementRoles}
                displacementScale={showDisplacementMm ? 1 : 100}
                densityBins={phaseDensityBins}
                contourMasses={phaseContourMasses}
                conditionalBins={phaseConditionalBins}
                renderMode={phaseRenderMode}
                markOpacity={phaseMarkOpacity}
                scatterMarkSize={phaseScatterMarkSize}
                showGridlines={phaseShowGridlines}
                xDomainOverride={phaseXAxisAuto ? phaseAutoDomain?.x ?? null : phaseXAxisManualRange}
                yDomainOverride={phaseYAxisAuto ? phaseAutoDomain?.y ?? null : phaseYAxisManualRange}
                logDensity
                showZeroLines
                positionConditionRange={deferredPhasePositionCondition}
                velocityConditionRange={deferredPhaseVelocityConditionRange}
                xLabel={displacementXLabel}
              />
            </VisualizationPanel>
            </>
          ) : (
            <>
          <VisualizationPanel
            id="displacement"
            title="Wheel displacement distribution"
            subtitle={showDisplacementMm ? 'Wheel displacement in engineering units, frequency distribution.' : 'Wheel displacement, % of maximum travel, frequency distribution.'}
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
                frontRole={displacementFrontRole}
                rearRole={displacementRearRole}
                displayMode={frequencyDisplayModes.displacement}
                showDisplacementStatsOnChart={showDisplacementStatsOnChart}
                xDomain={displacementXDomain}
                xLabel={displacementXLabel}
                bins={SECTOR_DISTRIBUTION_BINS}
                trackMatchesLoading={visualizationTrackMatchesLoading}
                valueTransform={displacementValueTransform}
                statsMode="displacement"
                statsFormatter={displacementStatsFormatter}
              />
            ) : (
              <DistributionGrid
                chartKind="histogram"
                displayMode={frequencyDisplayModes.displacement}
                layout={panelComparisonLayout}
                entities={selectedEntities}
                roles={distributionRoles(displacementFrontRole, displacementRearRole, selectedEnds)}
                xDomain={displacementXDomain}
                xLabel={displacementXLabel}
                bins={WHOLE_SESSION_DISTRIBUTION_BINS}
                yMax={distributionYMax(
                  selectedEntities,
                  distributionRoles(displacementFrontRole, displacementRearRole, selectedEnds),
                  (entity, role) => displacementValueTransform(entitySignalValues(entity, baseAnalysisData, role.signalRole)),
                  displacementXDomain,
                  WHOLE_SESSION_DISTRIBUTION_BINS,
                  'histogram',
                )}
                sessions={sessions}
                showStats
                showDisplacementStatsOnChart={showDisplacementStatsOnChart}
                statsMode="displacement"
                statsFormatter={displacementStatsFormatter}
                valueForEntityRole={(entity, role) => displacementValueTransform(entitySignalValues(entity, analysisData, role.signalRole))}
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
                displayMode={frequencyDisplayModes.velocity}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xLabel="stroke maximum wheel velocity (mm/s)"
                bins={SECTOR_DISTRIBUTION_BINS}
                domainCandidates={VELOCITY_DOMAIN_LIMITS}
                showStatsOnChart={showVelocityStatsOnChart}
                statsFormatter={VELOCITY_STATS_FORMATTER}
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <DistributionGrid
                chartKind="mirrored_velocity"
                displayMode={frequencyDisplayModes.velocity}
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
                showMirroredStatsOnChart={showVelocityStatsOnChart}
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
                displayMode={frequencyDisplayModes.strokeLength}
                selectedTrack={selectedTrack}
                sectors={selectedSectors}
                allSectors={sectors}
                xLabel="wheel stroke length (mm)"
                bins={SECTOR_DISTRIBUTION_BINS}
                domainCandidates={STROKE_LENGTH_DOMAIN_LIMITS}
                showStatsOnChart={showStrokeLengthStatsOnChart}
                statsFormatter={STROKE_LENGTH_STATS_FORMATTER}
                trackMatchesLoading={visualizationTrackMatchesLoading}
              />
            ) : (
              <DistributionGrid
                chartKind="mirrored_velocity"
                displayMode={frequencyDisplayModes.strokeLength}
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
                showMirroredStatsOnChart={showStrokeLengthStatsOnChart}
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
            </>
          )}
        </div>
      )}
        </div>
      </div>

    </div>
  )
}

function PhaseProvenanceNote({ entities, sessions }: { entities: VisualizationEntity[]; sessions: SessionRecord[] }) {
  const profileNames = Array.from(new Set(
    uniqueSessionRefs(entities.flatMap((entity) => entity.sessionRefs))
      .map((ref) => sessionByRef(ref, sessions)?.preprocessingProfile?.trim())
      .filter((value): value is string => Boolean(value)),
  ))
  return (
    <div className={`viz-status${profileNames.length > 1 ? ' warning' : ''}`}>
      Continuous velocity is the persisted preprocessed wheel-velocity signal. {profileNames.length > 0 ? `Profile${profileNames.length === 1 ? '' : 's'}: ${profileNames.join(', ')}.` : 'No preprocessing profile metadata is available.'}
      {profileNames.length > 1 ? ' Compare sessions only when filtering and derivation settings are compatible.' : ''}
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

function DisplayOptionsControl({
  modes,
  onChange,
  onShowDisplacementMmChange,
  onShowDisplacementStatsOnChartChange,
  onShowStrokeLengthStatsOnChartChange,
  onShowVelocityStatsOnChartChange,
  showDisplacementMm,
  showDisplacementStatsOnChart,
  showStrokeLengthStatsOnChart,
  showVelocityStatsOnChart,
}: {
  modes: FrequencyDisplayModes
  onChange: (quantity: keyof FrequencyDisplayModes, mode: FrequencyDisplayMode) => void
  onShowDisplacementMmChange: (checked: boolean) => void
  onShowDisplacementStatsOnChartChange: (checked: boolean) => void
  onShowStrokeLengthStatsOnChartChange: (checked: boolean) => void
  onShowVelocityStatsOnChartChange: (checked: boolean) => void
  showDisplacementMm: boolean
  showDisplacementStatsOnChart: boolean
  showStrokeLengthStatsOnChart: boolean
  showVelocityStatsOnChart: boolean
}) {
  return (
    <section className="viz-display-options">
      <strong>Display options</strong>
      <fieldset className="viz-frequency-options">
        <legend>Frequency data</legend>
        <FrequencyModePair
          extra={
            <>
              <label className="viz-frequency-extra-option">
                <input
                  checked={showDisplacementStatsOnChart}
                  onChange={(event) => onShowDisplacementStatsOnChartChange(event.target.checked)}
                  type="checkbox"
                />
                Show stats on chart
              </label>
              <label className="viz-frequency-extra-option">
                <input
                  checked={showDisplacementMm}
                  onChange={(event) => onShowDisplacementMmChange(event.target.checked)}
                  type="checkbox"
                />
                Show displacement in mm
              </label>
            </>
          }
          label="Wheel displacement"
          name="frequency-displacement"
          value={modes.displacement}
          onChange={(mode) => onChange('displacement', mode)}
        />
        <FrequencyModePair
          extra={
            <label className="viz-frequency-extra-option">
              <input
                checked={showVelocityStatsOnChart}
                onChange={(event) => onShowVelocityStatsOnChartChange(event.target.checked)}
                type="checkbox"
              />
              Show stats on chart
            </label>
          }
          label="Wheel velocity"
          name="frequency-velocity"
          value={modes.velocity}
          onChange={(mode) => onChange('velocity', mode)}
        />
        <FrequencyModePair
          extra={
            <label className="viz-frequency-extra-option">
              <input
                checked={showStrokeLengthStatsOnChart}
                onChange={(event) => onShowStrokeLengthStatsOnChartChange(event.target.checked)}
                type="checkbox"
              />
              Show stats on chart
            </label>
          }
          label="Wheel stroke length"
          name="frequency-stroke-length"
          value={modes.strokeLength}
          onChange={(mode) => onChange('strokeLength', mode)}
        />
      </fieldset>
    </section>
  )
}

function PhaseDisplayOptionsControl({
  densityBins,
  contourMasses,
  conditionalBins,
  renderMode,
  markOpacity,
  scatterMarkSize,
  showGridlines,
  xAxisAuto,
  xAxisBounds,
  xAxisRange,
  yAxisAuto,
  yAxisBounds,
  yAxisRange,
  positionConditionRange,
  velocityConditionRange,
  showDisplacementMm,
  onDensityBinsChange,
  onContourMassesChange,
  onConditionalBinsChange,
  onRenderModeChange,
  onMarkOpacityChange,
  onScatterMarkSizeChange,
  onShowGridlinesChange,
  onXAxisAutoChange,
  onXAxisRangeChange,
  onYAxisAutoChange,
  onYAxisRangeChange,
  onPositionConditionRangeChange,
  onVelocityConditionRangeChange,
  onShowDisplacementMmChange,
}: {
  densityBins: number
  contourMasses: number[]
  conditionalBins: number
  renderMode: PhaseRenderMode
  markOpacity: number
  scatterMarkSize: number
  showGridlines: boolean
  xAxisAuto: boolean
  xAxisBounds: PhaseAxisRange
  xAxisRange: PhaseAxisRange
  yAxisAuto: boolean
  yAxisBounds: readonly [number, number]
  yAxisRange: PhaseAxisRange
  positionConditionRange: PhaseAxisRange
  velocityConditionRange: PhaseAxisRange
  showDisplacementMm: boolean
  onDensityBinsChange: (value: number) => void
  onContourMassesChange: (value: number[]) => void
  onConditionalBinsChange: (value: number) => void
  onRenderModeChange: (value: PhaseRenderMode) => void
  onMarkOpacityChange: (value: number) => void
  onScatterMarkSizeChange: (value: number) => void
  onShowGridlinesChange: (checked: boolean) => void
  onXAxisAutoChange: (checked: boolean) => void
  onXAxisRangeChange: (value: PhaseAxisRange) => void
  onYAxisAutoChange: (checked: boolean) => void
  onYAxisRangeChange: (value: PhaseAxisRange) => void
  onPositionConditionRangeChange: (value: PhaseAxisRange) => void
  onVelocityConditionRangeChange: (value: PhaseAxisRange) => void
  onShowDisplacementMmChange: (checked: boolean) => void
}) {
  const toggleContourMass = (mass: number, checked: boolean) => {
    onContourMassesChange(checked
      ? PHASE_CONTOUR_MASS_OPTIONS.filter((option) => option === mass || contourMasses.includes(option))
      : contourMasses.filter((option) => option !== mass))
  }
  return (
    <section className="viz-display-options">
      <strong>Display options</strong>
      <fieldset className="viz-frequency-options">
        <legend>Phase diagram</legend>
        <span className="viz-frequency-mode-options">
          {(['line', 'scatter', 'density'] as const).map((presentation) => (
            <label key={presentation}>
              <input checked={renderMode === presentation} name="phase-presentation" onChange={() => onRenderModeChange(presentation)} type="radio" />
              {presentation[0].toUpperCase() + presentation.slice(1)}
            </label>
          ))}
        </span>
        {renderMode === 'density' && <label className="viz-frequency-extra-option">
          Resolution
          <select value={densityBins} onChange={(event) => onDensityBinsChange(Number(event.target.value))}>
            <option value={48}>Fine</option>
            <option value={72}>Finer</option>
            <option value={96}>Finest</option>
          </select>
        </label>}
        {renderMode !== 'density' && <label className="viz-frequency-extra-option">
          Mark opacity: {Math.round(markOpacity * 100)}%
          <input className="viz-mark-opacity-slider" min="0.02" max="0.8" step="0.02" type="range" value={markOpacity} onChange={(event) => onMarkOpacityChange(Number(event.target.value))} />
        </label>}
        {renderMode === 'scatter' && <label className="viz-frequency-extra-option">
          Mark size: {scatterMarkSize}px
          <input className="viz-mark-size-slider" min="1" max="5" step="0.5" type="range" value={scatterMarkSize} onChange={(event) => onScatterMarkSizeChange(Number(event.target.value))} />
        </label>}
        <div className="viz-phase-axis-options">
          <strong>Axis ranges</strong>
          <AxisRangeControl auto={xAxisAuto} bounds={xAxisBounds} label="Displacement" range={xAxisRange} step={PHASE_DISPLACEMENT_AXIS_STEP} onAutoChange={onXAxisAutoChange} onRangeChange={onXAxisRangeChange} />
          <AxisRangeControl auto={yAxisAuto} bounds={yAxisBounds} label="Velocity" range={yAxisRange} showZeroTick snapToZeroWithin={20} step={PHASE_VELOCITY_AXIS_STEP} onAutoChange={onYAxisAutoChange} onRangeChange={onYAxisRangeChange} />
        </div>
        <label className="viz-frequency-extra-option">
          <input checked={showGridlines} onChange={(event) => onShowGridlinesChange(event.target.checked)} type="checkbox" />
          Show gridlines
        </label>
        <label className="viz-frequency-extra-option">
          <input checked={!showDisplacementMm} onChange={(event) => onShowDisplacementMmChange(!event.target.checked)} type="checkbox" />
          Normalized displacement
        </label>
      </fieldset>
      <fieldset className="viz-frequency-options">
        <legend>Probability mass contours</legend>
        <span className="viz-frequency-mode-options viz-contour-mass-options">
          {PHASE_CONTOUR_MASS_OPTIONS.map((mass) => <label key={mass}>
            <input checked={contourMasses.includes(mass)} onChange={(event) => toggleContourMass(mass, event.target.checked)} type="checkbox" />
            {formatContourMass(mass)}
          </label>)}
        </span>
      </fieldset>
      <fieldset className="viz-frequency-options">
        <legend>Conditional distributions</legend>
        <ConditionRangeControl bounds={xAxisBounds} label="Position window" range={positionConditionRange} step={PHASE_DISPLACEMENT_AXIS_STEP} onRangeChange={onPositionConditionRangeChange} />
        <ConditionRangeControl bounds={yAxisBounds} label="Velocity window" range={velocityConditionRange} showZeroTick snapToZeroWithin={20} step={PHASE_VELOCITY_AXIS_STEP} onRangeChange={onVelocityConditionRangeChange} />
        <label className="viz-frequency-extra-option">
          Bins: {conditionalBins}
          <input className="viz-conditional-bins-slider" min="20" max="120" step="5" type="range" value={conditionalBins} onChange={(event) => onConditionalBinsChange(Number(event.target.value))} />
        </label>
      </fieldset>
    </section>
  )
}

function AxisRangeControl({ auto, bounds, label, range, showZeroTick = false, snapToZeroWithin, step, onAutoChange, onRangeChange }: {
  auto: boolean
  bounds: readonly [number, number]
  label: string
  range: PhaseAxisRange
  showZeroTick?: boolean
  snapToZeroWithin?: number
  step: number
  onAutoChange: (checked: boolean) => void
  onRangeChange: (range: PhaseAxisRange) => void
}) {
  const span = bounds[1] - bounds[0]
  const minPosition = ((range[0] - bounds[0]) / span) * 100
  const maxPosition = ((range[1] - bounds[0]) / span) * 100
  const sliderStyle = {
    '--phase-range-start': `${minPosition}%`,
    '--phase-range-width': `${Math.max(0, maxPosition - minPosition)}%`,
  } as CSSProperties
  const zeroPosition = ((0 - bounds[0]) / span) * 100
  const snapValue = (value: number) => snapToZeroWithin !== undefined && Math.abs(value) <= snapToZeroWithin ? 0 : value
  return (
    <div className="viz-phase-axis-control">
      <label><input checked={auto} onChange={(event) => onAutoChange(event.target.checked)} type="checkbox" /> {label}: auto</label>
      <div className={`viz-phase-range-slider${auto ? ' disabled' : ''}`} style={sliderStyle}>
        <span aria-hidden="true" />
        {showZeroTick && <i aria-hidden="true" className="viz-phase-range-zero-tick" style={{ left: `${zeroPosition}%` }} />}
        <input aria-label={`${label} minimum`} disabled={auto} max={bounds[1]} min={bounds[0]} onChange={(event) => onRangeChange([Math.min(snapValue(Number(event.target.value)), range[1] - step), range[1]])} step={step} type="range" value={range[0]} />
        <input aria-label={`${label} maximum`} disabled={auto} max={bounds[1]} min={bounds[0]} onChange={(event) => onRangeChange([range[0], Math.max(snapValue(Number(event.target.value)), range[0] + step)])} step={step} type="range" value={range[1]} />
      </div>
      <small>{formatPhaseAxisRangeValue(range[0])} to {formatPhaseAxisRangeValue(range[1])}</small>
    </div>
  )
}

function ConditionRangeControl({ bounds, label, range, showZeroTick = false, snapToZeroWithin, step, onRangeChange }: {
  bounds: readonly [number, number]
  label: string
  range: PhaseAxisRange
  showZeroTick?: boolean
  snapToZeroWithin?: number
  step: number
  onRangeChange: (range: PhaseAxisRange) => void
}) {
  const sliderRef = useRef<HTMLDivElement | null>(null)
  const activeThumbRef = useRef<'minimum' | 'maximum' | null>(null)
  const span = bounds[1] - bounds[0]
  const minPosition = ((range[0] - bounds[0]) / span) * 100
  const maxPosition = ((range[1] - bounds[0]) / span) * 100
  const zeroPosition = ((0 - bounds[0]) / span) * 100
  const snapValue = (value: number) => snapToZeroWithin !== undefined && Math.abs(value) <= snapToZeroWithin ? 0 : value
  const sliderStyle = {
    '--phase-range-start': `${minPosition}%`,
    '--phase-range-width': `${Math.max(0, maxPosition - minPosition)}%`,
  } as CSSProperties
  const valueAtPointer = (event: PointerEvent<HTMLDivElement>) => {
    const slider = sliderRef.current
    if (!slider) {
      return bounds[0]
    }
    const rect = slider.getBoundingClientRect()
    const proportion = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    const stepped = bounds[0] + Math.round((proportion * span) / step) * step
    return Math.max(bounds[0], Math.min(bounds[1], snapValue(stepped)))
  }
  const updateFromPointer = (event: PointerEvent<HTMLDivElement>, thumb: 'minimum' | 'maximum') => {
    const value = valueAtPointer(event)
    if (thumb === 'minimum') {
      onRangeChange([Math.min(value, range[1] - step), range[1]])
    } else {
      onRangeChange([range[0], Math.max(value, range[0] + step)])
    }
  }
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const value = valueAtPointer(event)
    const thumb = Math.abs(value - range[0]) <= Math.abs(value - range[1]) ? 'minimum' : 'maximum'
    activeThumbRef.current = thumb
    event.currentTarget.setPointerCapture(event.pointerId)
    updateFromPointer(event, thumb)
  }
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (activeThumbRef.current) {
      updateFromPointer(event, activeThumbRef.current)
    }
  }
  const finishPointerDrag = (event: PointerEvent<HTMLDivElement>) => {
    activeThumbRef.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }
  return (
    <div className="viz-phase-axis-control">
      <label>{label}</label>
      <div
        className="viz-phase-range-slider interactive"
        onPointerCancel={finishPointerDrag}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={finishPointerDrag}
        ref={sliderRef}
        style={sliderStyle}
      >
        <span aria-hidden="true" />
        {showZeroTick && <i aria-hidden="true" className="viz-phase-range-zero-tick" style={{ left: `${zeroPosition}%` }} />}
        <input aria-label={`${label} minimum`} max={bounds[1]} min={bounds[0]} readOnly step={step} tabIndex={-1} type="range" value={range[0]} />
        <input aria-label={`${label} maximum`} max={bounds[1]} min={bounds[0]} readOnly step={step} tabIndex={-1} type="range" value={range[1]} />
      </div>
      <small>{formatPhaseAxisRangeValue(range[0])} to {formatPhaseAxisRangeValue(range[1])}</small>
    </div>
  )
}

function FrequencyModePair({
  extra,
  label,
  name,
  value,
  onChange,
}: {
  extra?: ReactNode
  label: string
  name: string
  value: FrequencyDisplayMode
  onChange: (mode: FrequencyDisplayMode) => void
}) {
  return (
    <div className="viz-frequency-mode-row">
      <span>{label}</span>
      <span className="viz-frequency-mode-options">
        <label>
          <input
            checked={value === 'histogram'}
            name={name}
            onChange={() => onChange('histogram')}
            type="radio"
          />
          Histogram
        </label>
        <label>
          <input
            checked={value === 'cumulative'}
            name={name}
            onChange={() => onChange('cumulative')}
            type="radio"
          />
          Cumulative frequency
        </label>
      </span>
      {extra}
    </div>
  )
}

function TimeWindowManager({
  data,
  dataSource,
  bookmarkRefreshToken,
  sessionRefs,
  sessions,
  timeWindows,
  onChange,
  onReset,
  onResetAll,
  onInspectSignals,
}: {
  data: VisualizationData
  dataSource: LibraryDataSource
  bookmarkRefreshToken: number
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
        dataSource={dataSource}
        bookmarkRefreshToken={bookmarkRefreshToken}
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
  dataSource,
  bookmarkRefreshToken,
  sessionRef,
  session,
  window,
  onChange,
  onReset,
  onInspectSignals,
}: {
  embedded?: boolean
  data: VisualizationData
  dataSource: LibraryDataSource
  bookmarkRefreshToken: number
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
  const [periodBookmarks, setPeriodBookmarks] = useState<SessionBookmarkRecord[]>([])
  const active = Boolean(window)

  useEffect(() => {
    setDraftWindow(current)
  }, [current.startS, current.endS, sessionRef.sessionKey])

  useEffect(() => {
    let cancelled = false
    if (!session) {
      setPeriodBookmarks([])
      return
    }
    setPeriodBookmarks([])
    dataSource
      .listSessionBookmarks(session)
      .then((bookmarks) => {
        if (!cancelled) {
          setPeriodBookmarks(bookmarks.filter(isPeriodBookmark).sort(compareBookmarksByStart))
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPeriodBookmarks([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [bookmarkRefreshToken, dataSource, session])

  function commitDraftWindow(nextDraftWindow = draftWindow) {
    const nextWindow = sanitizeTimeWindow(nextDraftWindow, durationS, minWindowS)
    setDraftWindow(nextWindow)
    if (nextWindow.startS !== current.startS || nextWindow.endS !== current.endS) {
      onChange(nextWindow)
    }
  }

  function applyBookmarkWindow(bookmark: SessionBookmarkRecord) {
    const nextWindow = sanitizeTimeWindow(bookmark.window, durationS, minWindowS)
    setDraftWindow(nextWindow)
    onChange(nextWindow)
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
          <button type="button" onClick={onReset} disabled={!active || disabled}>
            Full session
          </button>
          {onInspectSignals && (
            <button type="button" onClick={() => onInspectSignals(draftWindow)} disabled={disabled}>
              <Activity size={13} />
              Signal inspector...
            </button>
          )}
        </div>
      </div>
      {disabled ? (
        <div className="viz-time-window-empty">No usable signal timebase is available for this session.</div>
      ) : (
        <>
          {periodBookmarks.length > 0 && (
            <div className="viz-time-window-bookmarks" aria-label="Period bookmarks">
              {periodBookmarks.map((bookmark) => (
                <button key={bookmark.id} type="button" onClick={() => applyBookmarkWindow(bookmark)}>
                  <span>{bookmark.title || 'Bookmark'}</span>
                  <small>
                    {formatTimeOffset(bookmark.window.startS)} - {formatTimeOffset(bookmark.window.endS)}
                  </small>
                </button>
              ))}
            </div>
          )}
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
  const frontPoints = overviewPoints(times, signals.front_displacement_mm ?? signals.front_displacement ?? [], 520)
  const rearPoints = overviewPoints(times, signals.rear_displacement_mm ?? signals.rear_displacement ?? [], 520)
  const displacementExtent = finiteExtent([...frontPoints, ...rearPoints].map((point) => point.value))
  const displacementMax = displacementExtent.count > 0 ? Math.max(1, displacementExtent.max * 1.04) : 1
  const x = d3.scaleLinear().domain([0, durationS || 1]).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, displacementMax]).range([height - margin.bottom, margin.top])
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
              <text className="viz-axis-label viz-time-window-tick-label" x={x(value)} y={height - 5} textAnchor="middle">
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

function SignalChoiceControl({
  groups,
  onChange,
}: {
  groups: SignalChoiceGroup[]
  onChange: (key: string, column: string) => void
}) {
  return (
    <div className="viz-signal-choice-panel">
      <strong>Signal choices</strong>
      <div className="viz-signal-choice-grid">
        {groups.map((group) => (
          <fieldset className="viz-signal-choice-group" key={group.key}>
            <legend>
              <span>{group.sessionLabel}</span>
              <small>{group.roleLabel}</small>
            </legend>
            {group.candidates.map((signal) => (
              <label key={signal.column}>
                <input
                  checked={group.selectedColumn === signal.column}
                  name={group.key}
                  onChange={() => onChange(group.key, signal.column)}
                  type="radio"
                />
                <span>
                  <strong>{signalChoiceLabel(signal)}</strong>
                  <small>{signalChoiceDetail(signal)}</small>
                </span>
              </label>
            ))}
          </fieldset>
        ))}
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
  displayMode,
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
  showDisplacementStatsOnChart = true,
  showMirroredStatsOnChart = false,
  statsMode = 'basic',
  statsFormatter = formatPercentValue,
  statsTransform = (value: number) => value,
}: {
  chartKind: DistributionChartKind
  displayMode: FrequencyDisplayMode
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
  showDisplacementStatsOnChart?: boolean
  showMirroredStatsOnChart?: boolean
  statsMode?: DistributionStatsMode
  statsFormatter?: (value: number | null) => string
  statsTransform?: (value: number) => number
}) {
  const yLabelForMode = displayMode === 'cumulative' ? 'cumulative frequency' : yLabel
  const yMaxForMode = displayMode === 'cumulative' ? 1 : yMax
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
                <MirroredVelocityChart
                  bins={bins}
                  displayMode={displayMode}
                  series={series}
                  showStatsOnChart={showMirroredStatsOnChart}
                  statsFormatter={statsFormatter}
                  xDomain={xDomain}
                  xLabel={xLabel}
                  yLabel={yLabelForMode}
                  yMax={yMaxForMode}
                />
              ) : (
                <FrequencyChartBlock
                  bins={bins}
                  displacementStatsFormatter={statsFormatter}
                  displayMode={displayMode}
                  series={series}
                  showDisplacementGlyphs={statsMode === 'displacement' && showDisplacementStatsOnChart}
                  xDomain={xDomain}
                  xLabel={xLabel}
                  yLabel={yLabelForMode}
                  yMax={yMaxForMode}
                />
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
              {showStats && (
                <DistributionStats
                  formatter={statsFormatter}
                  mode={statsMode}
                  series={series}
                  splitMirrored={chartKind === 'mirrored_velocity'}
                  transform={statsTransform}
                />
              )}
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
              <MirroredVelocityChart
                bins={bins}
                displayMode={displayMode}
                series={series}
                showStatsOnChart={showMirroredStatsOnChart}
                statsFormatter={statsFormatter}
                xDomain={xDomain}
                xLabel={xLabel}
                yLabel={yLabelForMode}
                yMax={yMaxForMode}
              />
            ) : (
              <FrequencyChartBlock
                bins={bins}
                displacementStatsFormatter={statsFormatter}
                displayMode={displayMode}
                series={series}
                showDisplacementGlyphs={statsMode === 'displacement' && showDisplacementStatsOnChart}
                xDomain={xDomain}
                xLabel={xLabel}
                yLabel={yLabelForMode}
                yMax={yMaxForMode}
              />
            )}
            {showStats && (
              <DistributionStats
                formatter={statsFormatter}
                mode={statsMode}
                series={series}
                splitMirrored={chartKind === 'mirrored_velocity'}
                transform={statsTransform}
              />
            )}
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
  displayMode,
  xDomain,
  xLabel,
  bins,
  trackMatchesLoading,
  showDisplacementStatsOnChart = true,
  statsMode = 'basic',
  statsFormatter = formatPercentValue,
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
  displayMode: FrequencyDisplayMode
  xDomain: [number, number]
  xLabel: string
  bins: number
  trackMatchesLoading: boolean
  showDisplacementStatsOnChart?: boolean
  statsMode?: DistributionStatsMode
  statsFormatter?: (value: number | null) => string
  valueTransform?: (values: number[]) => number[]
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)
  const horizontalFacets = entities.length === 1 && entities[0].kind === 'session'

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
          displayMode={displayMode}
          entities={entities}
          layout={layout}
          roles={roles}
          showDisplacementStatsOnChart={showDisplacementStatsOnChart}
          showStats={statsMode !== 'basic'}
          statsMode={statsMode}
          statsFormatter={statsFormatter}
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
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} ${horizontalFacets ? 'horizontal' : 'vertical'} sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className={`viz-sector-facet-stack${horizontalFacets ? ' horizontal' : ''}`}>
            {sectors.map((sector) => (
              <article className="viz-sector-facet" key={sector.id}>
                <header className="viz-sector-section-heading">
                  <strong>{sector.label}</strong>
                  <span>{formatMetres(sector.lengthM)}</span>
                </header>
                <DistributionGrid
                  bins={bins}
                  chartKind={chartKind}
                  displayMode={displayMode}
                  entities={entities}
                  layout={layout}
                  roles={roles}
                  showDisplacementStatsOnChart={showDisplacementStatsOnChart}
                  showStats={statsMode !== 'basic'}
                  statsMode={statsMode}
                  statsFormatter={statsFormatter}
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
  displayMode,
  xLabel,
  bins,
  domainCandidates,
  showStatsOnChart = false,
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
  displayMode: FrequencyDisplayMode
  xLabel: string
  bins: number
  domainCandidates: number[]
  showStatsOnChart?: boolean
  statsFormatter: (value: number | null) => string
  trackMatchesLoading: boolean
}) {
  const [facetsCollapsed, setFacetsCollapsed] = useState(false)
  const horizontalFacets = entities.length === 1 && entities[0].kind === 'session'
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
          displayMode={displayMode}
          entities={entities}
          layout={layout}
          roles={roles}
          showStats
          showMirroredStatsOnChart={showStatsOnChart}
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
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} ${horizontalFacets ? 'horizontal' : 'vertical'} sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className={`viz-sector-facet-stack${horizontalFacets ? ' horizontal' : ''}`}>
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
                    displayMode={displayMode}
                    entities={entities}
                    layout={layout}
                    roles={roles}
                    showStats
                    showMirroredStatsOnChart={showStatsOnChart}
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
  const horizontalFacets = entities.length === 1 && entities[0].kind === 'session'
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
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} ${horizontalFacets ? 'horizontal' : 'vertical'} sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className={`viz-sector-facet-stack${horizontalFacets ? ' horizontal' : ''}`}>
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
  const horizontalFacets = entities.length === 1 && entities[0].kind === 'session'
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
            <small>{facetsCollapsed ? 'Collapsed' : `${sectors.length} ${horizontalFacets ? 'horizontal' : 'vertical'} sector view(s)`}</small>
          </span>
          {facetsCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        </button>
        {!facetsCollapsed && (
          <div className={`viz-sector-facet-stack${horizontalFacets ? ' horizontal' : ''}`}>
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

type PhaseDiagramGridProps = {
  variant: PhaseChartVariant
  data: VisualizationData
  entities: VisualizationEntity[]
  ends: SuspensionEnd[]
  layout: ComparisonLayout
  scopeMode: ScopeMode
  selectedTrack: TrackRecord | null
  sectors: TrackSector[]
  displacementRoles: Record<SuspensionEnd, string>
  displacementScale: number
  densityBins: number
  contourMasses: number[]
  conditionalBins: number
  renderMode: PhaseRenderMode
  markOpacity: number
  scatterMarkSize: number
  showGridlines: boolean
  positionConditionRange: PhaseAxisRange
  velocityConditionRange: PhaseAxisRange
  xDomainOverride: PhaseAxisRange | null
  yDomainOverride: PhaseAxisRange | null
  logDensity: boolean
  showZeroLines: boolean
  xLabel: string
}

type PhaseConditionalSeries = PhaseSeries & { values: number[]; matchedCount: number }

function PhaseDiagramGridComponent({
  variant,
  data,
  entities,
  ends,
  layout,
  scopeMode,
  selectedTrack,
  sectors,
  displacementRoles,
  displacementScale,
  densityBins,
  contourMasses,
  conditionalBins,
  renderMode,
  markOpacity,
  scatterMarkSize,
  showGridlines,
  positionConditionRange,
  velocityConditionRange,
  xDomainOverride,
  yDomainOverride,
  logDensity,
  showZeroLines,
  xLabel,
}: PhaseDiagramGridProps) {
  if (ends.length === 0) {
    return <div className="viz-sector-empty"><strong>No ends selected.</strong><span>Select front, rear, or both in the visualization filters.</span></div>
  }
  const orderedEnds = orderedSuspensionEnds(ends)
  const makeEntityOverlaySeries = (items: VisualizationEntity[], end: SuspensionEnd, sector: TrackSector | null) => items.map((entity, index) => ({
    id: `${entity.id}:${end}`,
    label: entity.label,
    color: items.length > 1 ? entityColor(entity, index) : roleColor(end),
    points: phasePointsForEntityEnd(entity, data, displacementRoles[end], `${end}_velocity`, selectedTrack, sector ? [sector] : null, displacementScale),
  }))
  const makeEndOverlaySeries = (entity: VisualizationEntity, sector: TrackSector | null) => orderedEnds.map((end) => ({
    id: `${entity.id}:${end}`,
    label: formatRole(end),
    color: roleColor(end),
    points: phasePointsForEntityEnd(entity, data, displacementRoles[end], `${end}_velocity`, selectedTrack, sector ? [sector] : null, displacementScale),
  }))
  const chartDomain = (series: PhaseSeries[]) => {
    if (xDomainOverride && yDomainOverride) {
      return { x: xDomainOverride, y: yDomainOverride }
    }
    const automatic = phaseDomain(series)
    return { x: xDomainOverride ?? automatic.x, y: yDomainOverride ?? automatic.y }
  }
  const conditionalSeries = (series: PhaseSeries[]): PhaseConditionalSeries[] | null => {
    if (variant !== 'velocity_given_position' && variant !== 'position_given_velocity') {
      return null
    }
    return series.map((item) => {
      const values = phaseConditionalValues(item.points, variant, positionConditionRange, velocityConditionRange)
      return { ...item, values, matchedCount: values.length }
    })
  }
  const renderChart = (
    series: PhaseSeries[],
    domain: { x: PhaseAxisRange; y: PhaseAxisRange },
    conditional: PhaseConditionalSeries[] | null,
    conditionalDomain: PhaseAxisRange | null,
  ) => {
    if (variant === 'contours') {
      return <PhaseProbabilityContourChart contourMasses={contourMasses} densityBins={densityBins} series={series} showGridlines={showGridlines} showZeroLines={showZeroLines} xDomain={domain.x} yDomain={domain.y} xLabel={xLabel} />
    }
    if (variant === 'velocity_given_position' || variant === 'position_given_velocity') {
      return <PhaseConditionalDistributionChart bins={conditionalBins} conditionTitle={phaseConditionalChartTitle(variant, positionConditionRange, velocityConditionRange, xLabel)} series={conditional ?? []} showGridlines={showGridlines} target={variant} xDomain={conditionalDomain ?? [0, 1]} xLabel={xLabel} />
    }
    return <PhaseDensityChart densityBins={densityBins} markOpacity={markOpacity} renderMode={renderMode} logDensity={logDensity} scatterMarkSize={scatterMarkSize} series={series} showGridlines={showGridlines} showZeroLines={showZeroLines} xDomain={domain.x} yDomain={domain.y} xLabel={xLabel} />
  }
  const renderLegend = (series: PhaseSeries[], conditionalSeriesForLegend: PhaseConditionalSeries[] | null) => {
    const conditional = variant === 'velocity_given_position' || variant === 'position_given_velocity'
    const legendSeries = series.map((item) => {
      const matchedCount = conditionalSeriesForLegend?.find((candidate) => candidate.id === item.id)?.matchedCount ?? item.points.length
      return {
        ...item,
        count: matchedCount,
        detail: conditional
          ? `${matchedCount} rows · ${formatProportion(item.points.length ? matchedCount / item.points.length : 0)} of phase samples`
          : undefined,
      }
    })
    return <EntitySeriesLegend series={legendSeries} emptyLabel={conditional ? 'No samples in conditioning window' : 'No paired displacement and velocity samples'} />
  }
  const renderTileContents = (
    series: PhaseSeries[],
    domain: { x: PhaseAxisRange; y: PhaseAxisRange },
    rowConditionalSeries: PhaseConditionalSeries[] | null,
    conditionalDomain: PhaseAxisRange | null,
  ) => {
    const seriesIds = new Set(series.map((item) => item.id))
    const conditional = rowConditionalSeries?.filter((item) => seriesIds.has(item.id)) ?? null
    return <>{renderChart(series, domain, conditional, conditionalDomain)}{renderLegend(series, conditional)}</>
  }

  if (scopeMode === 'sector') {
    if (!selectedTrack || sectors.length === 0) {
      return <div className="viz-sector-empty"><strong>No sector data selected.</strong><span>Select a track and at least one sector in the visualization filters.</span></div>
    }
    return (
      <div className="viz-sector-facet-stack">
        {sectors.map((sector) => {
          const seriesByEnd = orderedEnds.map((end) => ({ end, series: makeEntityOverlaySeries(entities, end, sector) }))
          const rowSeries = seriesByEnd.flatMap((item) => item.series)
          const domain = chartDomain(rowSeries)
          const rowConditionalSeries = conditionalSeries(rowSeries)
          const conditionalDomain = phaseConditionalDataDomain(rowConditionalSeries, variant)
          return (
            <article className="viz-sector-facet" key={sector.id}>
              <header className="viz-sector-section-heading">
                <strong>{sector.label}</strong>
                <span>{formatMetres(sector.lengthM)}</span>
              </header>
              {layout === 'ends' ? (
                <div className="viz-entity-strip responsive phase-diagram-strip" style={responsiveStripStyle(orderedEnds.length, 700)}>
                  {seriesByEnd.map(({ end, series }) => <article className="viz-entity-tile viz-end-tile phase-diagram-tile" key={end}>
                    <EndTileHeader label={formatRole(end)} />
                    {renderTileContents(series, domain, rowConditionalSeries, conditionalDomain)}
                  </article>)}
                </div>
              ) : (
                <div className="viz-entity-strip responsive phase-diagram-strip" style={responsiveStripStyle(entities.length, 700)}>
                  {entities.map((entity) => {
                    const series = makeEndOverlaySeries(entity, sector)
                    return <article className="viz-entity-tile phase-diagram-tile" key={entity.id}>
                      <EntityTileHeader entity={entity} />
                      {renderTileContents(series, domain, rowConditionalSeries, conditionalDomain)}
                    </article>
                  })}
                </div>
              )}
            </article>
          )
        })}
      </div>
    )
  }

  if (layout === 'ends') {
    const allSeries = orderedEnds.map((end) => ({ end, series: makeEntityOverlaySeries(entities, end, null) }))
    const rowSeries = allSeries.flatMap((item) => item.series)
    const domain = chartDomain(rowSeries)
    const rowConditionalSeries = conditionalSeries(rowSeries)
    const conditionalDomain = phaseConditionalDataDomain(rowConditionalSeries, variant)
    return (
      <div className="viz-entity-strip responsive phase-diagram-strip" style={responsiveStripStyle(ends.length, 700)}>
        {allSeries.map(({ end, series }) => <article className="viz-entity-tile viz-end-tile phase-diagram-tile" key={end}>
          <EndTileHeader label={formatRole(end)} />
          {renderTileContents(series, domain, rowConditionalSeries, conditionalDomain)}
        </article>)}
      </div>
    )
  }

  const allSeries = entities.flatMap((entity) => makeEndOverlaySeries(entity, null))
  const domain = chartDomain(allSeries)
  const rowConditionalSeries = conditionalSeries(allSeries)
  const conditionalDomain = phaseConditionalDataDomain(rowConditionalSeries, variant)
  return (
    <div className="viz-entity-strip responsive phase-diagram-strip" style={responsiveStripStyle(entities.length, 700)}>
      {entities.map((entity) => {
        const series = makeEndOverlaySeries(entity, null)
        return <article className="viz-entity-tile phase-diagram-tile" key={entity.id}>
          <EntityTileHeader entity={entity} />
          {renderTileContents(series, domain, rowConditionalSeries, conditionalDomain)}
        </article>
      })}
    </div>
  )
}

const PhaseDiagramGrid = memo(PhaseDiagramGridComponent, phaseDiagramGridPropsEqual)

function phaseDiagramGridPropsEqual(previous: PhaseDiagramGridProps, next: PhaseDiagramGridProps) {
  if (
    previous.variant !== next.variant
    || previous.data !== next.data
    || previous.entities !== next.entities
    || previous.ends !== next.ends
    || previous.layout !== next.layout
    || previous.scopeMode !== next.scopeMode
    || previous.selectedTrack !== next.selectedTrack
    || previous.sectors !== next.sectors
    || previous.displacementRoles.front !== next.displacementRoles.front
    || previous.displacementRoles.rear !== next.displacementRoles.rear
    || previous.displacementScale !== next.displacementScale
    || previous.xLabel !== next.xLabel
  ) {
    return false
  }
  if (next.variant === 'phase') {
    return previous.densityBins === next.densityBins
      && previous.renderMode === next.renderMode
      && previous.markOpacity === next.markOpacity
      && previous.scatterMarkSize === next.scatterMarkSize
      && previous.showGridlines === next.showGridlines
      && previous.logDensity === next.logDensity
      && previous.showZeroLines === next.showZeroLines
      && nullablePhaseAxisRangesEqual(previous.xDomainOverride, next.xDomainOverride)
      && nullablePhaseAxisRangesEqual(previous.yDomainOverride, next.yDomainOverride)
  }
  if (next.variant === 'contours') {
    return previous.densityBins === next.densityBins
      && numericArraysEqual(previous.contourMasses, next.contourMasses)
      && previous.showGridlines === next.showGridlines
      && previous.showZeroLines === next.showZeroLines
      && nullablePhaseAxisRangesEqual(previous.xDomainOverride, next.xDomainOverride)
      && nullablePhaseAxisRangesEqual(previous.yDomainOverride, next.yDomainOverride)
  }
  if (next.variant === 'velocity_given_position') {
    return previous.conditionalBins === next.conditionalBins
      && previous.showGridlines === next.showGridlines
      && phaseAxisRangesEqual(previous.positionConditionRange, next.positionConditionRange)
  }
  return previous.conditionalBins === next.conditionalBins
    && previous.showGridlines === next.showGridlines
    && phaseAxisRangesEqual(previous.velocityConditionRange, next.velocityConditionRange)
}

function numericArraysEqual(left: number[], right: number[]) {
  return left === right || (left.length === right.length && left.every((value, index) => value === right[index]))
}

function nullablePhaseAxisRangesEqual(left: PhaseAxisRange | null, right: PhaseAxisRange | null) {
  return left === right || (left !== null && right !== null && phaseAxisRangesEqual(left, right))
}

function PhaseProbabilityContourChart({
  contourMasses,
  densityBins,
  series,
  showGridlines,
  showZeroLines,
  xDomain,
  yDomain,
  xLabel,
}: {
  contourMasses: number[]
  densityBins: number
  series: PhaseSeries[]
  showGridlines: boolean
  showZeroLines: boolean
  xDomain: PhaseAxisRange
  yDomain: PhaseAxisRange
  xLabel: string
}) {
  const width = 620
  const height = 470
  const margin = { top: 30, right: 16, bottom: 42, left: 56 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom
  const xScale = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const yScale = d3.scaleLinear().domain(yDomain).range([height - margin.bottom, margin.top])
  const contourSeries = series.map((item) => ({
    ...item,
    contours: phaseProbabilityContourPaths(item.points, xDomain, yDomain, densityBins, contourMasses),
  }))
  const hasContours = contourSeries.some((item) => item.contours.length > 0)
  return (
    <svg className="viz-chart viz-phase-contour-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Probability-mass contours: ${xLabel} versus wheel velocity`}>
      <rect fill="#ffffff" height={plotHeight} width={plotWidth} x={margin.left} y={margin.top} />
      {showGridlines && <g stroke="#d9e0dc" strokeWidth="1">
        {xScale.ticks(5).map((tick) => <line key={`grid-x-${tick}`} x1={xScale(tick)} x2={xScale(tick)} y1={margin.top} y2={height - margin.bottom} />)}
        {yScale.ticks(5).map((tick) => <line key={`grid-y-${tick}`} x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />)}
      </g>}
      <g transform={`translate(${margin.left} ${margin.top}) scale(${plotWidth / densityBins} ${plotHeight / densityBins})`}>
        {contourSeries.flatMap((item) => item.contours.map((contour) => (
          <path
            d={contour.d}
            fill="none"
            fillRule="evenodd"
            key={`${item.id}-${contour.mass}`}
            stroke={item.color}
            strokeDasharray={phaseContourDasharray(contour.mass)}
            strokeOpacity={phaseContourStrokeOpacity(contour.mass)}
            strokeWidth={phaseContourStrokeWidth(contour.mass)}
            vectorEffect="non-scaling-stroke"
          >
            <title>{item.label}: {Math.round(contour.mass * 100)}% sample-mass contour</title>
          </path>
        )))}
      </g>
      {showZeroLines && yDomain[0] < 0 && yDomain[1] > 0 && <line stroke="#7b8580" strokeDasharray="3 3" x1={margin.left} x2={width - margin.right} y1={yScale(0)} y2={yScale(0)} />}
      <line stroke="#56615c" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
      <line stroke="#56615c" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
      {xScale.ticks(5).map((tick) => <g key={`x-${tick}`} transform={`translate(${xScale(tick)},${height - margin.bottom})`}><line stroke="#56615c" y2="4" /><text dy="1.25em" textAnchor="middle">{formatPhaseTick(tick)}</text></g>)}
      {yScale.ticks(5).map((tick) => <g key={`y-${tick}`} transform={`translate(${margin.left},${yScale(tick)})`}><line stroke="#56615c" x2="-4" /><text dx="-0.5em" dy="0.32em" textAnchor="end">{formatPhaseTick(tick)}</text></g>)}
      {contourMasses.length > 0 && <g className="viz-phase-contour-level-legend" transform={`translate(${width - margin.right - contourMasses.length * 62} 10)`}>
        {contourMasses.map((mass, index) => <g key={mass} transform={`translate(${index * 62} 0)`}><line stroke="#56615c" strokeDasharray={phaseContourDasharray(mass)} strokeWidth={phaseContourStrokeWidth(mass)} x2="19" y1="5" y2="5" /><text x="23" y="9">{formatContourMass(mass)}</text></g>)}
      </g>}
      <text textAnchor="middle" x={margin.left + plotWidth / 2} y={height - 7}>{xLabel}</text>
      <text textAnchor="middle" transform={`translate(15 ${margin.top + plotHeight / 2}) rotate(-90)`}>wheel velocity (mm/s)</text>
      {!hasContours && <text textAnchor="middle" x={margin.left + plotWidth / 2} y={margin.top + plotHeight / 2}>{contourMasses.length === 0 ? 'No contour levels selected' : 'Not enough paired samples for contours'}</text>}
    </svg>
  )
}

function PhaseConditionalDistributionChart({ bins, conditionTitle, series, showGridlines, target, xDomain, xLabel }: {
  bins: number
  conditionTitle: string
  series: PhaseConditionalSeries[]
  showGridlines: boolean
  target: Extract<PhaseChartVariant, 'velocity_given_position' | 'position_given_velocity'>
  xDomain: PhaseAxisRange
  xLabel: string
}) {
  const width = 620
  const height = 470
  const margin = { top: 42, right: 16, bottom: 42, left: 56 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom
  const velocityTarget = target === 'velocity_given_position'
  const targetLabel = velocityTarget ? 'wheel velocity (mm/s)' : xLabel
  const xScale = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const seriesBins = series.map((item) => ({
    ...item,
    histogram: equalWidthConditionalHistogram(item.values, xDomain, bins),
  }))
  const maximumProportion = Math.max(...seriesBins.flatMap((item) => item.histogram.bins.map((bin) => bin.proportion)), 0)
  const yScale = d3.scaleLinear().domain([0, maximumProportion || 1]).nice(5).range([height - margin.bottom, margin.top])
  const xTicks = xScale.ticks(5)
  const yTicks = yScale.ticks(5)
  const allEmpty = series.every((item) => item.values.length === 0)
  const underflowCount = d3.sum(seriesBins, (item) => item.histogram.underflowCount)
  const overflowCount = d3.sum(seriesBins, (item) => item.histogram.overflowCount)
  const totalCount = d3.sum(seriesBins, (item) => item.histogram.total)
  return (
    <div className="viz-phase-conditional-chart">
      <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Conditional distribution of ${targetLabel}`}>
        <text className="viz-phase-conditional-title" textAnchor="middle" x={margin.left + plotWidth / 2} y={17}>{conditionTitle}</text>
        <rect fill="#f8faf9" height={plotHeight} width={plotWidth} x={margin.left} y={margin.top} />
        {showGridlines && <g stroke="#d9e0dc" strokeWidth="1">
          {xTicks.map((tick) => <line key={`grid-x-${tick}`} x1={xScale(tick)} x2={xScale(tick)} y1={margin.top} y2={height - margin.bottom} />)}
          {yTicks.map((tick) => <line key={`grid-y-${tick}`} x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />)}
        </g>}
        {seriesBins.flatMap((item, seriesIndex) => item.histogram.bins.map((bin) => {
          const bar = histogramBarGeometry(xScale, bin, seriesIndex, Math.max(1, seriesBins.length))
          return <rect
            className="viz-histogram-bar"
            fill={item.color}
            fillOpacity={0.3}
            height={height - margin.bottom - yScale(bin.proportion)}
            key={`${item.id}-${bin.x0}`}
            stroke={item.color}
            strokeOpacity={0.66}
            width={bar.width}
            x={bar.x}
            y={yScale(bin.proportion)}
          ><title>{histogramBinTitle(item.label, bin, targetLabel)}</title></rect>
        }))}
        <line className="viz-axis" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
        <line className="viz-axis" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
        {xTicks.map((tick) => <g key={`x-${tick}`}>
          <line className="viz-tick" x1={xScale(tick)} x2={xScale(tick)} y1={height - margin.bottom} y2={height - margin.bottom + 4} />
          <text className="viz-axis-label" textAnchor="middle" x={xScale(tick)} y={height - margin.bottom + 17}>{formatPhaseTick(tick)}</text>
        </g>)}
        {yTicks.map((tick) => <g key={`y-${tick}`}>
          <line className="viz-tick" x1={margin.left - 4} x2={margin.left} y1={yScale(tick)} y2={yScale(tick)} />
          <text className="viz-axis-label" dominantBaseline="middle" textAnchor="end" x={margin.left - 7} y={yScale(tick)}>{formatProportion(tick)}</text>
        </g>)}
        {underflowCount > 0 && <text className="viz-phase-tail-label" textAnchor="start" x={margin.left} y={34}>← {formatConditionalTailCount(underflowCount, totalCount)} below range</text>}
        {overflowCount > 0 && <text className="viz-phase-tail-label" textAnchor="end" x={width - margin.right} y={34}>{formatConditionalTailCount(overflowCount, totalCount)} above range →</text>}
        <text className="viz-axis-title" textAnchor="middle" x={margin.left + plotWidth / 2} y={height - 7}>{targetLabel}</text>
        <text className="viz-axis-title" textAnchor="middle" transform={`translate(15 ${margin.top + plotHeight / 2}) rotate(-90)`}>conditional proportion</text>
        {allEmpty && <text className="viz-empty-chart" textAnchor="middle" x={margin.left + plotWidth / 2} y={margin.top + plotHeight / 2}>No samples in conditioning window</text>}
      </svg>
    </div>
  )
}

function PhaseDensityChart({ densityBins, markOpacity, renderMode, logDensity, scatterMarkSize, series, showGridlines, showZeroLines, xDomain, yDomain, xLabel }: {
  densityBins: number
  markOpacity: number
  renderMode: PhaseRenderMode
  logDensity: boolean
  scatterMarkSize: number
  series: PhaseSeries[]
  showGridlines: boolean
  showZeroLines: boolean
  xDomain: [number, number]
  yDomain: [number, number]
  xLabel: string
}) {
  if (renderMode !== 'density') {
    return <PhaseCanvasChart markOpacity={markOpacity} renderMode={renderMode} scatterMarkSize={scatterMarkSize} series={series} showGridlines={showGridlines} showZeroLines={showZeroLines} xDomain={xDomain} yDomain={yDomain} xLabel={xLabel} />
  }
  const width = 620
  const height = 470
  const margin = { top: 12, right: 16, bottom: 42, left: 56 }
  const plotWidth = width - margin.left - margin.right
  const plotHeight = height - margin.top - margin.bottom
  const xScale = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const yScale = d3.scaleLinear().domain(yDomain).range([height - margin.bottom, margin.top])
  const hasPoints = series.some((item) => item.points.length > 0)
  return (
    <svg className="viz-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Suspension phase diagram: ${xLabel} versus wheel velocity`}>
      <rect fill="#f8faf9" height={plotHeight} width={plotWidth} x={margin.left} y={margin.top} />
      {showGridlines && <g stroke="#d9e0dc" strokeWidth="1">
        {xScale.ticks(5).map((tick) => <line key={`grid-x-${tick}`} x1={xScale(tick)} x2={xScale(tick)} y1={margin.top} y2={height - margin.bottom} />)}
        {yScale.ticks(5).map((tick) => <line key={`grid-y-${tick}`} x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />)}
      </g>}
      {series.map((item) => phaseDensityCells(item.points, xDomain, yDomain, densityBins).map((cell) => {
        const opacity = densityOpacity(cell.count, cell.maxCount, logDensity)
        return <rect fill={item.color} fillOpacity={opacity} height={Math.max(1, yScale(cell.y0) - yScale(cell.y1))} key={`${item.id}-${cell.xIndex}-${cell.yIndex}`} width={Math.max(1, xScale(cell.x1) - xScale(cell.x0))} x={xScale(cell.x0)} y={yScale(cell.y1)} />
      }))}
      {showZeroLines && yDomain[0] < 0 && yDomain[1] > 0 && <line stroke="#7b8580" strokeDasharray="3 3" x1={margin.left} x2={width - margin.right} y1={yScale(0)} y2={yScale(0)} />}
      <line stroke="#56615c" x1={margin.left} x2={width - margin.right} y1={height - margin.bottom} y2={height - margin.bottom} />
      <line stroke="#56615c" x1={margin.left} x2={margin.left} y1={margin.top} y2={height - margin.bottom} />
      {xScale.ticks(5).map((tick) => <g key={`x-${tick}`} transform={`translate(${xScale(tick)},${height - margin.bottom})`}><line stroke="#56615c" y2="4" /><text dy="1.25em" textAnchor="middle">{formatPhaseTick(tick)}</text></g>)}
      {yScale.ticks(5).map((tick) => <g key={`y-${tick}`} transform={`translate(${margin.left},${yScale(tick)})`}><line stroke="#56615c" x2="-4" /><text dx="-0.5em" dy="0.32em" textAnchor="end">{formatPhaseTick(tick)}</text></g>)}
      <text textAnchor="middle" x={margin.left + plotWidth / 2} y={height - 7}>{xLabel}</text>
      <text textAnchor="middle" transform={`translate(15 ${margin.top + plotHeight / 2}) rotate(-90)`}>wheel velocity (mm/s)</text>
      {!hasPoints && <text textAnchor="middle" x={margin.left + plotWidth / 2} y={margin.top + plotHeight / 2}>No paired samples</text>}
    </svg>
  )
}

function PhaseCanvasChart({ markOpacity, renderMode, scatterMarkSize, series, showGridlines, showZeroLines, xDomain, yDomain, xLabel }: {
  markOpacity: number
  renderMode: Exclude<PhaseRenderMode, 'density'>
  scatterMarkSize: number
  series: PhaseSeries[]
  showGridlines: boolean
  showZeroLines: boolean
  xDomain: [number, number]
  yDomain: [number, number]
  xLabel: string
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const width = 620
  const height = 470
  const deviceScale = 2
  const margin = { top: 12, right: 16, bottom: 42, left: 56 }
  const renderedSeries = useMemo(
    () => series.map((item) => ({ ...item, points: canvasPhasePoints(item.points, renderMode) })),
    [renderMode, series],
  )

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) {
      return
    }
    const plotWidth = width - margin.left - margin.right
    const plotHeight = height - margin.top - margin.bottom
    const xScale = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
    const yScale = d3.scaleLinear().domain(yDomain).range([height - margin.bottom, margin.top])
    context.setTransform(deviceScale, 0, 0, deviceScale, 0, 0)
    context.clearRect(0, 0, width, height)
    context.fillStyle = '#f8faf9'
    context.fillRect(margin.left, margin.top, plotWidth, plotHeight)
    if (showGridlines) {
      context.save()
      context.strokeStyle = '#d9e0dc'
      context.lineWidth = 1
      context.beginPath()
      for (const tick of xScale.ticks(5)) {
        const x = xScale(tick)
        context.moveTo(x, margin.top)
        context.lineTo(x, height - margin.bottom)
      }
      for (const tick of yScale.ticks(5)) {
        const y = yScale(tick)
        context.moveTo(margin.left, y)
        context.lineTo(width - margin.right, y)
      }
      context.stroke()
      context.restore()
    }
    context.save()
    context.beginPath()
    context.rect(margin.left, margin.top, plotWidth, plotHeight)
    context.clip()
    for (const item of renderedSeries) {
      if (renderMode === 'line') {
        context.globalAlpha = markOpacity
        context.strokeStyle = item.color
        context.lineWidth = 1.15
        context.lineCap = 'round'
        context.lineJoin = 'round'
        let started = false
        for (const point of item.points) {
          const x = xScale(point.x)
          const y = yScale(point.y)
          if (!started || point.breakBefore) {
            if (started) {
              context.stroke()
            }
            context.beginPath()
            context.moveTo(x, y)
            started = true
          } else {
            context.lineTo(x, y)
          }
        }
        if (started) {
          context.stroke()
        }
      } else {
        context.globalAlpha = markOpacity
        context.fillStyle = item.color
        for (const point of item.points) {
          context.fillRect(xScale(point.x) - scatterMarkSize / 2, yScale(point.y) - scatterMarkSize / 2, scatterMarkSize, scatterMarkSize)
        }
      }
    }
    context.restore()
    context.globalAlpha = 1
    if (showZeroLines && yDomain[0] < 0 && yDomain[1] > 0) {
      context.save()
      context.strokeStyle = '#7b8580'
      context.setLineDash([3, 3])
      context.beginPath()
      context.moveTo(margin.left, yScale(0))
      context.lineTo(width - margin.right, yScale(0))
      context.stroke()
      context.restore()
    }
    context.strokeStyle = '#56615c'
    context.lineWidth = 1
    context.beginPath()
    context.moveTo(margin.left, height - margin.bottom)
    context.lineTo(width - margin.right, height - margin.bottom)
    context.moveTo(margin.left, margin.top)
    context.lineTo(margin.left, height - margin.bottom)
    context.stroke()
    context.fillStyle = '#3f4a45'
    context.font = '12px system-ui, sans-serif'
    context.textAlign = 'center'
    for (const tick of xScale.ticks(5)) {
      const x = xScale(tick)
      context.beginPath()
      context.moveTo(x, height - margin.bottom)
      context.lineTo(x, height - margin.bottom + 4)
      context.stroke()
      context.fillText(formatPhaseTick(tick), x, height - margin.bottom + 16)
    }
    context.textAlign = 'right'
    for (const tick of yScale.ticks(5)) {
      const y = yScale(tick)
      context.beginPath()
      context.moveTo(margin.left, y)
      context.lineTo(margin.left - 4, y)
      context.stroke()
      context.fillText(formatPhaseTick(tick), margin.left - 7, y + 4)
    }
    context.textAlign = 'center'
    context.fillText(xLabel, margin.left + plotWidth / 2, height - 7)
    context.save()
    context.translate(15, margin.top + plotHeight / 2)
    context.rotate(-Math.PI / 2)
    context.fillText('wheel velocity (mm/s)', 0, 0)
    context.restore()
    if (!renderedSeries.some((item) => item.points.length > 0)) {
      context.fillText('No paired samples', margin.left + plotWidth / 2, margin.top + plotHeight / 2)
    }
  }, [markOpacity, renderMode, renderedSeries, scatterMarkSize, showGridlines, showZeroLines, xDomain, xLabel, yDomain])

  return <canvas className="viz-chart" height={height * deviceScale} ref={canvasRef} role="img" aria-label={`Suspension phase diagram: ${xLabel} versus wheel velocity`} width={width * deviceScale} />
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

function cumulativeSeriesTitle(label: string, sampleCount: number, xLabel: string, directionLabel = '') {
  const direction = directionLabel ? `${directionLabel}\n` : ''
  return sampleCount
    ? `${label}\n${direction}${sampleCount} sample(s)\n${xLabel}: cumulative frequency`
    : `${label}\n${direction}No samples`
}

function cumulativeDistribution(values: number[], xDomain: [number, number]): CumulativeDistribution {
  const key = histogramCacheKey(xDomain, CUMULATIVE_DISTRIBUTION_MAX_POINTS)
  const cached = cumulativeDistributionCache.get(values)
  if (cached?.has(key)) {
    return cached.get(key) ?? { points: [], sortedValues: [], sampleCount: 0 }
  }
  const clean = values
    .filter((value) => Number.isFinite(value) && value >= xDomain[0] && value <= xDomain[1])
    .sort((left, right) => left - right)
  if (clean.length === 0) {
    const empty = { points: [], sortedValues: [], sampleCount: 0 }
    const nextCache = cached ?? new Map<string, CumulativeDistribution>()
    nextCache.set(key, empty)
    if (!cached) {
      cumulativeDistributionCache.set(values, nextCache)
    }
    return empty
  }
  const points: CumulativeDistributionPoint[] = [{ x: xDomain[0], proportion: 0 }]
  let index = 0
  while (index < clean.length) {
    const value = clean[index]
    while (index < clean.length && clean[index] === value) {
      index += 1
    }
    points.push({ x: value, proportion: index / clean.length })
  }
  const lastPoint = points[points.length - 1]
  if (lastPoint && lastPoint.x < xDomain[1]) {
    points.push({ x: xDomain[1], proportion: 1 })
  }
  const distribution = {
    points: downsampleCumulativePoints(points),
    sortedValues: clean,
    sampleCount: clean.length,
  }
  const nextCache = cached ?? new Map<string, CumulativeDistribution>()
  nextCache.set(key, distribution)
  if (!cached) {
    cumulativeDistributionCache.set(values, nextCache)
  }
  return distribution
}

function cumulativeProportionAt(distribution: CumulativeDistribution, value: number) {
  if (distribution.sampleCount === 0) {
    return null
  }
  const count = upperBound(distribution.sortedValues, value)
  return count / distribution.sampleCount
}

function pointerEventXValue(
  event: PointerEvent<SVGSVGElement>,
  chartWidth: number,
  margin: { left: number; right: number },
  xDomain: [number, number],
) {
  const rect = event.currentTarget.getBoundingClientRect()
  const svgX = rect.width > 0 ? ((event.clientX - rect.left) / rect.width) * chartWidth : margin.left
  const clampedX = clamp(svgX, margin.left, chartWidth - margin.right)
  const plotFraction = (clampedX - margin.left) / Math.max(1, chartWidth - margin.left - margin.right)
  return xDomain[0] + plotFraction * (xDomain[1] - xDomain[0])
}

function cumulativeHoverTitle(value: number, xLabel: string) {
  const unit = shortAxisUnit(xLabel)
  return unit ? `${formatAxis(value)} ${unit}` : formatAxis(value)
}

function shortAxisUnit(label: string) {
  const parenthesized = label.match(/\(([^)]+)\)\s*$/)
  if (parenthesized) {
    return parenthesized[1]
  }
  const commaIndex = label.lastIndexOf(',')
  return commaIndex >= 0 ? label.slice(commaIndex + 1).trim() : ''
}

function compactSvgLabel(label: string, maxLength: number) {
  return label.length > maxLength ? `${label.slice(0, Math.max(0, maxLength - 1))}...` : label
}

function downsampleCumulativePoints(points: CumulativeDistributionPoint[]) {
  if (points.length <= CUMULATIVE_DISTRIBUTION_MAX_POINTS) {
    return points
  }
  const out: CumulativeDistributionPoint[] = []
  const lastIndex = points.length - 1
  for (let index = 0; index < CUMULATIVE_DISTRIBUTION_MAX_POINTS; index += 1) {
    out.push(points[Math.round((index / (CUMULATIVE_DISTRIBUTION_MAX_POINTS - 1)) * lastIndex)])
  }
  return out
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

function FrequencyChartBlock({
  bins,
  displacementStatsFormatter = formatPercentValue,
  displayMode,
  series,
  showDisplacementGlyphs,
  xDomain,
  xLabel,
  yLabel,
  yMax,
}: {
  bins: number
  displacementStatsFormatter?: (value: number | null) => string
  displayMode: FrequencyDisplayMode
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  showDisplacementGlyphs: boolean
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  yMax: number
}) {
  const displacementGlyphPlacement: DisplacementGlyphPlacement | null = showDisplacementGlyphs
    ? displayMode === 'cumulative'
      ? 'bottom'
      : 'top'
    : null
  return (
    <div className="viz-frequency-chart-block">
      {displayMode === 'cumulative' ? (
        <CumulativeFrequencyChart
          displacementGlyphPlacement={displacementGlyphPlacement}
          displacementStatsFormatter={displacementStatsFormatter}
          series={series}
          xDomain={xDomain}
          xLabel={xLabel}
          yLabel={yLabel}
        />
      ) : series.length <= 2 ? (
        <HistogramOverlayChart
          bins={bins}
          displacementGlyphPlacement={displacementGlyphPlacement}
          displacementStatsFormatter={displacementStatsFormatter}
          series={series}
          xDomain={xDomain}
          xLabel={xLabel}
          yLabel={yLabel}
          yMax={yMax}
        />
      ) : (
        <MultiHistogramChart
          bins={bins}
          displacementGlyphPlacement={displacementGlyphPlacement}
          displacementStatsFormatter={displacementStatsFormatter}
          series={series}
          xDomain={xDomain}
          xLabel={xLabel}
          yLabel={yLabel}
          yMax={yMax}
        />
      )}
    </div>
  )
}

function HistogramOverlayChart({
  displacementGlyphPlacement,
  displacementStatsFormatter,
  series,
  xDomain,
  xLabel,
  yLabel,
  bins,
  yMax,
}: {
  displacementGlyphPlacement: DisplacementGlyphPlacement | null
  displacementStatsFormatter: (value: number | null) => string
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 205
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
      {displacementGlyphPlacement && (
        <DisplacementStatsGlyphOverlay
          formatter={displacementStatsFormatter}
          height={height}
          margin={margin}
          placement={displacementGlyphPlacement}
          series={series}
          width={width}
          xDomain={xDomain}
        />
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
  displacementGlyphPlacement,
  displacementStatsFormatter,
  series,
  xDomain,
  xLabel,
  yLabel,
  bins,
  yMax,
}: {
  displacementGlyphPlacement: DisplacementGlyphPlacement | null
  displacementStatsFormatter: (value: number | null) => string
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
}) {
  const width = 324
  const height = 205
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
      {displacementGlyphPlacement && (
        <DisplacementStatsGlyphOverlay
          formatter={displacementStatsFormatter}
          height={height}
          margin={margin}
          placement={displacementGlyphPlacement}
          series={series}
          width={width}
          xDomain={xDomain}
        />
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

function CumulativeFrequencyChart({
  displacementGlyphPlacement,
  displacementStatsFormatter,
  series,
  xDomain,
  xLabel,
  yLabel,
}: {
  displacementGlyphPlacement: DisplacementGlyphPlacement | null
  displacementStatsFormatter: (value: number | null) => string
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
}) {
  const width = 324
  const height = 205
  const margin = { top: 12, right: 12, bottom: 34, left: 34 }
  const [hoverX, setHoverX] = useState<number | null>(null)
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const y = d3.scaleLinear().domain([0, 1]).range([height - margin.bottom, margin.top])
  const distributions = series.map((item) => ({
    ...item,
    distribution: cumulativeDistribution(item.values, xDomain),
  }))
  const line = d3
    .line<CumulativeDistributionPoint>()
    .x((point) => x(point.x))
    .y((point) => y(point.proportion))
    .curve(d3.curveStepAfter)
  const allEmpty = distributions.every((item) => item.distribution.sampleCount === 0)
  const hoverItems = hoverX === null
    ? []
    : distributions
        .map((item) => ({
          id: item.id,
          label: item.label,
          color: item.color,
          proportion: cumulativeProportionAt(item.distribution, hoverX),
        }))
        .filter((item): item is { id: string; label: string; color: string; proportion: number } => item.proportion !== null)
  return (
    <svg
      className="viz-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={xLabel}
      onPointerLeave={() => setHoverX(null)}
      onPointerMove={(event) => setHoverX(pointerEventXValue(event, width, margin, xDomain))}
    >
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
      {[0, 0.5, 1].map((tick) => (
        <g key={`y-${tick}`}>
          <line className="viz-grid-line" x1={margin.left} x2={width - margin.right} y1={y(tick)} y2={y(tick)} />
        </g>
      ))}
      {distributions.map((item) => {
        const path = line(item.distribution.points)
        return path ? (
          <path className="viz-series-line" d={path} key={item.id} stroke={item.color}>
            <title>{cumulativeSeriesTitle(item.label, item.distribution.sampleCount, xLabel)}</title>
          </path>
        ) : null
      })}
      {displacementGlyphPlacement && (
        <DisplacementStatsGlyphOverlay
          formatter={displacementStatsFormatter}
          height={height}
          margin={margin}
          placement={displacementGlyphPlacement}
          series={series}
          width={width}
          xDomain={xDomain}
        />
      )}
      {hoverX !== null && hoverItems.length > 0 && (
        <>
          <line className="viz-cumulative-hover-line" x1={x(hoverX)} x2={x(hoverX)} y1={margin.top} y2={height - margin.bottom} />
          <CumulativeHoverReadout
            chartWidth={width}
            items={hoverItems}
            title={cumulativeHoverTitle(hoverX, xLabel)}
            x={x(hoverX)}
            y={margin.top + 8}
          />
        </>
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

function CumulativeHoverReadout({
  chartWidth,
  items,
  title,
  x,
  y,
}: {
  chartWidth: number
  items: Array<{ id: string; label: string; color: string; proportion: number }>
  title: string
  x: number
  y: number
}) {
  const boxWidth = 142
  const rowHeight = 12
  const boxHeight = 20 + items.length * rowHeight
  const boxX = clamp(x + 8, 6, chartWidth - boxWidth - 6)
  return (
    <g className="viz-cumulative-tooltip" transform={`translate(${boxX} ${y})`}>
      <rect width={boxWidth} height={boxHeight} rx={3} />
      <text className="viz-cumulative-tooltip-title" x={8} y={13}>
        {title}
      </text>
      {items.map((item, index) => (
        <g key={item.id} transform={`translate(8 ${24 + index * rowHeight})`}>
          <circle cx={3} cy={-3} fill={item.color} r={2.5} />
          <text x={10} y={0}>
            {compactSvgLabel(item.label, 18)}
          </text>
          <text x={boxWidth - 16} y={0} textAnchor="end">
            {formatProportion(item.proportion)}
          </text>
        </g>
      ))}
    </g>
  )
}

function MirroredVelocityChart({
  series,
  xDomain,
  xLabel,
  yLabel,
  bins,
  yMax,
  displayMode,
  showStatsOnChart = false,
  statsFormatter = formatMetricValue,
}: {
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  xDomain: [number, number]
  xLabel: string
  yLabel: string
  bins: number
  yMax: number
  displayMode: FrequencyDisplayMode
  showStatsOnChart?: boolean
  statsFormatter?: (value: number | null) => string
}) {
  const width = 324
  const height = 202
  const margin = { top: 22, right: 12, bottom: 34, left: 38 }
  const [hoverX, setHoverX] = useState<number | null>(null)
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const mirroredBins =
    displayMode === 'histogram'
      ? series.map((item) => ({
          ...item,
          ...mirroredVelocityBins(item.values, xDomain, bins),
        }))
      : []
  const localYMax =
    displayMode === 'cumulative'
      ? 1
      : Math.max(...mirroredBins.flatMap((item) => [...item.compression, ...item.rebound].map((bin) => bin.proportion)), 0) ||
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
  const cumulativeLine = d3
    .line<CumulativeDistributionPoint>()
    .x((point) => x(point.x))
    .y((point) => y(point.proportion))
    .curve(d3.curveStepAfter)
  const mirroredCumulativeLine = d3
    .line<CumulativeDistributionPoint>()
    .x((point) => x(point.x))
    .y((point) => y(-point.proportion))
    .curve(d3.curveStepAfter)
  const allEmpty = series.every((item) => item.values.length === 0)
  const renderBars = displayMode === 'histogram' && series.length <= 2
  const seriesCount = Math.max(1, series.length)
  const cumulativeDistributions = displayMode === 'cumulative'
    ? series.map((item) => ({
        ...item,
        compressionDistribution: cumulativeDistribution(
          item.values.filter((value) => value >= 0),
          xDomain,
        ),
        reboundDistribution: cumulativeDistribution(
          item.values.filter((value) => value < 0).map((value) => -value),
          xDomain,
        ),
      }))
    : []
  const hoverItems = hoverX === null
    ? []
    : cumulativeDistributions
        .flatMap((item) => [
          {
            id: `${item.id}:compression`,
            label: `${item.label} compression`,
            color: item.color,
            proportion: cumulativeProportionAt(item.compressionDistribution, hoverX),
          },
          {
            id: `${item.id}:rebound`,
            label: `${item.label} rebound`,
            color: item.color,
            proportion: cumulativeProportionAt(item.reboundDistribution, hoverX),
          },
        ])
        .filter((item): item is { id: string; label: string; color: string; proportion: number } => item.proportion !== null)
  return (
    <svg
      className="viz-chart viz-mirrored-velocity-chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={xLabel}
      onPointerLeave={() => setHoverX(null)}
      onPointerMove={(event) => displayMode === 'cumulative' && setHoverX(pointerEventXValue(event, width, margin, xDomain))}
    >
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
      {displayMode === 'cumulative'
        ? cumulativeDistributions.map((item) => {
            const compressionPath = cumulativeLine(item.compressionDistribution.points)
            const reboundPath = mirroredCumulativeLine(item.reboundDistribution.points)
            return (
              <g key={item.id}>
                {compressionPath && (
                  <path className="viz-series-line" d={compressionPath} stroke={item.color}>
                    <title>{cumulativeSeriesTitle(item.label, item.compressionDistribution.sampleCount, xLabel, 'Compression')}</title>
                  </path>
                )}
                {reboundPath && (
                  <path className="viz-series-line" d={reboundPath} stroke={item.color}>
                    <title>{cumulativeSeriesTitle(item.label, item.reboundDistribution.sampleCount, xLabel, 'Rebound')}</title>
                  </path>
                )}
              </g>
            )
          })
        : renderBars
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
      {showStatsOnChart && (
        <MirroredStatsGlyphOverlay
          displayMode={displayMode}
          formatter={statsFormatter}
          height={height}
          margin={margin}
          series={series}
          width={width}
          xDomain={xDomain}
          y={y}
        />
      )}
      {displayMode === 'cumulative' && hoverX !== null && hoverItems.length > 0 && (
        <>
          <line className="viz-cumulative-hover-line" x1={x(hoverX)} x2={x(hoverX)} y1={margin.top} y2={height - margin.bottom} />
          <CumulativeHoverReadout
            chartWidth={width}
            items={hoverItems}
            title={cumulativeHoverTitle(hoverX, xLabel)}
            x={x(hoverX)}
            y={margin.top + 8}
          />
        </>
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
  series: Array<{ id: string; label: string; color: string; count: number; detail?: string }>
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
          <small>{item.detail ?? (item.count ? `${item.count} rows` : emptyLabel)}</small>
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
  splitMirrored = false,
  transform,
}: {
  formatter: (value: number | null) => string
  mode?: DistributionStatsMode
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  splitMirrored?: boolean
  transform: (value: number) => number
}) {
  return (
    <div className="viz-stat-grid">
      {series.flatMap((item) =>
        splitMirrored
          ? [
              <RoleStats
                color={item.color}
                formatter={formatter}
                key={`${item.id}-compression`}
                label={`${item.label} compression`}
                mode={mode}
                transform={transform}
                values={item.values.filter((value) => value >= 0)}
              />,
              <RoleStats
                color={item.color}
                formatter={formatter}
                key={`${item.id}-rebound`}
                label={`${item.label} rebound`}
                mode={mode}
                transform={transform}
                values={item.values.filter((value) => value < 0)}
              />,
            ]
          : [
              <RoleStats
                color={item.color}
                formatter={formatter}
                key={item.id}
                label={item.label}
                mode={mode}
                transform={transform}
                values={item.values}
              />,
            ],
      )}
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

function DisplacementStatsGlyphOverlay({
  formatter,
  height,
  margin,
  placement,
  series,
  width,
  xDomain,
}: {
  formatter: (value: number | null) => string
  height: number
  margin: { left: number; right: number; top: number; bottom: number }
  placement: DisplacementGlyphPlacement
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  width: number
  xDomain: [number, number]
}) {
  const rows = series
    .map((item) => ({
      ...item,
      stats: distributionStats(item.values),
    }))
    .filter((item) => item.stats.q25 !== null && item.stats.median !== null && item.stats.q75 !== null && item.stats.p95 !== null && item.stats.max !== null)
  if (rows.length === 0) {
    return null
  }
  const rowHeight = 10
  const stackHeight = rows.length * rowHeight
  const y = placement === 'top' ? margin.top + 7 : height - margin.bottom - stackHeight - 7
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  return (
    <g className={`viz-displacement-glyph-overlay ${placement}`} aria-label="Displacement distribution summaries" transform={`translate(0 ${y})`}>
      {rows.map((row, index) => (
        <DisplacementStatsGlyph
          color={row.color}
          formatter={formatter}
          key={row.id}
          label={row.label}
          stats={row.stats}
          x={x}
          xDomain={xDomain}
          y={index * rowHeight}
        />
      ))}
    </g>
  )
}

function MirroredStatsGlyphOverlay({
  displayMode,
  formatter,
  height,
  margin,
  series,
  width,
  xDomain,
  y,
}: {
  displayMode: FrequencyDisplayMode
  formatter: (value: number | null) => string
  height: number
  margin: { left: number; right: number; top: number; bottom: number }
  series: Array<{ id: string; label: string; color: string; values: number[] }>
  width: number
  xDomain: [number, number]
  y: d3.ScaleLinear<number, number>
}) {
  const compressionRows = series
    .map((item) => ({
      color: item.color,
      id: `${item.id}:compression`,
      label: `${item.label} compression`,
      stats: distributionStats(item.values.filter((value) => value >= 0)),
    }))
    .filter((item) => item.stats.q25 !== null && item.stats.median !== null && item.stats.q75 !== null && item.stats.p95 !== null && item.stats.max !== null)
  const reboundRows = series
    .map((item) => ({
      color: item.color,
      id: `${item.id}:rebound`,
      label: `${item.label} rebound`,
      stats: distributionStats(item.values.filter((value) => value < 0).map((value) => -value)),
    }))
    .filter((item) => item.stats.q25 !== null && item.stats.median !== null && item.stats.q75 !== null && item.stats.p95 !== null && item.stats.max !== null)
  if (compressionRows.length === 0 && reboundRows.length === 0) {
    return null
  }
  const rowHeight = 8
  const x = d3.scaleLinear().domain(xDomain).range([margin.left, width - margin.right])
  const zeroY = y(0)
  const compressionStackHeight = compressionRows.length * rowHeight
  const reboundStackHeight = reboundRows.length * rowHeight
  const compressionY =
    displayMode === 'histogram'
      ? margin.top + 7
      : Math.max(margin.top + 4, zeroY - compressionStackHeight - 7)
  const reboundY =
    displayMode === 'histogram'
      ? height - margin.bottom - reboundStackHeight - 7
      : Math.min(height - margin.bottom - reboundStackHeight - 3, zeroY + 7)
  return (
    <g className="viz-displacement-glyph-overlay mirrored" aria-label="Mirrored distribution summaries">
      <g transform={`translate(0 ${compressionY})`}>
        {compressionRows.map((row, index) => (
          <DisplacementStatsGlyph
            color={row.color}
            formatter={formatter}
            key={row.id}
            label={row.label}
            stats={row.stats}
            x={x}
            xDomain={xDomain}
            y={index * rowHeight}
          />
        ))}
      </g>
      <g transform={`translate(0 ${reboundY})`}>
        {reboundRows.map((row, index) => (
          <DisplacementStatsGlyph
            color={row.color}
            formatter={formatter}
            key={row.id}
            label={row.label}
            stats={row.stats}
            x={x}
            xDomain={xDomain}
            y={index * rowHeight}
          />
        ))}
      </g>
    </g>
  )
}

function DisplacementStatsGlyph({
  color,
  formatter,
  label,
  stats,
  x,
  y,
  xDomain,
}: {
  color: string
  formatter: (value: number | null) => string
  label: string
  stats: ReturnType<typeof distributionStats>
  x: d3.ScaleLinear<number, number>
  y: number
  xDomain: [number, number]
}) {
  if (
    stats.q25 === null ||
    stats.median === null ||
    stats.q75 === null ||
    stats.p95 === null ||
    stats.max === null
  ) {
    return null
  }
  const q25 = clamp(stats.q25, xDomain[0], xDomain[1])
  const median = clamp(stats.median, xDomain[0], xDomain[1])
  const q75 = clamp(stats.q75, xDomain[0], xDomain[1])
  const p95 = clamp(stats.p95, xDomain[0], xDomain[1])
  const max = clamp(stats.max, xDomain[0], xDomain[1])
  return (
    <g className="viz-displacement-glyph-row" transform={`translate(0 ${y})`}>
      <title>{`${label}\nmedian ${formatter(stats.median)}; IQR ${formatter(stats.iqr)}; P95 ${formatter(stats.p95)}; max ${formatter(stats.max)}`}</title>
      <line className="viz-displacement-glyph-whisker" x1={x(q75)} x2={x(max)} y1={5} y2={5} />
      <rect
        className="viz-displacement-glyph-iqr"
        fill={color}
        height={3}
        rx={1}
        stroke={color}
        width={Math.max(2, x(q75) - x(q25))}
        x={x(q25)}
        y={3.5}
      />
      <line className="viz-displacement-glyph-median" x1={x(median)} x2={x(median)} y1={2.5} y2={7.5} />
      <line className="viz-displacement-glyph-p95" x1={x(p95)} x2={x(p95)} y1={2.5} y2={7.5} />
      <line className="viz-displacement-glyph-max" x1={x(max)} x2={x(max)} y1={3} y2={7} />
    </g>
  )
}

function resolvedDisplacementSignalChoices(
  sessionRefs: StudySessionRef[],
  sessions: SessionRecord[],
  selections: SignalChoiceSelections,
  configs: readonly DisplacementSignalRoleConfig[],
): SignalChoiceSelections {
  const resolved: SignalChoiceSelections = {}
  for (const sessionRef of sessionRefs) {
    const session = sessionByRef(sessionRef, sessions)
    if (!session) {
      continue
    }
    const refId = sessionRefId(sessionRef)
    for (const config of configs) {
      const candidates = displacementSignalCandidates(session, config)
      if (candidates.length === 0) {
        continue
      }
      const key = signalChoiceKey(refId, config.role)
      const selected = selections[key]
      resolved[key] = candidates.some((signal) => signal.column === selected) ? selected : candidates[0].column
    }
  }
  return resolved
}

function displacementSignalRoleConfigs(mode: DisplacementUnitMode): readonly DisplacementSignalRoleConfig[] {
  return mode === 'mm' ? MM_DISPLACEMENT_SIGNAL_ROLE_CONFIGS : NORMALIZED_DISPLACEMENT_SIGNAL_ROLE_CONFIGS
}

function duplicateDisplacementSignalChoiceGroups(
  sessionRefs: StudySessionRef[],
  sessions: SessionRecord[],
  selections: SignalChoiceSelections,
  configs: readonly DisplacementSignalRoleConfig[],
): SignalChoiceGroup[] {
  const groups: SignalChoiceGroup[] = []
  for (const sessionRef of sessionRefs) {
    const session = sessionByRef(sessionRef, sessions)
    if (!session) {
      continue
    }
    const refId = sessionRefId(sessionRef)
    for (const config of configs) {
      const candidates = displacementSignalCandidates(session, config)
      if (candidates.length <= 1) {
        continue
      }
      const key = signalChoiceKey(refId, config.role)
      groups.push({
        key,
        role: config.role,
        roleLabel: config.label,
        sessionLabel: session.name || sessionRef.label || sessionRef.sessionId,
        selectedColumn: selections[key] ?? candidates[0].column,
        candidates,
      })
    }
  }
  return groups
}

function displacementSignalCandidates(session: SessionRecord, config: DisplacementSignalRoleConfig) {
  const candidates = [...(session.availableSignals ?? [])]
    .filter((signal) => displacementSignalCandidateMatches(signal, config))
    .sort(compareDisplacementSignalCandidates)
  const groups = displacementSignalCandidateGroups(candidates)
  const duplicateGroups = groups.filter((group) => group.length > 1)
  return duplicateGroups[0] ?? groups[0] ?? []
}

function displacementSignalCandidateMatches(signal: SessionSignalSummary, config: DisplacementSignalRoleConfig) {
  const quantity = normalizeSignalText(signal.quantity)
  const unit = normalizeSignalText(signal.unit)
  const expectedQuantity = normalizeSignalText(config.selector.quantity)
  const expectedUnit = normalizeSignalText(config.selector.unit)
  return (
    normalizeSignalText(signal.end) === config.end &&
    normalizeSignalText(signal.domain) === 'wheel' &&
    quantity === expectedQuantity &&
    (expectedUnit === 'mm' ? isMillimetreUnit(unit) : unit === expectedUnit)
  )
}

function normalizeSignalText(value: unknown) {
  return String(value ?? '').trim().toLowerCase()
}

function isMillimetreUnit(unit: string) {
  return ['mm', 'millimeter', 'millimeters', 'millimetre', 'millimetres'].includes(unit)
}

function displacementSignalCandidateGroups(candidates: SessionSignalSummary[]) {
  const groups = new Map<string, SessionSignalSummary[]>()
  for (const signal of candidates) {
    const key = displacementSignalSemanticKey(signal)
    groups.set(key, [...(groups.get(key) ?? []), signal])
  }
  return Array.from(groups.values()).sort(compareDisplacementSignalCandidateGroups)
}

function displacementSignalSemanticKey(signal: SessionSignalSummary) {
  return [
    normalizeSignalText(signal.end),
    normalizeSignalText(signal.domain),
    normalizeSignalText(signal.quantity),
    normalizeSignalText(signal.unit),
  ].join('|')
}

function compareDisplacementSignalCandidateGroups(left: SessionSignalSummary[], right: SessionSignalSummary[]) {
  return (
    displacementSignalCandidateGroupScore(left) - displacementSignalCandidateGroupScore(right) ||
    displacementSignalSemanticKey(left[0]).localeCompare(displacementSignalSemanticKey(right[0]))
  )
}

function displacementSignalCandidateGroupScore(group: SessionSignalSummary[]) {
  const signal = group[0]
  const quantity = normalizeSignalText(signal.quantity)
  const unit = normalizeSignalText(signal.unit)
  if (quantity === 'disp_norm' && unit === '1') {
    return 0
  }
  if (quantity === 'disp' && isMillimetreUnit(unit)) {
    return 1
  }
  return 99
}

function compareDisplacementSignalCandidates(left: SessionSignalSummary, right: SessionSignalSummary) {
  return displacementSignalCandidateScore(left) - displacementSignalCandidateScore(right) || left.column.localeCompare(right.column)
}

function displacementSignalCandidateScore(signal: SessionSignalSummary) {
  const roleScore = normalizeSignalText(signal.processingRole) === 'primary_analysis' ? 0 : 2
  const kind = normalizeSignalText(signal.kind)
  const kindScore = kind && !['raw', 'qc'].includes(kind) ? 0 : 1
  return roleScore + kindScore
}

function signalChoiceLabel(signal: SessionSignalSummary) {
  const base = signal.displayName || signal.column
  const motionSource = signal.motionSourceId?.trim()
  return motionSource ? `${base} (${motionSource})` : base
}

function signalChoiceDetail(signal: SessionSignalSummary) {
  return [signal.domain, signal.quantity, signal.unit, signal.column].filter(Boolean).join(' / ')
}

function signalChoiceKey(sessionRefIdValue: string, role: DisplacementSignalRole) {
  return `${sessionRefIdValue}|${role}`
}

function signalChoiceSelectionSignature(selections: SignalChoiceSelections) {
  return Object.entries(selections)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, column]) => `${key}=${column}`)
    .join(';')
}

function visualizationSessionCacheKey(
  sessionRef: StudySessionRef,
  signalChoices: SignalChoiceSelections,
  displacementMode: DisplacementUnitMode,
  mode: SuspensionVisualizationMode,
) {
  const refId = sessionRefId(sessionRef)
  const displacementChoices = displacementSignalRoleConfigs(displacementMode)
    .map((config) => `${config.role}:${signalChoices[signalChoiceKey(refId, config.role)] ?? ''}`)
    .join('|')
  return `v${VISUALIZATION_SESSION_CACHE_VERSION}|${mode}|${refId}|disp:${displacementMode}|${displacementChoices}`
}

function visualizationCacheMissCount(
  dataSource: LibraryDataSource,
  requestedSessionRefs: StudySessionRef[],
  signalChoices: SignalChoiceSelections,
  displacementMode: DisplacementUnitMode,
  mode: SuspensionVisualizationMode,
) {
  const sessionCache = suspensionSessionCache<CachedSessionVisualizationData>(dataSource)
  return uniqueSessionRefs(requestedSessionRefs).filter((sessionRef) => {
    const cacheKey = visualizationSessionCacheKey(sessionRef, signalChoices, displacementMode, mode)
    return !sessionCache.entries.has(cacheKey) && !sessionCache.inFlight.has(cacheKey)
  }).length
}

function signalRequestsForSession(
  sessionRef: StudySessionRef,
  signalChoices: SignalChoiceSelections,
  displacementMode: DisplacementUnitMode,
  mode: SuspensionVisualizationMode,
): SignalQuerySignalRequest[] {
  const refId = sessionRefId(sessionRef)
  return [
    ...displacementSignalRoleConfigs(displacementMode).map((config): SignalQuerySignalRequest => {
      const column = signalChoices[signalChoiceKey(refId, config.role)]
      return column ? { role: config.role, column } : { role: config.role, selector: config.selector }
    }),
    ...(mode === 'phase' ? VELOCITY_SIGNAL_ROLE_CONFIGS.map((config): SignalQuerySignalRequest => ({ role: config.role, selector: config.selector })) : []),
    ...SIGNAL_REQUESTS,
  ]
}

async function loadVisualizationData(
  requestedSessionRefs: StudySessionRef[],
  signalChoices: SignalChoiceSelections,
  displacementMode: DisplacementUnitMode,
  sessions: SessionRecord[],
  dataSource: LibraryDataSource,
  mode: SuspensionVisualizationMode,
): Promise<VisualizationLoadResult> {
  const sessionRefs = uniqueSessionRefs(requestedSessionRefs)
  const diagnostics = startSuspensionCacheDiagnostics(sessionRefs.length)
  const sessionCache = suspensionSessionCache<CachedSessionVisualizationData>(dataSource)
  const refsNeedingData: StudySessionRef[] = []

  for (const sessionRef of sessionRefs) {
    const cacheKey = visualizationSessionCacheKey(sessionRef, signalChoices, displacementMode, mode)
    if (getSuspensionCacheEntry(sessionCache, cacheKey)) {
      diagnostics.cacheHitCount += 1
    } else if (sessionCache.inFlight.has(cacheKey)) {
      diagnostics.inFlightHitCount += 1
      refsNeedingData.push(sessionRef)
    } else {
      diagnostics.cacheMissCount += 1
      refsNeedingData.push(sessionRef)
    }
  }

  for (const [libraryId, refs] of groupRefsByLibrary(refsNeedingData).entries()) {
    const inFlightRequests: Promise<CachedSessionVisualizationData>[] = []
    const refsToFetch: StudySessionRef[] = []

    for (const ref of refs) {
      const cacheKey = visualizationSessionCacheKey(ref, signalChoices, displacementMode, mode)
      const inFlight = sessionCache.inFlight.get(cacheKey)
      if (inFlight) {
        inFlightRequests.push(inFlight)
      } else {
        refsToFetch.push(ref)
      }
    }

    if (refsToFetch.length > 0) {
      const fetchStartedAtMs = suspensionCacheNowMs()
      diagnostics.fetchBatchCount += 1
      diagnostics.fetchedSessionCount += refsToFetch.length
      let fetchDurationRecorded = false
      const recordFetchDuration = () => {
        if (!fetchDurationRecorded) {
          diagnostics.fetchDurationMs += suspensionCacheNowMs() - fetchStartedAtMs
          fetchDurationRecorded = true
        }
      }
      const batchPromise = fetchVisualizationLibrarySessions(
        libraryId,
        refsToFetch,
        signalChoices,
        displacementMode,
        sessions,
        dataSource,
        mode,
      ).then(
        (fetchedSessions) => {
          recordFetchDuration()
          for (const cached of fetchedSessions.values()) {
            setSuspensionCacheEntry(sessionCache, visualizationSessionCacheKey(cached.sessionRef, signalChoices, displacementMode, mode), cached)
          }
          return fetchedSessions
        },
        (error) => {
          recordFetchDuration()
          throw error
        },
      )

      for (const ref of refsToFetch) {
        const cacheKey = visualizationSessionCacheKey(ref, signalChoices, displacementMode, mode)
        sessionCache.inFlight.set(
          cacheKey,
          batchPromise.then((fetchedSessions) => fetchedSessions.get(sessionRefId(ref)) ?? emptyCachedSession(ref)),
        )
      }

      try {
        await batchPromise
      } finally {
        for (const ref of refsToFetch) {
          sessionCache.inFlight.delete(visualizationSessionCacheKey(ref, signalChoices, displacementMode, mode))
        }
      }
    }

    if (inFlightRequests.length > 0) {
      const fetchedSessions = await Promise.all(inFlightRequests)
      for (const cached of fetchedSessions) {
        setSuspensionCacheEntry(sessionCache, visualizationSessionCacheKey(cached.sessionRef, signalChoices, displacementMode, mode), cached)
      }
    }
  }

  const sessionCacheKeys = sessionRefs.map((sessionRef) => visualizationSessionCacheKey(sessionRef, signalChoices, displacementMode, mode))
  const composedCacheKey = `visualization-data|${sessionCacheKeys.join('\n')}`
  const composedData = getSuspensionComposedCacheEntry<VisualizationData>(sessionCache, composedCacheKey)
  if (composedData) {
    diagnostics.composedCacheHitCount += 1
    finishSuspensionCacheDiagnostics(diagnostics)
    return { data: composedData, diagnostics }
  }

  const composeStartedAtMs = suspensionCacheNowMs()
  const cachedSessions = sessionRefs.map((sessionRef, index) => (
    getSuspensionCacheEntry(sessionCache, sessionCacheKeys[index] ?? '') ?? emptyCachedSession(sessionRef)
  ))
  const eventRows = cachedSessions.flatMap((session) => session.events)
  const metricRows = cachedSessions.flatMap((session) => session.metrics)
  const data = {
    timeBySession: Object.fromEntries(cachedSessions.map((session) => [sessionRefId(session.sessionRef), session.time])),
    signalsBySession: Object.fromEntries(cachedSessions.map((session) => [sessionRefId(session.sessionRef), session.signals])),
    events: eventRows,
    eventTriggerTimeByKey: eventTriggerTimeMap(eventRows),
    metrics: metricRows,
    warnings: uniqueStrings(cachedSessions.flatMap((session) => session.warnings).filter(Boolean)),
  }
  setSuspensionComposedCacheEntry(sessionCache, composedCacheKey, data)
  diagnostics.composeDurationMs += suspensionCacheNowMs() - composeStartedAtMs
  finishSuspensionCacheDiagnostics(diagnostics)

  return { data, diagnostics }
}

async function fetchVisualizationLibrarySessions(
  libraryId: string,
  refs: StudySessionRef[],
  signalChoices: SignalChoiceSelections,
  displacementMode: DisplacementUnitMode,
  sessions: SessionRecord[],
  dataSource: LibraryDataSource,
  mode: SuspensionVisualizationMode,
) {
  const [signalResponses, events, metrics] = await Promise.all([
    Promise.all(
      refs.map((ref) =>
        dataSource.querySignals(libraryId, {
          sessions: [ref],
          signals: signalRequestsForSession(ref, signalChoices, displacementMode, mode),
        }),
      ),
    ),
    mode === 'simple' ? dataSource.queryEvents(libraryId, { sessions: refs }) : Promise.resolve({ rows: [], warnings: [] }),
    mode === 'simple'
      ? dataSource.queryMetrics(libraryId, { sessions: refs, eventTypes: [COMPRESSION_EVENT_TYPE, REBOUND_EVENT_TYPE] })
      : Promise.resolve({ rows: [], warnings: [] }),
  ])
  const signalWarnings = signalResponses.flatMap((response) => response.warnings)
  const signalSessions = signalResponses.flatMap((response) => response.sessions)
  const requestWarnings = [
    ...signalWarnings.filter((warning) => !activitySignalWarning(warning)).map((warning) => warningMessage(warning)),
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
  for (const session of signalSessions) {
    const key = sessionRefId(session.sessionRef)
    const sessionRecord = sessionByRef(session.sessionRef, sessions)
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
      const values = numericValues(signal.values)
      cached.signals[role] = normalizeDisplacementSignalValues(role, signal, values, sessionRecord)
    }
    fetchedSessions.set(key, cached)
  }

  const eventRowsBySession = rowsGroupedBySession(events.rows)
  const metricRowsBySession = rowsGroupedBySession(metrics.rows)
  for (const [key, cached] of fetchedSessions.entries()) {
    cached.events = eventRowsBySession.get(key) ?? []
    cached.metrics = metricRowsBySession.get(key) ?? []
    cached.warnings = uniqueStrings(cached.warnings)
  }

  return fetchedSessions
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

function visualizationSettingsKey(studySet: StudySet, mode: SuspensionVisualizationMode) {
  const prefix = mode === 'phase' ? 'phase' : 'simple'
  if (studySet.id) {
    return `${prefix}:study-set:${studySet.id}`
  }
  if (studySet.provenance.startsWith('Temporary one-session Study Set')) {
    return `${prefix}:temporary:${stableStudySetKey(studySet)}`
  }
  const name = studySet.displayName.trim() || 'untitled'
  const provenance = studySet.provenance.trim() || 'interactive'
  return `${prefix}:unsaved:${name}:${provenance}`
}

function restoredVisualizationSettings(
  cacheKey: string,
  entities: VisualizationEntity[],
  tracks: TrackRecord[],
  mode: SuspensionVisualizationMode,
): SuspensionVisualizationSettings {
  const cached = restoredVisualizationSettingsRecord(cacheKey)
  const defaultSelectedEntityIds = entities.filter((entity) => entity.kind === 'session').map((entity) => entity.id)
  const selectedEntityIds = cached
    ? normalizedSelectedEntityIds(
        stringArrayValue(cached.selectedEntityIds),
        stringArrayValue(cached.knownSessionEntityIds),
        defaultSelectedEntityIds,
        entities,
      )
    : defaultSelectedEntityIds
  const validTrackIds = new Set(tracks.map((track) => track.id))
  const selectedTrackId = cached?.selectedTrackId && validTrackIds.has(cached.selectedTrackId)
    ? cached.selectedTrackId
    : tracks[0]?.id ?? null
  return {
    selectedEntityIds,
    knownSessionEntityIds: defaultSelectedEntityIds,
    collapsedPanels: cached?.collapsedPanels ? stringArrayValue(cached.collapsedPanels) : ['select-filter'],
    comparisonLayout: cached?.comparisonLayout ?? 'entities',
    scopeMode: cached?.scopeMode ?? 'whole_session',
    selectedTrackId,
    selectedEnds: normalizedSelectedEnds(cached?.selectedEnds),
    selectedSectorIds: cached?.selectedSectorIds ? stringArrayValue(cached.selectedSectorIds) : [],
    timeWindowsBySession: cached?.timeWindowsBySession ? { ...cached.timeWindowsBySession } : {},
    excludeInactivePeriods: cached?.excludeInactivePeriods ?? true,
    signalChoices: cached?.signalChoices ? { ...cached.signalChoices } : {},
    frequencyDisplayModes: normalizedFrequencyDisplayModes(cached?.frequencyDisplayModes),
    showDisplacementMm: cached?.showDisplacementMm ?? mode === 'phase',
    showDisplacementStatsOnChart: cached?.showDisplacementStatsOnChart ?? true,
    showVelocityStatsOnChart: cached?.showVelocityStatsOnChart ?? true,
    showStrokeLengthStatsOnChart: cached?.showStrokeLengthStatsOnChart ?? true,
    phaseDensityBins: cached?.phaseDensityBins === 48 || cached?.phaseDensityBins === 96 ? cached.phaseDensityBins : 72,
    phaseContourMasses: normalizedPhaseContourMasses(cached?.phaseContourMasses),
    phaseConditionalBins: typeof cached?.phaseConditionalBins === 'number' && Number.isInteger(cached.phaseConditionalBins) && cached.phaseConditionalBins >= 20 && cached.phaseConditionalBins <= 120
      ? cached.phaseConditionalBins
      : PHASE_DEFAULT_CONDITIONAL_DISTRIBUTION_BINS,
    phaseRenderMode: cached?.phaseRenderMode === 'line' || cached?.phaseRenderMode === 'scatter' ? cached.phaseRenderMode : 'density',
    phaseMarkOpacity: typeof cached?.phaseMarkOpacity === 'number' && cached.phaseMarkOpacity >= 0.02 && cached.phaseMarkOpacity <= 0.8 ? cached.phaseMarkOpacity : 0.08,
    phaseScatterMarkSize: typeof cached?.phaseScatterMarkSize === 'number' && cached.phaseScatterMarkSize >= 1 && cached.phaseScatterMarkSize <= 5 ? cached.phaseScatterMarkSize : 1,
    phaseShowGridlines: cached?.phaseShowGridlines ?? false,
    phaseXAxisAuto: cached?.phaseXAxisAuto ?? true,
    phaseYAxisAuto: cached?.phaseYAxisAuto ?? true,
    phaseXAxisRange: phaseAxisRangeValue(cached?.phaseXAxisRange, PHASE_DISPLACEMENT_MM_BOUNDS),
    phaseYAxisRange: phaseAxisRangeValue(cached?.phaseYAxisRange, PHASE_VELOCITY_BOUNDS),
    phasePositionConditionMm: phaseAxisRangeValue(cached?.phasePositionConditionMm, PHASE_DISPLACEMENT_MM_BOUNDS),
    phasePositionConditionNormalized: phaseAxisRangeValue(cached?.phasePositionConditionNormalized, PHASE_DISPLACEMENT_NORMALIZED_BOUNDS),
    phaseVelocityCondition: phaseAxisRangeValue(cached?.phaseVelocityCondition, PHASE_VELOCITY_BOUNDS),
  }
}

function normalizedPhaseContourMasses(value: unknown) {
  if (!Array.isArray(value)) {
    return [...PHASE_DEFAULT_CONTOUR_MASSES]
  }
  return PHASE_CONTOUR_MASS_OPTIONS.filter((mass) => value.includes(mass))
}

type PhasePoint = { timeS: number; x: number; y: number; breakBefore?: boolean }
type PhaseSeries = { id: string; label: string; color: string; points: PhasePoint[] }
type PhaseContourPath = { mass: number; d: string }

const phasePointsCache = new WeakMap<VisualizationData, Map<string, PhasePoint[]>>()
const phaseContourPathCache = new WeakMap<PhasePoint[], Map<string, PhaseContourPath[]>>()
const phaseDensityCellCache = new WeakMap<PhasePoint[], Map<string, PhaseDensityCell[]>>()

function restoredVisualizationSettingsRecord(cacheKey: string): Partial<SuspensionVisualizationSettings> | null {
  const cached = visualizationSettingsCache.get(cacheKey)
  if (cached) {
    return cached
  }
  if (typeof window === 'undefined') {
    return null
  }
  try {
    const raw = window.localStorage.getItem(`${VISUALIZATION_SETTINGS_STORAGE_PREFIX}${cacheKey}`)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') {
      return null
    }
    return parsed as Partial<SuspensionVisualizationSettings>
  } catch {
    return null
  }
}

function persistVisualizationSettings(cacheKey: string, settings: SuspensionVisualizationSettings) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(`${VISUALIZATION_SETTINGS_STORAGE_PREFIX}${cacheKey}`, JSON.stringify(settings))
  } catch {
    // Analysis settings are a convenience cache; storage failures should not block charting.
  }
}

function stringArrayValue(value: unknown) {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
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
  return orderedSuspensionEnds(ends.length > 0 ? ends : ['front', 'rear'])
}

function orderedSuspensionEnds(ends: SuspensionEnd[]) {
  return (['front', 'rear'] as const).filter((end) => ends.includes(end))
}

function normalizedFrequencyDisplayModes(value: unknown): FrequencyDisplayModes {
  if (!value || typeof value !== 'object') {
    return DEFAULT_FREQUENCY_DISPLAY_MODES
  }
  const modes = value as Partial<Record<keyof FrequencyDisplayModes, unknown>>
  return {
    displacement: normalizedFrequencyDisplayMode(modes.displacement),
    velocity: normalizedFrequencyDisplayMode(modes.velocity),
    strokeLength: normalizedFrequencyDisplayMode(modes.strokeLength),
  }
}

function normalizedFrequencyDisplayMode(value: unknown): FrequencyDisplayMode {
  return value === 'cumulative' ? 'cumulative' : 'histogram'
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
      appendRows(filteredRows, sessionRows)
      continue
    }
    appendRows(filteredRows, tableRowsInTimeWindow(sessionRows, data, timeWindows[sessionKey]))
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

function isPeriodBookmark(bookmark: SessionBookmarkRecord) {
  return (
    Number.isFinite(bookmark.window.startS) &&
    Number.isFinite(bookmark.window.endS) &&
    bookmark.window.endS > bookmark.window.startS
  )
}

function compareBookmarksByStart(left: SessionBookmarkRecord, right: SessionBookmarkRecord) {
  return left.window.startS - right.window.startS || left.title.localeCompare(right.title)
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

function appendNumbers(target: number[], source: readonly number[]) {
  for (const value of source) {
    target.push(value)
  }
}

function appendRows(target: TableQueryRow[], source: readonly TableQueryRow[]) {
  for (const row of source) {
    target.push(row)
  }
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
    appendNumbers(values, sessionValues)
  }
  const nextCache = cached ?? new Map<string, number[]>()
  nextCache.set(key, values)
  if (!cached) {
    entitySignalValuesCache.set(data, nextCache)
  }
  return values
}

function phasePointsForEntityEnd(
  entity: VisualizationEntity,
  data: VisualizationData,
  displacementRole: string,
  velocityRole: string,
  track: TrackRecord | null,
  sectors: TrackSector[] | null,
  displacementScale = 1,
) {
  const cacheKey = [
    entity.id,
    entity.sessionRefs.map(sessionRefId).join(','),
    displacementRole,
    velocityRole,
    track ? `${track.id}:${track.revision}` : 'all-track',
    sectors?.map((sector) => sector.id).join(',') ?? 'all-sectors',
    displacementScale,
  ].join('|')
  const cachedForData = phasePointsCache.get(data)
  const cached = cachedForData?.get(cacheKey)
  if (cached) {
    return cached
  }
  const points: PhasePoint[] = []
  const intervalsBySession = track && sectors ? sectorIntervalsForEntity(entity, track, sectors) : null
  for (const sessionRef of entity.sessionRefs) {
    const key = sessionRefId(sessionRef)
    const times = data.timeBySession[key] ?? []
    const signals = data.signalsBySession[key] ?? {}
    const displacement = signals[displacementRole] ?? []
    const velocity = signals[velocityRole] ?? []
    const intervals = intervalsBySession?.get(key) ?? null
    const limit = Math.min(times.length, displacement.length, velocity.length)
    let previousIncludedIndex: number | null = null
    let previousVelocity: number | null = null
    for (let index = 0; index < limit; index += 1) {
      const x = displacement[index]
      const y = velocity[index]
      if (!Number.isFinite(times[index]) || !Number.isFinite(x) || !Number.isFinite(y) || (intervals && !timeInSectorIntervals(times[index], intervals))) {
        continue
      }
      const startsCompressionCycle = previousVelocity !== null && previousVelocity <= 0 && y > 0
      points.push({
        timeS: times[index],
        x: x * displacementScale,
        y,
        breakBefore: previousIncludedIndex === null || index !== previousIncludedIndex + 1 || startsCompressionCycle,
      })
      previousIncludedIndex = index
      previousVelocity = y
    }
  }
  const nextCache = cachedForData ?? new Map<string, PhasePoint[]>()
  nextCache.set(cacheKey, points)
  if (!cachedForData) {
    phasePointsCache.set(data, nextCache)
  }
  return points
}

function timeInSectorIntervals(timeS: number, intervals: Array<SectorInterval & { endInclusive: boolean }>) {
  return intervals.some((interval) => timeS >= interval.startS && (interval.endInclusive ? timeS <= interval.endS : timeS < interval.endS))
}

function phaseDomain(series: PhaseSeries[]) {
  const points = series.flatMap((item) => item.points)
  const xExtent = finiteExtent(points.map((point) => point.x))
  const yExtent = finiteExtent(points.map((point) => point.y))
  const xMax = xExtent.count > 0 ? roundPhaseAxisUpper(Math.max(1, xExtent.max * 1.04), PHASE_DISPLACEMENT_AXIS_STEP) : 100
  const yLimit = yExtent.count > 0 ? roundPhaseAxisUpper(Math.max(100, Math.abs(yExtent.min), Math.abs(yExtent.max)) * 1.08, PHASE_VELOCITY_AXIS_STEP) : 1000
  return { x: [0, xMax] as [number, number], y: [-yLimit, yLimit] as [number, number] }
}

function phaseConditionalValues(
  points: PhasePoint[],
  target: Extract<PhaseChartVariant, 'velocity_given_position' | 'position_given_velocity'>,
  positionConditionRange: PhaseAxisRange,
  velocityConditionRange: PhaseAxisRange,
) {
  const values: number[] = []
  if (target === 'velocity_given_position') {
    for (const point of points) {
      if (point.x >= positionConditionRange[0] && point.x <= positionConditionRange[1]) {
        values.push(point.y)
      }
    }
  } else {
    for (const point of points) {
      if (point.y >= velocityConditionRange[0] && point.y <= velocityConditionRange[1]) {
        values.push(point.x)
      }
    }
  }
  return values
}

function phaseConditionalChartTitle(
  target: Extract<PhaseChartVariant, 'velocity_given_position' | 'position_given_velocity'>,
  positionConditionRange: PhaseAxisRange,
  velocityConditionRange: PhaseAxisRange,
  xLabel: string,
) {
  if (target === 'velocity_given_position') {
    const unit = xLabel.includes('(mm)') ? 'mm' : '%'
    return `Velocity conditional on position from ${formatPhaseAxisRangeValue(positionConditionRange[0])} to ${formatPhaseAxisRangeValue(positionConditionRange[1])} ${unit}`
  }
  return `Position conditional on velocity from ${formatPhaseAxisRangeValue(velocityConditionRange[0])} to ${formatPhaseAxisRangeValue(velocityConditionRange[1])} mm/s`
}

function phaseConditionalDataDomain(
  series: PhaseConditionalSeries[] | null,
  target: PhaseChartVariant,
): PhaseAxisRange | null {
  if (!series || (target !== 'velocity_given_position' && target !== 'position_given_velocity')) {
    return null
  }
  const values: number[] = []
  for (const item of series) {
    for (const value of item.values) {
      if (Number.isFinite(value)) {
        values.push(value)
      }
    }
  }
  if (values.length === 0) {
    return [0, 1]
  }
  values.sort((left, right) => left - right)
  const minimum = values.length >= 1000
    ? d3.quantileSorted(values, PHASE_CONDITIONAL_LOWER_QUANTILE) ?? values[0]
    : values[0]
  const maximum = values.length >= 1000
    ? d3.quantileSorted(values, PHASE_CONDITIONAL_UPPER_QUANTILE) ?? values[values.length - 1]
    : values[values.length - 1]
  const minimumPadding = target === 'velocity_given_position' ? 10 : 0.1
  const padding = Math.max((maximum - minimum) * 0.02, minimumPadding)
  return [minimum - padding, maximum + padding]
}

function equalWidthConditionalHistogram(values: number[], xDomain: PhaseAxisRange, bins: number): ConditionalHistogram {
  const [minimum, maximum] = xDomain
  const span = maximum - minimum
  const counts = new Uint32Array(bins)
  let underflowCount = 0
  let overflowCount = 0
  let total = 0
  if (span <= 0 || bins <= 0) {
    return { bins: [], underflowCount, overflowCount, total }
  }
  for (const value of values) {
    if (!Number.isFinite(value)) {
      continue
    }
    total += 1
    if (value < minimum) {
      underflowCount += 1
      continue
    }
    if (value > maximum) {
      overflowCount += 1
      continue
    }
    const index = Math.min(bins - 1, Math.floor(((value - minimum) / span) * bins))
    counts[index] += 1
  }
  const histogram = Array.from(counts, (count, index) => ({
    x0: minimum + (index / bins) * span,
    x1: minimum + ((index + 1) / bins) * span,
    count,
    total,
    proportion: total > 0 ? count / total : 0,
  }))
  return { bins: histogram, underflowCount, overflowCount, total }
}

function formatConditionalTailCount(count: number, total: number) {
  return `${count.toLocaleString()} (${formatProportion(total > 0 ? count / total : 0)})`
}

function phaseJointHistogram(points: PhasePoint[], xDomain: PhaseAxisRange, yDomain: PhaseAxisRange, bins: number) {
  const counts = Array.from({ length: bins * bins }, () => 0)
  const xSpan = xDomain[1] - xDomain[0]
  const ySpan = yDomain[1] - yDomain[0]
  if (xSpan <= 0 || ySpan <= 0) {
    return { counts, total: 0 }
  }
  let total = 0
  for (const point of points) {
    if (point.x < xDomain[0] || point.x > xDomain[1] || point.y < yDomain[0] || point.y > yDomain[1]) {
      continue
    }
    const xIndex = Math.min(bins - 1, Math.floor(((point.x - xDomain[0]) / xSpan) * bins))
    const yIndex = Math.min(bins - 1, Math.floor(((point.y - yDomain[0]) / ySpan) * bins))
    const displayRow = bins - 1 - yIndex
    counts[displayRow * bins + xIndex] += 1
    total += 1
  }
  return { counts, total }
}

function phaseProbabilityContourPaths(points: PhasePoint[], xDomain: PhaseAxisRange, yDomain: PhaseAxisRange, bins: number, contourMasses: number[]) {
  const cacheKey = `${xDomain[0]}:${xDomain[1]}:${yDomain[0]}:${yDomain[1]}:${bins}:${contourMasses.join(',')}`
  const cachedForPoints = phaseContourPathCache.get(points)
  const cached = cachedForPoints?.get(cacheKey)
  if (cached) {
    return cached
  }
  const histogram = phaseJointHistogram(points, xDomain, yDomain, bins)
  const path = d3.geoPath()
  const contours = [...contourMasses].reverse().flatMap((mass) => {
    const threshold = probabilityMassThreshold(histogram.counts, mass)
    if (threshold === null) {
      return []
    }
    const contour = d3.contours()
      .size([bins, bins])
      .smooth(true)
      .thresholds([Math.max(Number.EPSILON, threshold - 1e-6)])(histogram.counts)[0]
    const d = contour ? path(contour) : null
    return d ? [{ mass, d }] : []
  })
  const nextCache = cachedForPoints ?? new Map<string, PhaseContourPath[]>()
  nextCache.set(cacheKey, contours)
  if (!cachedForPoints) {
    phaseContourPathCache.set(points, nextCache)
  }
  return contours
}

function probabilityMassThreshold(counts: number[], mass: number) {
  const positive = counts.filter((count) => count > 0).sort((left, right) => right - left)
  const total = d3.sum(positive)
  if (total <= 0) {
    return null
  }
  const target = total * mass
  let cumulative = 0
  for (const count of positive) {
    cumulative += count
    if (cumulative >= target) {
      return count
    }
  }
  return positive[positive.length - 1] ?? null
}

function phaseContourDasharray(mass: number) {
  if (mass <= 0.5) {
    return undefined
  }
  if (mass <= 0.8) {
    return '6 3'
  }
  if (mass <= 0.95) {
    return '2 3'
  }
  return mass <= 0.99 ? '8 3 2 3' : '1 2'
}

function phaseContourStrokeWidth(mass: number) {
  return mass <= 0.5 ? 2.2 : mass <= 0.8 ? 1.8 : mass <= 0.95 ? 1.4 : 1.15
}

function phaseContourStrokeOpacity(mass: number) {
  return mass <= 0.5 ? 0.95 : mass <= 0.8 ? 0.8 : 0.68
}

function formatContourMass(mass: number) {
  const percentage = mass * 100
  return `${Number.isInteger(percentage) ? percentage.toFixed(0) : percentage.toFixed(1)}%`
}

function roundPhaseAxisUpper(value: number, step: number) {
  return Math.ceil(value / step) * step
}

function clampPhaseAxisRange(range: PhaseAxisRange, bounds: PhaseAxisRange): PhaseAxisRange {
  const [minimumBound, maximumBound] = bounds
  const minimum = Math.max(minimumBound, Math.min(maximumBound - 1, range[0]))
  const maximum = Math.max(minimum + 1, Math.min(maximumBound, range[1]))
  return [minimum, maximum]
}

function phaseAxisRangesEqual(left: PhaseAxisRange, right: PhaseAxisRange) {
  return left[0] === right[0] && left[1] === right[1]
}

function phaseAxisRangeValue(value: unknown, bounds: readonly [number, number]): PhaseAxisRange {
  if (Array.isArray(value) && value.length === 2 && value.every((item) => typeof item === 'number' && Number.isFinite(item))) {
    return clampPhaseAxisRange([value[0], value[1]], [bounds[0], bounds[1]])
  }
  return [bounds[0], bounds[1]]
}

function formatPhaseAxisRangeValue(value: number) {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}

type PhaseDensityCell = { xIndex: number; yIndex: number; x0: number; x1: number; y0: number; y1: number; count: number; maxCount: number }

function phaseDensityCells(points: PhasePoint[], xDomain: [number, number], yDomain: [number, number], bins: number): PhaseDensityCell[] {
  const cacheKey = `${xDomain[0]}:${xDomain[1]}:${yDomain[0]}:${yDomain[1]}:${bins}`
  const cachedForPoints = phaseDensityCellCache.get(points)
  const cached = cachedForPoints?.get(cacheKey)
  if (cached) {
    return cached
  }
  const counts = new Map<number, number>()
  const xSpan = xDomain[1] - xDomain[0]
  const ySpan = yDomain[1] - yDomain[0]
  if (xSpan <= 0 || ySpan <= 0) {
    return []
  }
  for (const point of points) {
    const xIndex = Math.floor(((point.x - xDomain[0]) / xSpan) * bins)
    const yIndex = Math.floor(((point.y - yDomain[0]) / ySpan) * bins)
    if (xIndex < 0 || xIndex >= bins || yIndex < 0 || yIndex >= bins) {
      continue
    }
    const key = yIndex * bins + xIndex
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  const maxCount = Math.max(1, ...counts.values())
  const cells = Array.from(counts.entries()).map(([key, count]) => {
    const xIndex = key % bins
    const yIndex = Math.floor(key / bins)
    return {
      xIndex,
      yIndex,
      x0: xDomain[0] + (xIndex / bins) * xSpan,
      x1: xDomain[0] + ((xIndex + 1) / bins) * xSpan,
      y0: yDomain[0] + (yIndex / bins) * ySpan,
      y1: yDomain[0] + ((yIndex + 1) / bins) * ySpan,
      count,
      maxCount,
    }
  })
  const nextCache = cachedForPoints ?? new Map<string, PhaseDensityCell[]>()
  nextCache.set(cacheKey, cells)
  if (!cachedForPoints) {
    phaseDensityCellCache.set(points, nextCache)
  }
  return cells
}

function densityOpacity(count: number, maxCount: number, logarithmic: boolean) {
  const normalized = logarithmic ? Math.log1p(count) / Math.log1p(maxCount) : count / maxCount
  return 0.12 + normalized * 0.68
}

function samplePhasePoints(points: PhasePoint[], maxPoints: number) {
  if (points.length <= maxPoints) {
    return points
  }
  const bucketCount = Math.max(1, Math.floor(maxPoints / 6))
  const selectedIndexes = new Set<number>([0, points.length - 1])
  for (let bucket = 0; bucket < bucketCount; bucket += 1) {
    const start = Math.floor((bucket * points.length) / bucketCount)
    const end = Math.max(start, Math.floor(((bucket + 1) * points.length) / bucketCount) - 1)
    let minX = start
    let maxX = start
    let minY = start
    let maxY = start
    for (let index = start + 1; index <= end; index += 1) {
      if (points[index].x < points[minX].x) minX = index
      if (points[index].x > points[maxX].x) maxX = index
      if (points[index].y < points[minY].y) minY = index
      if (points[index].y > points[maxY].y) maxY = index
    }
    selectedIndexes.add(start)
    selectedIndexes.add(end)
    selectedIndexes.add(minX)
    selectedIndexes.add(maxX)
    selectedIndexes.add(minY)
    selectedIndexes.add(maxY)
  }
  const indexes = Array.from(selectedIndexes).sort((left, right) => left - right)
  const breakCounts = new Uint32Array(points.length)
  for (let index = 0; index < points.length; index += 1) {
    breakCounts[index] = (index > 0 ? breakCounts[index - 1] : 0) + (points[index].breakBefore ? 1 : 0)
  }
  return indexes.map((index, outputIndex) => {
    const previousIndex = indexes[outputIndex - 1] ?? -1
    const hasBreak = outputIndex === 0 || breakCounts[index] > (previousIndex >= 0 ? breakCounts[previousIndex] : 0)
    return { ...points[index], breakBefore: hasBreak }
  })
}

function canvasPhasePoints(points: PhasePoint[], renderMode: Exclude<PhaseRenderMode, 'density'>) {
  if (points.length <= PHASE_CANVAS_RAW_POINT_LIMIT) {
    return points
  }
  return renderMode === 'line'
    ? samplePhaseLinePoints(points, PHASE_LINE_TARGET_HZ, PHASE_LINE_MAX_POINTS)
    : samplePhasePoints(points, PHASE_SCATTER_MAX_POINTS)
}

function samplePhaseLinePoints(points: PhasePoint[], targetHz: number, maxPoints: number) {
  if (points.length <= maxPoints && phaseSampleRateHz(points) <= targetHz) {
    return points
  }
  const targetIntervalS = 1 / targetHz
  const backbone = new Set<number>([0, points.length - 1])
  let nextTargetTimeS = points[0]?.timeS ?? 0
  for (let index = 0; index < points.length; index += 1) {
    const point = points[index]
    if (point.breakBefore) {
      backbone.add(index)
      nextTargetTimeS = point.timeS + targetIntervalS
    } else if (point.timeS >= nextTargetTimeS) {
      backbone.add(index)
      while (nextTargetTimeS <= point.timeS) {
        nextTargetTimeS += targetIntervalS
      }
    }
  }
  const backboneIndexes = Array.from(backbone).sort((left, right) => left - right)
  const remainingBudget = Math.max(0, maxPoints - backboneIndexes.length)
  if (remainingBudget === 0) {
    return sampledPhasePointsAtIndexes(points, backboneIndexes)
  }

  const extrema = new Set<number>()
  for (let item = 0; item < backboneIndexes.length - 1; item += 1) {
    const start = backboneIndexes[item]
    const end = backboneIndexes[item + 1]
    let minX = start
    let maxX = start
    let minY = start
    let maxY = start
    for (let index = start + 1; index <= end; index += 1) {
      if (points[index].x < points[minX].x) minX = index
      if (points[index].x > points[maxX].x) maxX = index
      if (points[index].y < points[minY].y) minY = index
      if (points[index].y > points[maxY].y) maxY = index
    }
    extrema.add(minX)
    extrema.add(maxX)
    extrema.add(minY)
    extrema.add(maxY)
  }
  const extremaIndexes = Array.from(extrema).filter((index) => !backbone.has(index)).sort((left, right) => left - right)
  const retainedExtrema = extremaIndexes.length <= remainingBudget
    ? extremaIndexes
    : extremaIndexes.filter((_, index) => index % Math.ceil(extremaIndexes.length / remainingBudget) === 0).slice(0, remainingBudget)
  return sampledPhasePointsAtIndexes(points, [...backboneIndexes, ...retainedExtrema].sort((left, right) => left - right))
}

function phaseSampleRateHz(points: PhasePoint[]) {
  const gaps = points.slice(1).map((point, index) => point.timeS - points[index].timeS).filter((gap) => Number.isFinite(gap) && gap > 0)
  const medianGapS = d3.median(gaps)
  return medianGapS && medianGapS > 0 ? 1 / medianGapS : Number.POSITIVE_INFINITY
}

function sampledPhasePointsAtIndexes(points: PhasePoint[], indexes: number[]) {
  const breakCounts = new Uint32Array(points.length)
  for (let index = 0; index < points.length; index += 1) {
    breakCounts[index] = (index > 0 ? breakCounts[index - 1] : 0) + (points[index].breakBefore ? 1 : 0)
  }
  return indexes.map((index, outputIndex) => {
    const previousIndex = indexes[outputIndex - 1] ?? -1
    const hasBreak = outputIndex === 0 || breakCounts[index] > (previousIndex >= 0 ? breakCounts[previousIndex] : 0)
    return { ...points[index], breakBefore: hasBreak }
  })
}

function formatPhaseTick(value: number) {
  const absolute = Math.abs(value)
  if (absolute >= 1000) {
    return `${(value / 1000).toFixed(absolute >= 10000 ? 0 : 1)}k`
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
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
  const out: TableQueryRow[] = entity.sessionRefs.length === 1 ? grouped.get(sessionRefId(entity.sessionRefs[0])) ?? [] : []
  if (entity.sessionRefs.length > 1) {
    for (const sessionRef of entity.sessionRefs) {
      appendRows(out, grouped.get(sessionRefId(sessionRef)) ?? [])
    }
  }
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

function identityValues(values: number[]) {
  return values
}

function normalizeDisplacementSignalValues(
  role: string,
  signal: SignalQuerySignal,
  values: number[],
  session: SessionRecord | undefined,
) {
  if (!NORMALIZED_DISPLACEMENT_SIGNAL_ROLES.has(role)) {
    return values
  }
  const quantity = normalizeSignalText(signal.quantity)
  const unit = normalizeSignalText(signal.unit)
  if (quantity === 'disp_norm' && unit === '1') {
    return values
  }
  if (quantity !== 'disp' || !isMillimetreUnit(unit)) {
    return values
  }
  const fullRange = displacementFullRangeForSignal(signal, values, session)
  if (fullRange === null || fullRange <= 0) {
    return values
  }
  return values.map((value) => (Number.isFinite(value) ? value / fullRange : Number.NaN))
}

function displacementFullRangeForSignal(
  signal: SignalQuerySignal,
  values: number[],
  session: SessionRecord | undefined,
) {
  const ownRange = fullRangeFromDerivation(signal.derivation)
  if (ownRange !== null) {
    return ownRange
  }
  const candidates = (session?.availableSignals ?? [])
    .filter((candidate) => displacementNormalizationCandidateMatches(candidate, signal))
    .sort((left, right) => displacementNormalizationCandidateScore(left, signal) - displacementNormalizationCandidateScore(right, signal))
  for (const candidate of candidates) {
    const range = fullRangeFromDerivation(candidate.derivation)
    if (range !== null) {
      return range
    }
  }
  return observedPositiveMax(values)
}

function displacementNormalizationCandidateMatches(candidate: SessionSignalSummary, signal: SignalQuerySignal) {
  return (
    normalizeSignalText(candidate.end) === normalizeSignalText(signal.end) &&
    normalizeSignalText(candidate.domain) === normalizeSignalText(signal.domain) &&
    normalizeSignalText(candidate.quantity) === 'disp_norm' &&
    normalizeSignalText(candidate.unit) === '1'
  )
}

function displacementNormalizationCandidateScore(candidate: SessionSignalSummary, signal: SignalQuerySignal) {
  const sameMotionSource =
    normalizeSignalText(candidate.motionSourceId) &&
    normalizeSignalText(candidate.motionSourceId) === normalizeSignalText(signal.motionSourceId)
  const motionScore = sameMotionSource ? 0 : 20
  const roleScore = normalizeSignalText(candidate.processingRole) === 'primary_analysis' ? 0 : 2
  const rangeScore = fullRangeFromDerivation(candidate.derivation) !== null ? 0 : 4
  return motionScore + roleScore + rangeScore
}

function fullRangeFromDerivation(derivation: Record<string, unknown> | undefined) {
  const value = firstNumericField(derivation?.full_range, derivation?.fullRange, derivation?.full_range_mm, derivation?.fullRangeMm)
  return value !== null && Number.isFinite(value) && value > 0 ? value : null
}

function observedPositiveMax(values: number[]) {
  const extent = finiteExtent(values)
  if (extent.count === 0) {
    return null
  }
  if (extent.max > 0) {
    return extent.max
  }
  const absoluteMin = Math.abs(extent.min)
  return absoluteMin > 0 ? absoluteMin : null
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

function displacementMmCandidateDomain(
  entities: VisualizationEntity[],
  data: VisualizationData,
  ends: SuspensionEnd[],
  candidates: number[],
): [number, number] {
  const roles = distributionRoles('front_displacement_mm', 'rear_displacement_mm', ends)
  const values = entities.flatMap((entity) =>
    roles.flatMap((role) => entitySignalValues(entity, data, role.signalRole)),
  )
  return candidateDomainContainingMax(values, candidates)
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

function candidateDomainContainingMax(values: number[], candidates: number[]): [number, number] {
  const limits = [...candidates].filter((value) => Number.isFinite(value) && value > 0).sort((a, b) => a - b)
  const fallback = limits[0] ?? 1
  const clean = values.filter((value) => Number.isFinite(value) && value >= 0)
  if (clean.length === 0) {
    return [0, fallback]
  }
  const max = d3.max(clean) ?? 0
  const candidate = limits.find((limit) => max <= limit)
  if (candidate !== undefined) {
    return [0, candidate]
  }
  return [0, Math.max(fallback, Math.ceil(max / 50) * 50)]
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
  const aliasesByPair = new Map(
    (track.segmentAliases ?? []).map((alias) => [`${alias.fromTrackpointId}:${alias.toTrackpointId}`, alias]),
  )
  const sectors: TrackSector[] = []
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index]
    const end = points[index + 1]
    const alias = aliasesByPair.get(`${start.id}:${end.id}`)
    if (alias?.timingRole === 'untimed') {
      continue
    }
    sectors.push({
      id: `${start.id}:${end.id}`,
      label: alias?.name.trim() || `${start.name} to ${end.name}`,
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
    appendNumbers(values, sectorValuesForSession(sessionRef, data, track, sector, role))
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
    appendNumbers(values, sectorValuesForEntity(entity, data, track, sector, role))
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
    q25,
    median,
    q75,
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
