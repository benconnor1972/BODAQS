import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Columns3,
  FileText,
  FolderOpen,
  GitBranch,
  Library,
  Minus,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import './App.css'
import { IconButton, InfoTip, PanelTitle } from './components/Common'
import { FilterPanel } from './components/FilterPanel'
import { FilterManagerModal } from './components/FilterManagerModal'
import { GeospatialWorkbench, MatchPreviewCard, StudySetGpsCoverageCard } from './components/GeospatialWorkbench'
import { GpsRoutePreview } from './components/GpsRoutePreview'
import { MapRoutePreview } from './components/MapRoutePreview'
import { Modal } from './components/Modal'
import { SessionNoteEditorModal } from './components/SessionNoteEditorModal'
import { SessionTable, type SessionSelectionGesture } from './components/SessionTable'
import { StudySessionTable } from './components/StudySessionTable'
import { SuspensionVisualization } from './components/SuspensionVisualization'
import { UnsavedChangesDialog } from './components/UnsavedChangesDialog'
import { FixtureLibraryDataSource } from './data/FixtureLibraryDataSource'
import { LocalApiDataSource } from './data/LocalApiDataSource'
import type { LibraryDataSource } from './data/LibraryDataSource'
import { invalidateSuspensionCacheForSession } from './data/SuspensionAnalysisCache'
import {
  broadcastSessionDeleted,
  broadcastStudySetDeleted,
  broadcastStudySetUpdated,
  subscribeWorkbenchSync,
} from './data/WorkbenchSync'
import {
  columnGroups,
  columnLabels,
  columnPresets,
  defaultColumns,
  infoActionColumns,
  lockedColumns,
  matchesSearch,
  normalizeColumnSelection,
  sortSessions,
} from './domain/sessionCatalog'
import {
  applySavedSessionFilters,
  prototypeSavedSessionFilters,
  trackpointCrossingSpecsForFilters,
  type SavedSessionFilterRecord,
  type TrackpointCrossingSpec,
} from './domain/sessionFilters'
import {
  candidateId,
  cloneStudySet,
  emptyStudySet,
  groupingColors,
  hasStudySetContent,
  isTemporaryStudySet,
  sessionRefId,
  sessionByRef,
  sessionToStudyRef,
  slugify,
  studySetsEqual,
  uniqueId,
} from './domain/studySets'
import { applyTableColumnFilters, type TableColumnFilter } from './domain/tableFilters'
import type {
  ColumnId,
  LibraryRecord,
  ModalState,
  SessionInspectionTab,
  SessionTrackMatchRecord,
  SessionRecord,
  SortDirection,
  StudyGrouping,
  StudySet,
  TrackpointMatchQueryRecord,
  TrackpointMatchQueryResults,
  TrackRecord,
} from './domain/types'

type PendingStudySetAction =
  | { kind: 'load'; studySet: StudySet }
  | { kind: 'analyze-now'; session: SessionRecord }
  | { kind: 'clear' }

type GeoFilterQueryState = {
  key: string
  label: string
  status: 'queued' | 'running' | 'completed' | 'cancelled' | 'failed'
  candidateSessionCount: number
  processedSessionCount: number
  matchedSessionCount: number
  matchedSessionIds: string[]
  error: string
}

type StudySetMapSessionPath = {
  id: string
  label: string
  path: Array<[number, number]>
}

const LEGACY_SESSION_SELECTOR_COLUMNS_STORAGE_KEY = 'bodaqs.web.session-selector.columns.v1'
const SESSION_SELECTOR_COLUMNS_STORAGE_KEY = 'bodaqs.web.session-selector.columns.v2'
const ANALYSIS_SCOPE_STORAGE_PREFIX = 'bodaqs.web.analysis-scope.v1.'

type AnalysisRouteState = {
  viewId: string
  scopeToken: string | null
  studySetId: string | null
}

type AnalysisScopeNotice = {
  kind: 'study-set-updated' | 'study-set-deleted' | 'session-deleted'
  message: string
  refreshable: boolean
}

function App() {
  const [localDataSource] = useState(() => new LocalApiDataSource())
  const [fixtureDataSource] = useState(() => new FixtureLibraryDataSource())
  const [analysisRoute, setAnalysisRoute] = useState<AnalysisRouteState | null>(() => parseAnalysisRouteHash())
  const [analysisRouteStudySet, setAnalysisRouteStudySet] = useState<StudySet | null>(null)
  const [analysisRouteStudySetLoading, setAnalysisRouteStudySetLoading] = useState(() =>
    Boolean(parseAnalysisRouteHash()?.studySetId),
  )
  const [analysisRouteStudySetError, setAnalysisRouteStudySetError] = useState('')
  const [analysisScopeNotice, setAnalysisScopeNotice] = useState<AnalysisScopeNotice | null>(null)
  const [activeDataSource, setActiveDataSource] = useState<LibraryDataSource>(localDataSource)
  const columnMenuRef = useRef<HTMLDivElement>(null)
  const [libraries, setLibraries] = useState<LibraryRecord[]>([])
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [tracks, setTracks] = useState<TrackRecord[]>([])
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState<ColumnId[]>(loadPersistedVisibleColumns)
  const [searchText, setSearchText] = useState('')
  const [sortColumn, setSortColumn] = useState<ColumnId>('started')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const [primaryCandidateId, setPrimaryCandidateId] = useState<string | null>(null)
  const [selectionAnchorCandidateId, setSelectionAnchorCandidateId] = useState<string | null>(null)
  const [selectedStudySessionIds, setSelectedStudySessionIds] = useState<string[]>([])
  const [selectionAnchorStudySessionId, setSelectionAnchorStudySessionId] = useState<string | null>(null)
  const [selectedTrackIds, setSelectedTrackIds] = useState<string[]>([])
  const [savedStudySets, setSavedStudySets] = useState<StudySet[]>([])
  const [savedSessionFilters, setSavedSessionFilters] = useState<SavedSessionFilterRecord[]>(prototypeSavedSessionFilters)
  const [currentStudySet, setCurrentStudySet] = useState<StudySet>(() => emptyStudySet())
  const [lastCommittedStudySet, setLastCommittedStudySet] = useState<StudySet>(() => emptyStudySet())
  const [studySetMapSessionPaths, setStudySetMapSessionPaths] = useState<StudySetMapSessionPath[]>([])
  const [groupingName, setGroupingName] = useState('')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [librarySelectorCollapsed, setLibrarySelectorCollapsed] = useState(true)
  const [sessionSelectorCollapsed, setSessionSelectorCollapsed] = useState(false)
  const [gpsLocationCollapsed, setGpsLocationCollapsed] = useState(false)
  const [studyGpsCollapsed, setStudyGpsCollapsed] = useState(false)
  const [filtersCollapsed, setFiltersCollapsed] = useState(false)
  const [activeSavedFilterIds, setActiveSavedFilterIds] = useState<string[]>([])
  const [geoFilterQueryStates, setGeoFilterQueryStates] = useState<Record<string, GeoFilterQueryState>>({})
  const [tableColumnFilters, setTableColumnFilters] = useState<TableColumnFilter[]>([])
  const [filterManagerOpen, setFilterManagerOpen] = useState(false)
  const [columnMenuOpen, setColumnMenuOpen] = useState(false)
  const [modal, setModal] = useState<ModalState>(null)
  const [bookmarkRefreshToken, setBookmarkRefreshToken] = useState(0)
  const [noteEditorSession, setNoteEditorSession] = useState<SessionRecord | null>(null)
  const [pendingStudySetAction, setPendingStudySetAction] = useState<PendingStudySetAction | null>(null)
  const [libraryRootInput, setLibraryRootInput] = useState('')
  const [connectionMode, setConnectionMode] = useState<'local-api' | 'fixture'>('local-api')
  const [isChangingLibraryRoot, setIsChangingLibraryRoot] = useState(false)
  const [isRefreshingWorkbenchData, setIsRefreshingWorkbenchData] = useState(false)
  const [statusMessage, setStatusMessage] = useState('Connecting to configured BODAQS Library API...')
  const workbenchRefreshInFlightRef = useRef(false)
  const lastAutomaticWorkbenchRefreshMs = useRef(0)

  useEffect(() => {
    function handleHashChange() {
      const nextRoute = parseAnalysisRouteHash()
      setAnalysisRoute(nextRoute)
      setAnalysisRouteStudySetLoading(Boolean(nextRoute?.studySetId))
      setAnalysisRouteStudySetError('')
    }

    window.addEventListener('hashchange', handleHashChange)
    return () => {
      window.removeEventListener('hashchange', handleHashChange)
    }
  }, [])

  useEffect(() => {
    document.title = browserTabTitle(analysisRoute)
  }, [analysisRoute])

  useEffect(() => {
    let cancelled = false

    async function loadDefaultData() {
      try {
        const health = await localDataSource.getHealth()
        if (cancelled) {
          return
        }
        if (health.libraries_root) {
          setLibraryRootInput(health.libraries_root)
        }
        const loaded = await fetchWorkbenchData(localDataSource)
        if (cancelled) {
          return
        }
        setLibraries(loaded.libraries)
        setSessions(loaded.sessions)
        setTracks(loaded.tracks)
        setSavedStudySets(loaded.studySets)
        setSavedSessionFilters(loaded.savedFilters)
        setSelectedLibraryIds(loaded.libraries.map((libraryItem) => libraryItem.id))
        setStatusMessage(`Connected to Library API at ${localDataSource.baseUrl}.`)
        setActiveDataSource(localDataSource)
        setConnectionMode('local-api')
      } catch (error) {
        if (cancelled) {
          return
        }
        const message = error instanceof Error ? error.message : String(error)
        setActiveDataSource(fixtureDataSource)
        setConnectionMode('fixture')
        try {
          const loaded = await fetchWorkbenchData(fixtureDataSource)
          if (cancelled) {
            return
          }
          setLibraries(loaded.libraries)
          setSessions(loaded.sessions)
          setTracks(loaded.tracks)
          setSavedStudySets(loaded.studySets)
          setSavedSessionFilters(loaded.savedFilters)
          setSelectedLibraryIds(loaded.libraries.map((libraryItem) => libraryItem.id))
          setStatusMessage(`Local API unavailable at ${localDataSource.baseUrl}; fixture prototype loaded. ${message}`)
        } catch (fixtureError) {
          if (cancelled) {
            return
          }
          const fixtureMessage = fixtureError instanceof Error ? fixtureError.message : String(fixtureError)
          setStatusMessage(`Could not load local API or prototype fixture data: ${fixtureMessage}`)
        }
      }
    }

    void loadDefaultData()
    return () => {
      cancelled = true
    }
  }, [fixtureDataSource, localDataSource])

  useEffect(() => {
    if (connectionMode !== 'local-api' || !activeDataSource.refreshLibrary || libraries.length === 0) {
      return
    }

    function refreshIfReturningToWorkbench() {
      if (document.visibilityState !== 'visible') {
        return
      }
      const now = Date.now()
      if (now - lastAutomaticWorkbenchRefreshMs.current < 15000) {
        return
      }
      lastAutomaticWorkbenchRefreshMs.current = now
      void refreshWorkbenchData({ quiet: true, automatic: true })
    }

    window.addEventListener('focus', refreshIfReturningToWorkbench)
    document.addEventListener('visibilitychange', refreshIfReturningToWorkbench)
    return () => {
      window.removeEventListener('focus', refreshIfReturningToWorkbench)
      document.removeEventListener('visibilitychange', refreshIfReturningToWorkbench)
    }
  }, [activeDataSource, connectionMode, libraries.length, refreshWorkbenchData, selectedLibraryIds, sessions.length])

  useEffect(() => {
    if (!analysisRoute?.studySetId) {
      setAnalysisRouteStudySet(null)
      setAnalysisRouteStudySetLoading(false)
      setAnalysisRouteStudySetError('')
      return
    }

    let cancelled = false
    const studySetId = analysisRoute.studySetId

    async function loadRouteStudySet() {
      const cachedStudySet = savedStudySets.find((studySet) => studySet.id === studySetId)
      if (cachedStudySet) {
        setAnalysisRouteStudySet(cloneStudySet(cachedStudySet))
        setAnalysisRouteStudySetLoading(false)
        setAnalysisRouteStudySetError('')
        return
      }

      if (!activeDataSource.loadStudySet) {
        setAnalysisRouteStudySet(null)
        setAnalysisRouteStudySetLoading(false)
        setAnalysisRouteStudySetError('This data source cannot load a Study Set directly by ID.')
        return
      }

      setAnalysisRouteStudySetLoading(true)
      setAnalysisRouteStudySetError('')
      try {
        const loaded = await activeDataSource.loadStudySet(studySetId)
        if (cancelled) {
          return
        }
        setAnalysisRouteStudySet(cloneStudySet(loaded))
      } catch (error) {
        if (cancelled) {
          return
        }
        setAnalysisRouteStudySet(null)
        setAnalysisRouteStudySetError(error instanceof Error ? error.message : 'Could not load the Study Set.')
      } finally {
        if (!cancelled) {
          setAnalysisRouteStudySetLoading(false)
        }
      }
    }

    void loadRouteStudySet()
    return () => {
      cancelled = true
    }
  }, [activeDataSource, analysisRoute?.studySetId, savedStudySets])

  useEffect(() => {
    return subscribeWorkbenchSync((message) => {
      if (message.type === 'session-deleted') {
        invalidateSuspensionCacheForSession(activeDataSource, message.sessionRefId)
      }
      if (!analysisRoute) {
        return
      }

      const routeStudySet = analysisRoute.scopeToken
        ? loadAnalysisScope(analysisRoute.scopeToken)
        : analysisRouteStudySet

      if (message.type === 'study-set-updated' && analysisRoute.studySetId === message.studySetId) {
        setAnalysisScopeNotice({
          kind: 'study-set-updated',
          message: `Study Set "${message.displayName}" was changed in another tab.`,
          refreshable: true,
        })
        return
      }

      if (message.type === 'study-set-deleted' && analysisRoute.studySetId === message.studySetId) {
        setAnalysisScopeNotice({
          kind: 'study-set-deleted',
          message: `Study Set "${message.displayName}" was deleted in another tab.`,
          refreshable: false,
        })
        return
      }

      if (message.type === 'session-deleted' && routeStudySet?.sessions.some((ref) => sessionRefId(ref) === message.sessionRefId)) {
        setAnalysisScopeNotice({
          kind: 'session-deleted',
          message: `Session "${message.sessionName}" was deleted in another tab.`,
          refreshable: Boolean(analysisRoute.studySetId),
        })
      }
    })
  }, [activeDataSource, analysisRoute, analysisRouteStudySet])

  const isCurrentStudySetDirty = !studySetsEqual(currentStudySet, lastCommittedStudySet)
  const currentStudySetHasContent = hasStudySetContent(currentStudySet)
  const currentStudySetStatus = studySetStatus(currentStudySet, isCurrentStudySetDirty)
  const canSaveCurrentStudySet =
    isCurrentStudySetDirty || (!currentStudySet.id && currentStudySet.sessions.length > 0)
  const canSavePendingAction = Boolean(currentStudySet.displayName.trim() && currentStudySet.sessions.length > 0)
  const trackMatchRequestKey = JSON.stringify({
    sessions: currentStudySet.sessions,
    trackIds: currentStudySet.trackIds,
    trackRevisions: currentStudySet.trackIds.map((trackId) => {
      const track = tracks.find((item) => item.id === trackId)
      return {
        trackId,
        revision: track?.revision ?? 0,
        trackpoints: track?.trackpoints.map((trackpoint) => [trackpoint.id, trackpoint.stationM]) ?? [],
      }
    }),
  })

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!isCurrentStudySetDirty) {
        return
      }
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [isCurrentStudySetDirty])

  useEffect(() => {
    if (!activeDataSource.listTrackMatches) {
      return
    }

    let cancelled = false
    async function loadTrackMatches() {
      try {
        const matchRequest = JSON.parse(trackMatchRequestKey) as Pick<StudySet, 'sessions' | 'trackIds'>
        const matches = await activeDataSource.listTrackMatches?.({
          id: null,
          displayName: '',
          revision: 0,
          saved: false,
          sessions: matchRequest.sessions,
          groupings: [],
          trackIds: matchRequest.trackIds,
          provenance: '',
        })
        if (cancelled || !matches) {
          return
        }
        setTracks((currentTracks) => withTrackMatches(currentTracks, matches))
      } catch (error) {
        if (cancelled) {
          return
        }
        const message = error instanceof Error ? error.message : String(error)
        setStatusMessage(`Track match preview unavailable: ${message}`)
        setTracks((currentTracks) => withTrackMatches(currentTracks, []))
      }
    }

    void loadTrackMatches()
    return () => {
      cancelled = true
    }
  }, [activeDataSource, trackMatchRequestKey])

  useEffect(() => {
    if (!columnMenuOpen) {
      return
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target
      if (!(target instanceof Node)) {
        return
      }
      if (columnMenuRef.current?.contains(target)) {
        return
      }
      setColumnMenuOpen(false)
    }

    document.addEventListener('pointerdown', handlePointerDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
    }
  }, [columnMenuOpen])

  useEffect(() => {
    persistVisibleColumns(visibleColumns)
  }, [visibleColumns])

  const selectedLibraries = libraries.filter((libraryItem) =>
    selectedLibraryIds.includes(libraryItem.id),
  )
  const libraryScopedSessions = sessions.filter((session) => selectedLibraryIds.includes(session.libraryId))
  const activeSavedSessionFilters = savedSessionFilters.filter((filter) => activeSavedFilterIds.includes(filter.id))
  const activeTrackpointFilterSpecs = trackpointCrossingSpecsForFilters(activeSavedSessionFilters, selectedLibraryIds)
  const activeTrackpointFilterSpecKey = JSON.stringify(activeTrackpointFilterSpecs)
  const pendingTrackpointFilterKeys = new Set(
    activeTrackpointFilterSpecs
      .filter((spec) => geoFilterQueryStates[spec.key]?.status !== 'completed')
      .map((spec) => spec.key),
  )
  const trackpointCrossingMatches = Object.fromEntries(
    activeTrackpointFilterSpecs
      .filter((spec) => geoFilterQueryStates[spec.key]?.status === 'completed')
      .map((spec) => [spec.key, geoFilterQueryStates[spec.key].matchedSessionIds]),
  )
  const activeGeoFilterStates = activeTrackpointFilterSpecs.map((spec) => geoFilterQueryStates[spec.key] ?? queuedGeoFilterState(spec))
  const savedFilteredSessions = applySavedSessionFilters(libraryScopedSessions, activeSavedSessionFilters, {
    libraryIds: selectedLibraryIds,
    pendingTrackpointCrossingKeys: pendingTrackpointFilterKeys,
    trackpointCrossingMatches,
  })
  const activeTableColumnFilters = tableColumnFilters.filter((filter) => filter.values.length > 0)
  const tableFilteredSessions = applyTableColumnFilters(savedFilteredSessions, activeTableColumnFilters, libraries)
  const searchedSessions = tableFilteredSessions.filter((session) =>
    matchesSearch(session, searchText, visibleColumns, libraries),
  )
  const visibleSessions = sortSessions(
    searchedSessions,
    sortColumn,
    sortDirection,
    libraries,
  )
  const primarySession = primaryCandidateId
    ? sessions.find((session) => candidateId(session) === primaryCandidateId) ?? null
    : null
  const selectedCandidateSessions = selectedCandidateIds
    .map((id) => sessions.find((session) => candidateId(session) === id))
    .filter((session): session is SessionRecord => Boolean(session))
  const selectedTracks = tracks.filter((track) => selectedTrackIds.includes(track.id))
  const currentStudyTracks = tracks.filter((track) => currentStudySet.trackIds.includes(track.id))
  const currentStudySetSessions = useMemo(
    () =>
      currentStudySet.sessions
        .map((sessionRef) => sessionByRef(sessionRef, sessions))
        .filter((session): session is SessionRecord => Boolean(session)),
    [currentStudySet.sessions, sessions],
  )
  const currentStudySetSessionKey = currentStudySet.sessions.map(sessionRefId).join('|')

  useEffect(() => {
    let cancelled = false
    const fallbackPaths = currentStudySetSessions.map((session) => studySetPathFromSession(session)).filter(hasMapPath)

    if (currentStudySetSessions.length === 0) {
      setStudySetMapSessionPaths([])
      return
    }

    if (!activeDataSource.loadSessionGpsPoints) {
      setStudySetMapSessionPaths(fallbackPaths)
      return
    }

    setStudySetMapSessionPaths(fallbackPaths)
    Promise.all(
      currentStudySetSessions.map(async (session) => {
        try {
          const preferredSourceId = session.gpsSummary.preferredSourceId ?? session.gpsSummary.sources[0]?.sourceId ?? null
          const pointSet = await activeDataSource.loadSessionGpsPoints?.(session, preferredSourceId)
          return studySetPathFromSession(session, pointSet?.path ?? [])
        } catch {
          return studySetPathFromSession(session)
        }
      }),
    ).then((paths) => {
      if (!cancelled) {
        setStudySetMapSessionPaths(paths.filter(hasMapPath))
      }
    })

    return () => {
      cancelled = true
    }
  }, [activeDataSource, currentStudySetSessionKey, currentStudySetSessions])

  useEffect(() => {
    const specs = JSON.parse(activeTrackpointFilterSpecKey) as TrackpointCrossingSpec[]
    if (specs.length === 0) {
      return
    }

    if (
      !activeDataSource.createTrackpointMatchQuery ||
      !activeDataSource.loadTrackpointMatchQuery ||
      !activeDataSource.loadTrackpointMatchQueryResults
    ) {
      const timeoutId = window.setTimeout(() => {
        setGeoFilterQueryStates((current) => {
          const next: Record<string, GeoFilterQueryState> = {}
          for (const spec of specs) {
            next[spec.key] = {
              ...(current[spec.key] ?? queuedGeoFilterState(spec)),
              status: 'failed',
              error: 'Current data source cannot run trackpoint match queries.',
            }
          }
          return next
        })
      }, 0)
      return () => window.clearTimeout(timeoutId)
    }

    let cancelled = false
    for (const spec of specs) {
      void runTrackpointFilterQuery(spec)
    }

    return () => {
      cancelled = true
    }

    async function runTrackpointFilterQuery(spec: TrackpointCrossingSpec) {
      try {
        const created = await activeDataSource.createTrackpointMatchQuery?.({
          trackId: spec.trackId,
          trackpointIds: spec.trackpointIds,
          matchMode: spec.matchMode,
          toleranceM: spec.toleranceM,
          minCount: spec.minCount,
          scope: { libraryIds: spec.libraryIds },
          persist: true,
        })
        if (!created || cancelled) {
          return
        }
        setGeoFilterQueryStates((current) => ({
          ...current,
          [spec.key]: geoFilterStateFromQuery(spec, created, current[spec.key]?.matchedSessionIds ?? []),
        }))

        let query = created
        for (let attempt = 0; attempt < 120; attempt += 1) {
          if (cancelled || query.status === 'completed' || query.status === 'failed' || query.status === 'cancelled') {
            break
          }
          await delay(500)
          const loaded = await activeDataSource.loadTrackpointMatchQuery?.(query.queryId)
          if (!loaded || cancelled) {
            return
          }
          query = loaded
          setGeoFilterQueryStates((current) => ({
            ...current,
            [spec.key]: geoFilterStateFromQuery(spec, query, current[spec.key]?.matchedSessionIds ?? []),
          }))
        }

        if (query.status !== 'completed' || cancelled) {
          return
        }

        const matchedSessionIds = await loadAllTrackpointFilterResultIds(query.queryId)
        if (cancelled) {
          return
        }
        setGeoFilterQueryStates((current) => ({
          ...current,
          [spec.key]: geoFilterStateFromQuery(spec, query, matchedSessionIds),
        }))
      } catch (error) {
        if (cancelled) {
          return
        }
        const message = error instanceof Error ? error.message : String(error)
        setGeoFilterQueryStates((current) => ({
          ...current,
          [spec.key]: {
            ...(current[spec.key] ?? queuedGeoFilterState(spec)),
            status: 'failed',
            error: message,
          },
        }))
      }
    }

    async function loadAllTrackpointFilterResultIds(queryId: string) {
      const matchedSessionIds: string[] = []
      let cursor: string | null = null
      do {
        const page: TrackpointMatchQueryResults | undefined =
          await activeDataSource.loadTrackpointMatchQueryResults?.(queryId, cursor, 500)
        if (!page) {
          break
        }
        matchedSessionIds.push(...page.results.map((result) => sessionRefId(result.sessionRef)))
        cursor = page.nextCursor
      } while (cursor && !cancelled)
      return Array.from(new Set(matchedSessionIds))
    }
  }, [activeDataSource, activeTrackpointFilterSpecKey])

  function toggleLibrary(libraryId: string) {
    setSelectedLibraryIds((current) => {
      if (current.includes(libraryId)) {
        return current.filter((id) => id !== libraryId)
      }
      return [...current, libraryId]
    })
  }

  async function applyLibraryRoot() {
    const librariesRoot = libraryRootInput.trim()
    if (!librariesRoot) {
      setStatusMessage('Enter a local libraries root path before selecting a root.')
      return
    }
    if (isCurrentStudySetDirty) {
      setStatusMessage('Save, discard, or clear the current Study Set before changing library roots.')
      return
    }

    setIsChangingLibraryRoot(true)
    try {
      const response = await localDataSource.setLibrariesRoot(librariesRoot)
      const resolvedRoot = response.libraries_root ?? librariesRoot
      setLibraryRootInput(resolvedRoot)
      const loaded = await fetchWorkbenchData(localDataSource)
      const libraryCount = response.library_count ?? loaded.libraries.length
      const libraryLabel = libraryCount === 1 ? 'library' : 'libraries'
      setLibraries(loaded.libraries)
      setSessions(loaded.sessions)
      setTracks(loaded.tracks)
      setSavedStudySets(loaded.studySets)
      setSavedSessionFilters(loaded.savedFilters)
      setSelectedLibraryIds(loaded.libraries.map((libraryItem) => libraryItem.id))
      setStatusMessage(`Connected to ${libraryCount} ${libraryLabel} under ${resolvedRoot}.`)
      setActiveDataSource(localDataSource)
      setConnectionMode('local-api')

      const cleared = emptyStudySet()
      setCurrentStudySet(cleared)
      setLastCommittedStudySet(cloneStudySet(cleared))
      setSelectedCandidateIds([])
      setPrimaryCandidateId(null)
      setSelectionAnchorCandidateId(null)
      setSelectedStudySessionIds([])
      setSelectionAnchorStudySessionId(null)
      setSelectedTrackIds([])
      setActiveSavedFilterIds([])
      setTableColumnFilters([])
      setGroupingName('')
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatusMessage(`Could not select library root through ${localDataSource.baseUrl}: ${message}`)
    } finally {
      setIsChangingLibraryRoot(false)
    }
  }

  async function refreshWorkbenchData({
    quiet = false,
    automatic = false,
  }: {
    quiet?: boolean
    automatic?: boolean
  } = {}) {
    if (workbenchRefreshInFlightRef.current || isChangingLibraryRoot) {
      return
    }

    workbenchRefreshInFlightRef.current = true
    if (!quiet) {
      setIsRefreshingWorkbenchData(true)
      setStatusMessage('Refreshing library catalog...')
    }

    const selectedAllLibraries =
      libraries.length > 0 &&
      selectedLibraryIds.length === libraries.length &&
      libraries.every((libraryItem) => selectedLibraryIds.includes(libraryItem.id))

    try {
      const libraryIdsToRefresh = selectedLibraryIds.length
        ? selectedLibraryIds
        : libraries.map((libraryItem) => libraryItem.id)
      if (activeDataSource.refreshLibrary && libraryIdsToRefresh.length) {
        await Promise.all(libraryIdsToRefresh.map((libraryId) => activeDataSource.refreshLibrary?.(libraryId)))
      }

      const loaded = await fetchWorkbenchData(activeDataSource)
      const loadedLibraryIds = new Set(loaded.libraries.map((libraryItem) => libraryItem.id))
      const loadedCandidateIds = new Set(loaded.sessions.map(candidateId))

      setLibraries(loaded.libraries)
      setSessions(loaded.sessions)
      setTracks(loaded.tracks)
      setSavedStudySets(loaded.studySets)
      setSavedSessionFilters(loaded.savedFilters)
      setSelectedLibraryIds((current) => {
        if (selectedAllLibraries) {
          return loaded.libraries.map((libraryItem) => libraryItem.id)
        }
        return current.filter((libraryId) => loadedLibraryIds.has(libraryId))
      })
      setSelectedCandidateIds((current) => current.filter((id) => loadedCandidateIds.has(id)))
      setPrimaryCandidateId((current) => (current && loadedCandidateIds.has(current) ? current : null))
      setSelectionAnchorCandidateId((current) => (current && loadedCandidateIds.has(current) ? current : null))

      if (!quiet) {
        const sessionLabel = loaded.sessions.length === 1 ? 'session' : 'sessions'
        setStatusMessage(`Refreshed library catalog: ${loaded.sessions.length} ${sessionLabel} available.`)
      } else if (automatic) {
        const newSessionCount = loaded.sessions.length - sessions.length
        if (newSessionCount > 0) {
          const sessionLabel = newSessionCount === 1 ? 'new session' : 'new sessions'
          setStatusMessage(`Library catalog refreshed: ${newSessionCount} ${sessionLabel} found.`)
        }
      }
    } catch (error) {
      if (!quiet) {
        const message = error instanceof Error ? error.message : String(error)
        setStatusMessage(`Could not refresh library catalog: ${message}`)
      }
    } finally {
      workbenchRefreshInFlightRef.current = false
      if (!quiet) {
        setIsRefreshingWorkbenchData(false)
      }
    }
  }

  function toggleColumn(columnId: ColumnId) {
    if (lockedColumns.includes(columnId)) {
      return
    }
    setVisibleColumns((current) => {
      if (current.includes(columnId)) {
        return normalizeColumnSelection(current.filter((id) => id !== columnId))
      }
      return normalizeColumnSelection([...current, columnId])
    })
  }

  function applyColumnPreset(columns: ColumnId[]) {
    setVisibleColumns(normalizeColumnSelection(columns))
  }

  function moveVisibleColumn(columnId: ColumnId, direction: -1 | 1) {
    if (lockedColumns.includes(columnId)) {
      return
    }

    setVisibleColumns((current) => {
      const fixedColumns = current.filter((id) => lockedColumns.includes(id))
      const movableColumns = current.filter((id) => !lockedColumns.includes(id))
      const index = movableColumns.indexOf(columnId)
      const targetIndex = index + direction
      if (index === -1 || targetIndex < 0 || targetIndex >= movableColumns.length) {
        return current
      }
      const nextMovableColumns = [...movableColumns]
      const [movedColumn] = nextMovableColumns.splice(index, 1)
      nextMovableColumns.splice(targetIndex, 0, movedColumn)
      return normalizeColumnSelection([...fixedColumns, ...nextMovableColumns])
    })
  }

  function canMoveVisibleColumn(columnId: ColumnId, direction: -1 | 1) {
    if (lockedColumns.includes(columnId)) {
      return false
    }
    const movableColumns = visibleColumns.filter((id) => !lockedColumns.includes(id))
    const index = movableColumns.indexOf(columnId)
    const targetIndex = index + direction
    return index !== -1 && targetIndex >= 0 && targetIndex < movableColumns.length
  }

  function toggleSavedSessionFilter(filterId: string) {
    setActiveSavedFilterIds((current) => {
      if (current.includes(filterId)) {
        return current.filter((id) => id !== filterId)
      }
      return [...current, filterId]
    })
    clearSessionSelection()
  }

  function clearSavedSessionFilters() {
    setActiveSavedFilterIds([])
    clearSessionSelection()
  }

  async function saveSessionFilter(filter: SavedSessionFilterRecord) {
    if (!activeDataSource.saveSavedSessionFilter) {
      throw new Error('The current data source does not support filter writes.')
    }
    const saved = await activeDataSource.saveSavedSessionFilter(filter)
    setSavedSessionFilters((current) => {
      const withoutOldFilter = current.filter((item) => item.id !== saved.id && item.id !== filter.id)
      return [...withoutOldFilter, saved].sort((a, b) =>
        a.displayName.localeCompare(b.displayName, undefined, { sensitivity: 'base' }),
      )
    })
    setStatusMessage(`Filter saved: "${saved.displayName}".`)
    return saved
  }

  async function deleteSavedStudySet(studySet: StudySet) {
    if (!studySet.id) {
      setStatusMessage('Only saved Study Sets can be deleted.')
      return
    }
    if (!activeDataSource.deleteStudySet) {
      setStatusMessage('The current data source does not support Study Set deletes.')
      return
    }
    if (!window.confirm(`Delete Study Set "${studySet.displayName}"? This cannot be undone.`)) {
      return
    }
    try {
      await activeDataSource.deleteStudySet(studySet.id)
      broadcastStudySetDeleted(studySet)
      setSavedStudySets((current) => current.filter((item) => item.id !== studySet.id))
      if (currentStudySet.id === studySet.id) {
        const empty = emptyStudySet()
        setCurrentStudySet(empty)
        setLastCommittedStudySet(cloneStudySet(empty))
        setSelectedStudySessionIds([])
        setSelectionAnchorStudySessionId(null)
        setGroupingName('')
      }
      setStatusMessage(`Deleted Study Set "${studySet.displayName}".`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatusMessage(`Could not delete Study Set: ${message}`)
    }
  }

  async function deleteLibrarySession(session: SessionRecord) {
    if (!activeDataSource.deleteSession) {
      setStatusMessage('The current data source does not support session deletes.')
      return
    }
    if (
      !window.confirm(
        `Delete processed session "${session.name}" from ${session.libraryId}? Source files will not be deleted.`,
      )
    ) {
      return
    }

    try {
      await activeDataSource.deleteSession(session)
      await refreshAfterSessionDelete(session)
      setStatusMessage(`Deleted session "${session.name}".`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (!message.toLowerCase().includes('referenced')) {
        setStatusMessage(`Could not delete session: ${message}`)
        return
      }
      if (
        !window.confirm(
          `Session "${session.name}" is used by saved Study Sets. Remove it from those Study Sets, delete empty groupings, and delete the session?`,
        )
      ) {
        setStatusMessage('Session delete cancelled; saved Study Set memberships were left unchanged.')
        return
      }
      try {
        await activeDataSource.deleteSession(session, { cleanupMemberships: true })
        await refreshAfterSessionDelete(session)
        setStatusMessage(`Deleted session "${session.name}" and cleaned saved Study Set memberships.`)
      } catch (cleanupError) {
        const cleanupMessage = cleanupError instanceof Error ? cleanupError.message : String(cleanupError)
        setStatusMessage(`Could not delete session with cleanup: ${cleanupMessage}`)
      }
    }
  }

  async function refreshAfterSessionDelete(session: SessionRecord) {
    const deletedRefId = candidateId(session)
    invalidateSuspensionCacheForSession(activeDataSource, deletedRefId)
    broadcastSessionDeleted(deletedRefId, session.name)
    const loaded = await fetchWorkbenchData(activeDataSource)
    const remainingSessions = loaded.sessions.filter((item) => candidateId(item) !== deletedRefId)
    setLibraries(applySessionCounts(loaded.libraries, remainingSessions))
    setSessions(remainingSessions)
    setTracks(loaded.tracks)
    setSavedStudySets(loaded.studySets)
    setSavedSessionFilters(loaded.savedFilters)
    setSelectedCandidateIds((current) => current.filter((id) => id !== deletedRefId))
    setPrimaryCandidateId((current) => (current === deletedRefId ? null : current))
    setSelectionAnchorCandidateId((current) => (current === deletedRefId ? null : current))
    setSelectedStudySessionIds((current) => current.filter((id) => id !== deletedRefId))
    setSelectionAnchorStudySessionId((current) => (current === deletedRefId ? null : current))
    setModal((current) =>
      current?.kind === 'session' && candidateId(current.session) === deletedRefId ? null : current,
    )
    setNoteEditorSession((current) => (current && candidateId(current) === deletedRefId ? null : current))

    if (currentStudySet.id && !isCurrentStudySetDirty) {
      const refreshedStudySet = loaded.studySets.find((studySet) => studySet.id === currentStudySet.id)
      if (refreshedStudySet) {
        setCurrentStudySet(refreshedStudySet)
        setLastCommittedStudySet(cloneStudySet(refreshedStudySet))
        return
      }
    }
    setCurrentStudySet((current) => removeSessionFromStudySetValue(current, deletedRefId, false))
    const refreshedStudySet = currentStudySet.id
      ? loaded.studySets.find((studySet) => studySet.id === currentStudySet.id)
      : null
    setLastCommittedStudySet((current) =>
      refreshedStudySet ? cloneStudySet(refreshedStudySet) : removeSessionFromStudySetValue(current, deletedRefId, true),
    )
  }

  async function deleteSessionFilter(filter: SavedSessionFilterRecord) {
    if (!activeDataSource.deleteSavedSessionFilter) {
      throw new Error('The current data source does not support filter deletes.')
    }
    if (filter.origin !== 'api_saved') {
      throw new Error('Prototype filters cannot be deleted.')
    }
    await activeDataSource.deleteSavedSessionFilter(filter.id)
    setSavedSessionFilters((current) => current.filter((item) => item.id !== filter.id))
    setActiveSavedFilterIds((current) => current.filter((filterId) => filterId !== filter.id))
    setStatusMessage(`Deleted filter "${filter.displayName}".`)
    clearSessionSelection()
  }

  function setTableColumnFilter(columnId: ColumnId, values: string[]) {
    setTableColumnFilters((current) => {
      const nextValues = Array.from(new Set(values)).filter(Boolean)
      const withoutColumn = current.filter((filter) => filter.columnId !== columnId)
      if (nextValues.length === 0) {
        return withoutColumn
      }
      return [...withoutColumn, { columnId, values: nextValues }]
    })
    clearSessionSelection()
  }

  function clearTableColumnFilter(columnId: ColumnId) {
    setTableColumnFilters((current) => current.filter((filter) => filter.columnId !== columnId))
    clearSessionSelection()
  }

  function clearSessionSelection() {
    setSelectedCandidateIds([])
    setPrimaryCandidateId(null)
    setSelectionAnchorCandidateId(null)
  }

  function setSort(columnId: ColumnId) {
    if (sortColumn === columnId) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortColumn(columnId)
    setSortDirection('asc')
  }

  function inspectSession(session: SessionRecord, tab: SessionInspectionTab) {
    if (tab === 'note') {
      setModal(null)
      setNoteEditorSession(session)
      return
    }
    if (tab === 'signals') {
      setModal({ kind: 'signal-inspector', session, initialWindow: null })
      return
    }
    setModal({ kind: 'session', session, tab })
  }

  function showBothWorkbenchPanels() {
    setLeftCollapsed(false)
    setRightCollapsed(false)
  }

  function showStudySetPanelOnly() {
    setLeftCollapsed(true)
    setRightCollapsed(false)
  }

  function showLibraryPanelOnly() {
    setLeftCollapsed(false)
    setRightCollapsed(true)
  }

  function openAnalysisLauncher(studySet: StudySet) {
    setModal({ kind: 'analysis-launcher', studySet: cloneStudySet(studySet) })
  }

  function openAnalysisView(viewId: string, studySet: StudySet) {
    if (viewId === 'simple-suspension') {
      const url = analysisRouteUrl(viewId, studySet)
      const opened = window.open(url, '_blank')
      if (!opened) {
        window.location.href = url
      } else {
        opened.opener = null
      }
      setModal(null)
      setStatusMessage(`Opened ${studySet.displayName || 'Study Set'} analysis in a browser tab.`)
      return
    }
    setStatusMessage(`Analysis view "${viewId}" is not implemented in this prototype yet.`)
  }

  function updateSessionAfterNoteSave(updatedSession: SessionRecord) {
    setSessions((current) =>
      current.map((session) => (candidateId(session) === candidateId(updatedSession) ? updatedSession : session)),
    )
  }

  function selectCandidate(session: SessionRecord, gesture: SessionSelectionGesture) {
    const id = candidateId(session)
    const wasSelected = selectedCandidateIds.includes(id)

    setSelectedCandidateIds((current) => {
      if (gesture.extendRange && selectionAnchorCandidateId) {
        const visibleIds = visibleSessions.map(candidateId)
        const anchorIndex = visibleIds.indexOf(selectionAnchorCandidateId)
        const targetIndex = visibleIds.indexOf(id)

        if (anchorIndex >= 0 && targetIndex >= 0) {
          const start = Math.min(anchorIndex, targetIndex)
          const end = Math.max(anchorIndex, targetIndex)
          const rangeIds = visibleIds.slice(start, end + 1)
          if (gesture.toggle) {
            return uniqueStrings([...current, ...rangeIds])
          }
          return rangeIds
        }
      }

      if (gesture.toggle) {
        if (current.includes(id)) {
          return current.filter((item) => item !== id)
        }
        return [...current, id]
      }

      return [id]
    })

    if (gesture.toggle && wasSelected && !gesture.extendRange) {
      const remainingSelectedIds = selectedCandidateIds.filter((item) => item !== id)
      setPrimaryCandidateId(remainingSelectedIds[0] ?? null)
    } else {
      setPrimaryCandidateId(id)
    }
    setSelectionAnchorCandidateId(id)
  }

  function addSelectedSessionsToStudySet() {
    if (selectedCandidateSessions.length === 0) {
      setStatusMessage('Select one or more sessions before adding to the Study Set.')
      return
    }

    setCurrentStudySet((current) => {
      const existingIds = new Set(current.sessions.map(sessionRefId))
      const nextSessions = [...current.sessions]
      for (const session of selectedCandidateSessions) {
        const ref = sessionToStudyRef(session)
        if (!existingIds.has(sessionRefId(ref))) {
          nextSessions.push(ref)
          existingIds.add(sessionRefId(ref))
        }
      }
      return {
        ...current,
        sessions: nextSessions,
        saved: false,
      }
    })
    setStatusMessage(`${selectedCandidateSessions.length} selected session(s) added to the current Study Set.`)
  }

  function addSessionRefToStudySet(sessionRef: StudySet['sessions'][number]) {
    setCurrentStudySet((current) => {
      const refId = sessionRefId(sessionRef)
      if (current.sessions.some((item) => sessionRefId(item) === refId)) {
        return current
      }
      return {
        ...current,
        sessions: [...current.sessions, sessionRef],
        saved: false,
      }
    })
    setStatusMessage(`${sessionRef.label || sessionRef.sessionId} added to the current Study Set.`)
  }

  function analyzeNow() {
    if (!primarySession) {
      setStatusMessage('Choose a primary session before using Analyze now.')
      return
    }
    requestStudySetReplacement({ kind: 'analyze-now', session: primarySession })
  }

  function executeAnalyzeNow(session: SessionRecord) {
    const temporarySet: StudySet = {
      ...emptyStudySet(),
      displayName: `Analyze now: ${session.name}`,
      sessions: [sessionToStudyRef(session)],
      provenance: 'Temporary one-session Study Set created by Analyze now',
    }
    setCurrentStudySet(temporarySet)
    setLastCommittedStudySet(cloneStudySet(temporarySet))
    setSelectedStudySessionIds([])
    setSelectionAnchorStudySessionId(null)
    setGroupingName('')
    openAnalysisLauncher(temporarySet)
    setStatusMessage('Created an unsaved one-session Study Set for analysis.')
  }

  function removeStudySession(refId: string) {
    setCurrentStudySet((current) => ({
      ...current,
      saved: false,
      sessions: current.sessions.filter((session) => sessionRefId(session) !== refId),
      groupings: current.groupings
        .map((grouping) => ({
          ...grouping,
          sessionRefs: grouping.sessionRefs.filter((sessionRef) => sessionRef !== refId),
        }))
        .filter((grouping) => grouping.sessionRefs.length > 0),
    }))
    setSelectedStudySessionIds((current) => current.filter((id) => id !== refId))
    setSelectionAnchorStudySessionId((current) => (current === refId ? null : current))
  }

  function selectStudySession(refId: string, gesture: SessionSelectionGesture) {
    setSelectedStudySessionIds((current) => {
      if (gesture.extendRange && selectionAnchorStudySessionId) {
        const studySessionIds = currentStudySet.sessions.map(sessionRefId)
        const anchorIndex = studySessionIds.indexOf(selectionAnchorStudySessionId)
        const targetIndex = studySessionIds.indexOf(refId)

        if (anchorIndex >= 0 && targetIndex >= 0) {
          const start = Math.min(anchorIndex, targetIndex)
          const end = Math.max(anchorIndex, targetIndex)
          const rangeIds = studySessionIds.slice(start, end + 1)
          if (gesture.toggle) {
            return uniqueStrings([...current, ...rangeIds])
          }
          return rangeIds
        }
      }

      if (gesture.toggle) {
        if (current.includes(refId)) {
          return current.filter((id) => id !== refId)
        }
        return [...current, refId]
      }

      return [refId]
    })
    setSelectionAnchorStudySessionId(refId)
  }

  function createGrouping() {
    const trimmedName = groupingName.trim()
    if (!trimmedName || selectedStudySessionIds.length === 0) {
      setStatusMessage('Name a grouping and select Study Set sessions first.')
      return
    }
    const grouping: StudyGrouping = {
      id: uniqueId(slugify(trimmedName), currentStudySet.groupings.map((item) => item.id)),
      name: trimmedName,
      color: groupingColors[currentStudySet.groupings.length % groupingColors.length],
      sessionRefs: selectedStudySessionIds,
    }
    setCurrentStudySet((current) => ({
      ...current,
      saved: false,
      groupings: [...current.groupings, grouping],
    }))
    setGroupingName('')
    setSelectedStudySessionIds([])
    setSelectionAnchorStudySessionId(null)
    setStatusMessage(`Grouping "${grouping.name}" added. Sessions can belong to multiple groupings.`)
  }

  function removeGrouping(groupingId: string) {
    setCurrentStudySet((current) => ({
      ...current,
      saved: false,
      groupings: current.groupings.filter((grouping) => grouping.id !== groupingId),
    }))
  }

  function toggleTrack(trackId: string) {
    setSelectedTrackIds((current) => {
      if (current.includes(trackId)) {
        return current.filter((id) => id !== trackId)
      }
      return [...current, trackId]
    })
  }

  function addTrackToStudySet(trackId: string) {
    setCurrentStudySet((current) => ({
      ...current,
      saved: current.trackIds.includes(trackId) ? current.saved : false,
      trackIds: Array.from(new Set([...current.trackIds, trackId])),
    }))
    setStatusMessage('Track attached to the Study Set.')
  }

  function upsertTrack(track: TrackRecord) {
    setTracks((currentTracks) => {
      const exists = currentTracks.some((item) => item.id === track.id)
      return exists ? currentTracks.map((item) => (item.id === track.id ? track : item)) : [...currentTracks, track]
    })
    setModal((current) => (current?.kind === 'track' && current.track.id === track.id ? { kind: 'track', track } : current))
  }

  function deleteTrackFromWorkbench(trackId: string) {
    setTracks((currentTracks) => currentTracks.filter((track) => track.id !== trackId))
    setSelectedTrackIds((current) => current.filter((id) => id !== trackId))
    setCurrentStudySet((current) => ({
      ...current,
      saved: current.trackIds.includes(trackId) ? false : current.saved,
      trackIds: current.trackIds.filter((id) => id !== trackId),
    }))
    setModal((current) => (current?.kind === 'track' && current.track.id === trackId ? null : current))
  }

  function removeTrack(trackId: string) {
    setCurrentStudySet((current) => ({
      ...current,
      saved: false,
      trackIds: current.trackIds.filter((id) => id !== trackId),
    }))
  }

  function updateStudySetName(displayName: string) {
    setCurrentStudySet((current) => ({
      ...current,
      displayName,
      saved: false,
    }))
  }

  async function saveCurrentStudySet(): Promise<StudySet | null> {
    const displayName = currentStudySet.displayName.trim()
    if (!displayName) {
      setStatusMessage('Name the Study Set before saving.')
      return null
    }
    if (currentStudySet.sessions.length === 0) {
      setStatusMessage('Add at least one session before saving a Study Set.')
      return null
    }

    try {
      const saved = await activeDataSource.saveStudySet({
        ...currentStudySet,
        displayName,
      })
      broadcastStudySetUpdated(saved)
      setSavedStudySets(await activeDataSource.listStudySets())
      setCurrentStudySet(saved)
      setLastCommittedStudySet(cloneStudySet(saved))
      setStatusMessage(`Saved "${saved.displayName}" at revision ${saved.revision}.`)
      return saved
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatusMessage(`Could not save Study Set: ${message}`)
      return null
    }
  }

  function requestLoadStudySet(studySet: StudySet) {
    requestStudySetReplacement({ kind: 'load', studySet })
  }

  function requestClearStudySet() {
    if (!currentStudySetHasContent) {
      setStatusMessage('The current Study Set is already clear.')
      return
    }
    requestStudySetReplacement({ kind: 'clear' })
  }

  function requestStudySetReplacement(action: PendingStudySetAction) {
    if (isCurrentStudySetDirty) {
      setPendingStudySetAction(action)
      return
    }
    executeStudySetReplacement(action)
  }

  function executeStudySetReplacement(action: PendingStudySetAction) {
    if (action.kind === 'load') {
      const loaded = cloneStudySet(action.studySet)
      setCurrentStudySet(loaded)
      setLastCommittedStudySet(cloneStudySet(loaded))
      setSelectedStudySessionIds([])
      setSelectionAnchorStudySessionId(null)
      setGroupingName('')
      setStatusMessage(`Loaded "${action.studySet.displayName}" into the current Study Set editor.`)
      return
    }

    if (action.kind === 'analyze-now') {
      executeAnalyzeNow(action.session)
      return
    }

    const cleared = emptyStudySet()
    setCurrentStudySet(cleared)
    setLastCommittedStudySet(cloneStudySet(cleared))
    setSelectedStudySessionIds([])
    setSelectionAnchorStudySessionId(null)
    setGroupingName('')
    setStatusMessage('Cleared the current Study Set.')
  }

  async function savePendingStudySetAction() {
    if (!pendingStudySetAction) {
      return
    }
    const action = pendingStudySetAction
    const saved = await saveCurrentStudySet()
    if (!saved) {
      return
    }
    setPendingStudySetAction(null)
    executeStudySetReplacement(action)
  }

  function discardPendingStudySetAction() {
    if (!pendingStudySetAction) {
      return
    }
    const action = pendingStudySetAction
    setPendingStudySetAction(null)
    executeStudySetReplacement(action)
  }

  function cancelPendingStudySetAction() {
    setPendingStudySetAction(null)
    setStatusMessage('Kept the current Study Set open for editing.')
  }

  async function refreshAnalysisRouteScope() {
    if (!analysisRoute?.studySetId) {
      setAnalysisScopeNotice(null)
      return
    }
    const studySetId = analysisRoute.studySetId
    setAnalysisRouteStudySetLoading(true)
    setAnalysisRouteStudySetError('')
    try {
      const refreshed = activeDataSource.loadStudySet
        ? await activeDataSource.loadStudySet(studySetId)
        : savedStudySets.find((studySet) => studySet.id === studySetId)
      if (!refreshed) {
        setAnalysisRouteStudySet(null)
        setAnalysisRouteStudySetError('The saved Study Set could not be refreshed.')
        return
      }
      setAnalysisRouteStudySet(cloneStudySet(refreshed))
      setAnalysisScopeNotice(null)
      setStatusMessage(`Refreshed analysis scope "${refreshed.displayName}".`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setAnalysisRouteStudySetError(message)
      setStatusMessage(`Could not refresh analysis scope: ${message}`)
    } finally {
      setAnalysisRouteStudySetLoading(false)
    }
  }

  if (analysisRoute) {
    const routeStudySet = analysisRoute.scopeToken ? loadAnalysisScope(analysisRoute.scopeToken) : analysisRouteStudySet
    return (
      <AnalysisRoutePage
        route={analysisRoute}
        studySet={routeStudySet}
        loadingScope={analysisRouteStudySetLoading}
        scopeError={analysisRouteStudySetError}
        scopeNotice={analysisScopeNotice}
        sessions={sessions}
        tracks={tracks}
        dataSource={activeDataSource}
        statusMessage={statusMessage}
        connectionMode={connectionMode}
        onRefreshScope={() => void refreshAnalysisRouteScope()}
        onDismissScopeNotice={() => setAnalysisScopeNotice(null)}
      />
    )
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">BODAQS application prototype</p>
          <h1>Library Browser and Study Set Builder</h1>
        </div>
        <div className="header-status">
          <span>{statusMessage}</span>
        </div>
      </header>

      <section
        className={[
          'workbench',
          leftCollapsed ? 'left-collapsed' : '',
          rightCollapsed ? 'right-collapsed' : '',
        ].join(' ')}
      >
        <aside className="panel library-panel" aria-label="Library Browser">
          <PanelTitle
            icon={<Library size={18} />}
            title="Library Browser"
            action={<span className="panel-title-spacer" />}
          />

          <section className={`module collapsible-module${librarySelectorCollapsed ? ' collapsed' : ''}`}>
            {librarySelectorCollapsed ? (
              <button className="collapsed-root-row" type="button" onClick={() => setLibrarySelectorCollapsed(false)}>
                <span>
                  <strong>Library root:</strong> {libraryRootInput || 'No library root selected'}
                </span>
                <span className="collapsed-root-count">
                  {libraries.length} libraries / {selectedLibraries.length} selected
                </span>
                <ChevronDown size={16} />
              </button>
            ) : (
              <>
                <div className="module-header">
                  <h2 className="module-heading">
                    Library Selector
                    <InfoTip text="Choose which libraries from the configured library root are included in the session browser." />
                  </h2>
                  <div className="module-header-actions">
                    <span className="module-header-count">{selectedLibraries.length} active</span>
                    <IconButton
                      label="Collapse Library Selector"
                      onClick={() => setLibrarySelectorCollapsed(true)}
                      icon={<ChevronUp size={16} />}
                    />
                  </div>
                </div>
                <div className="library-root-control">
                  <label>
                    <span>Library root</span>
                    <input
                      value={libraryRootInput}
                      onChange={(event) => setLibraryRootInput(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          void applyLibraryRoot()
                        }
                      }}
                      placeholder="Paste a local libraries root path"
                    />
                  </label>
                  <button
                    className="secondary-action"
                    disabled={isChangingLibraryRoot}
                    onClick={() => void applyLibraryRoot()}
                    type="button"
                  >
                    <FolderOpen size={16} />
                    Select root
                  </button>
                </div>
                <p className="connection-note">
                  <strong>{connectionMode === 'local-api' ? 'Local API' : 'Fixture fallback'}</strong>
                  <span>{localDataSource.baseUrl}</span>
                </p>
                <div className="library-list">
                  {libraries.map((libraryItem) => (
                    <label className="check-row" key={libraryItem.id}>
                      <input
                        type="checkbox"
                        checked={selectedLibraryIds.includes(libraryItem.id)}
                        onChange={() => toggleLibrary(libraryItem.id)}
                      />
                      <span>
                        <strong>{libraryItem.name}</strong>
                        <small>{libraryItem.sessionCount} sessions</small>
                      </span>
                    </label>
                  ))}
                </div>
              </>
            )}
          </section>

          <section className={`module session-selector collapsible-module${sessionSelectorCollapsed ? ' collapsed' : ''}`}>
            <div className="module-header">
              <h2 className="module-heading">
                Session Selector
                <InfoTip text="Browse sessions from the selected libraries. Use reusable filters from the filter panel or column filter icons in the table to narrow the list." />
              </h2>
              <div className="module-header-actions">
                <span className="module-header-count">
                  {libraryScopedSessions.length} total / {visibleSessions.length} filtered / {selectedCandidateIds.length} selected
                </span>
                <IconButton
                  label="Refresh Session Selector"
                  onClick={() => void refreshWorkbenchData()}
                  disabled={isRefreshingWorkbenchData || isChangingLibraryRoot}
                  icon={<RefreshCw size={16} />}
                />
                <IconButton
                  label={sessionSelectorCollapsed ? 'Expand Session Selector' : 'Collapse Session Selector'}
                  onClick={() => setSessionSelectorCollapsed((current) => !current)}
                  icon={sessionSelectorCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                />
              </div>
            </div>
            {!sessionSelectorCollapsed && (
              <>
                <div className="toolbar">
                  <label className="search-field">
                    <Search size={16} />
                    <input
                      value={searchText}
                      onChange={(event) => setSearchText(event.target.value)}
                      placeholder="Search visible fields"
                    />
                  </label>
                  <div className="column-menu" ref={columnMenuRef}>
                    <button
                      aria-expanded={columnMenuOpen}
                      className="column-menu-button"
                      onClick={() => setColumnMenuOpen((current) => !current)}
                      type="button"
                    >
                      <Columns3 size={16} />
                      Columns
                    </button>
                    {columnMenuOpen && (
                      <div className="column-popover">
                        <div className="column-presets" aria-label="Column presets">
                          {columnPresets.map((preset) => (
                            <button
                              className="preset-button"
                              key={preset.id}
                              title={preset.description}
                              type="button"
                              onClick={() => applyColumnPreset(preset.columns)}
                            >
                              {preset.label}
                            </button>
                          ))}
                        </div>
                        <div className="column-order-panel" aria-label="Visible column order">
                          <div className="column-order-title">Visible order</div>
                          <div className="column-order-list">
                            {visibleColumns.map((columnId) => {
                              const locked = lockedColumns.includes(columnId)
                              return (
                                <div className="column-order-row" key={columnId}>
                                  <span className="column-order-label">
                                    {columnLabels[columnId]}
                                    {locked ? <span>fixed</span> : null}
                                  </span>
                                  <div className="column-order-actions">
                                    <button
                                      aria-label={`Move ${columnLabels[columnId]} earlier`}
                                      disabled={!canMoveVisibleColumn(columnId, -1)}
                                      onClick={() => moveVisibleColumn(columnId, -1)}
                                      type="button"
                                    >
                                      <ChevronUp size={13} />
                                    </button>
                                    <button
                                      aria-label={`Move ${columnLabels[columnId]} later`}
                                      disabled={!canMoveVisibleColumn(columnId, 1)}
                                      onClick={() => moveVisibleColumn(columnId, 1)}
                                      type="button"
                                    >
                                      <ChevronDown size={13} />
                                    </button>
                                  </div>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                        {columnGroups.map((group) => (
                          <fieldset className="column-group" key={group.id}>
                            <legend>{group.label}</legend>
                            {group.columns.map((columnId) => {
                              const locked = lockedColumns.includes(columnId)
                              return (
                                <label className="check-row compact" key={columnId}>
                                  <input
                                    type="checkbox"
                                    checked={visibleColumns.includes(columnId)}
                                    disabled={locked}
                                    onChange={() => toggleColumn(columnId)}
                                  />
                                  <span>{columnLabels[columnId]}{locked ? ' (fixed)' : ''}</span>
                                </label>
                              )
                            })}
                          </fieldset>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
                <SessionTable
                  sessions={visibleSessions}
                  filterBaseSessions={savedFilteredSessions}
                  libraries={libraries}
                  visibleColumns={visibleColumns}
                  tableColumnFilters={tableColumnFilters}
                  selectedIds={selectedCandidateIds}
                  primaryId={primaryCandidateId}
                  sortColumn={sortColumn}
                  sortDirection={sortDirection}
                  onTableColumnFilterChange={setTableColumnFilter}
                  onClearTableColumnFilter={clearTableColumnFilter}
                  onSort={setSort}
                  onSelect={selectCandidate}
                  onInspect={inspectSession}
                  onDeleteSession={deleteLibrarySession}
                />
                <div className="action-row">
                  <button className="primary-action" onClick={addSelectedSessionsToStudySet}>
                    <Plus size={17} />
                    Add to Study Set
                  </button>
                  <button className="secondary-action" onClick={analyzeNow}>
                    <Play size={17} />
                    Analyze now
                  </button>
                </div>
              </>
            )}
          </section>

          <section className={`lower-grid${gpsLocationCollapsed ? ' gps-collapsed' : ''}`}>
            {gpsLocationCollapsed ? (
              <button className="gps-rail" onClick={() => setGpsLocationCollapsed(false)} type="button">
                <ChevronRight size={18} />
                GPS Location
              </button>
            ) : (
              <section className="module map-module">
                <div className="module-header">
                  <h2 className="module-heading">
                    GPS Location
                    <InfoTip text="Preview the selected session GPS path and any selected or attached tracks." />
                  </h2>
                  <div className="module-header-actions">
                    <span className="module-header-count">{primarySession ? primarySession.name : 'No primary session'}</span>
                    <IconButton
                      label="Collapse GPS Location"
                      onClick={() => setGpsLocationCollapsed(true)}
                      icon={<ChevronLeft size={16} />}
                    />
                  </div>
                </div>
                <GpsRoutePreview
                  session={primarySession}
                  dataSource={activeDataSource}
                  selectedTracks={selectedTracks}
                  currentTracks={currentStudyTracks}
                />
              </section>
            )}

            <div className="support-stack">
              <section className={`module collapsible-module${filtersCollapsed ? ' collapsed' : ''}`}>
                <div className="module-header">
                  <h2 className="module-heading">
                    Filters
                    <InfoTip text="Create and apply reusable filters on the sessions displayed. Filters stack and combine with table filtering." />
                  </h2>
                  <div className="module-header-actions">
                    <span className="module-header-count">
                      {savedSessionFilters.length} available / {activeSavedSessionFilters.length} active
                    </span>
                    <IconButton
                      label={filtersCollapsed ? 'Expand Filters' : 'Collapse Filters'}
                      onClick={() => setFiltersCollapsed((current) => !current)}
                      icon={filtersCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                    />
                  </div>
                </div>
                {!filtersCollapsed && (
                  <FilterPanel
                    savedFilters={savedSessionFilters}
                    activeSavedFilterIds={activeSavedFilterIds}
                    trackpointFilterStates={activeGeoFilterStates}
                    onToggleSavedFilter={toggleSavedSessionFilter}
                    onClearSavedFilters={clearSavedSessionFilters}
                    onManageSavedFilters={() => setFilterManagerOpen(true)}
                  />
                )}
              </section>

              <GeospatialWorkbench
                primarySession={primarySession}
                currentStudySet={currentStudySet}
                sessions={sessions}
                tracks={tracks}
                selectedTrackIds={selectedTrackIds}
                dataSource={activeDataSource}
                onToggleTrack={toggleTrack}
                onAttachTrack={addTrackToStudySet}
                onAttachSession={addSessionRefToStudySet}
                onTrackSaved={upsertTrack}
                onTrackDeleted={deleteTrackFromWorkbench}
              />
            </div>
          </section>
        </aside>

        <div className="center-collapse-controls" aria-label="Workbench panel controls">
          <IconButton
            label="Show Study Set Builder only"
            disabled={leftCollapsed && !rightCollapsed}
            onClick={showStudySetPanelOnly}
            icon={<ChevronLeft size={17} />}
          />
          <IconButton
            label="Show both panels"
            disabled={!leftCollapsed && !rightCollapsed}
            onClick={showBothWorkbenchPanels}
            icon={<Columns3 size={17} />}
          />
          <IconButton
            label="Show Library Browser only"
            disabled={rightCollapsed && !leftCollapsed}
            onClick={showLibraryPanelOnly}
            icon={<ChevronRight size={17} />}
          />
        </div>

        <aside className="panel study-panel" aria-label="Study Set Builder">
          <PanelTitle
            icon={<BookOpen size={18} />}
            title="Study Set Builder"
            action={<span className="panel-title-spacer" />}
          />

          <section className="module current-study-set">
            <div className="module-header">
              <h2 className="module-heading">
                Current Study Set
                <InfoTip text="The working Study Set comprising sessions and optional groupings and tracks." />
              </h2>
              <div className="module-header-actions">
                <span className="module-header-count study-set-count">
                  {currentStudySet.sessions.length} sessions / {currentStudySet.groupings.length} groupings / {currentStudySet.trackIds.length} tracks
                </span>
                <span className={currentStudySetStatus.className}>{currentStudySetStatus.label}</span>
              </div>
            </div>

            <div className="study-name-row">
              <label>
                <span>Name</span>
                <input
                  value={currentStudySet.displayName}
                  onChange={(event) => updateStudySetName(event.target.value)}
                  placeholder="Name this Study Set"
                />
              </label>
              <button
                className="primary-action compact-row-action"
                disabled={!canSaveCurrentStudySet}
                onClick={() => void saveCurrentStudySet()}
              >
                <Save size={17} />
                Save
              </button>
              <button className="danger-action compact-row-action" disabled={!currentStudySetHasContent} onClick={requestClearStudySet}>
                <Trash2 size={17} />
                Clear
              </button>
              <button
                className="secondary-action compact-row-action"
                onClick={() => openAnalysisLauncher(currentStudySet)}
              >
                <BarChart3 size={17} />
                Analyze
              </button>
            </div>

            <section className="study-section">
              <div className="subsection-header">
                <h3 className="subsection-heading">
                  Sessions
                  <InfoTip text="List of the sessions in this study set. Removing a session removes it from the Study Set, but not from the library." />
                </h3>
              </div>
              <StudySessionTable
                studySet={currentStudySet}
                libraries={libraries}
                sessions={sessions}
                visibleColumns={visibleColumns}
                selectedStudySessionIds={selectedStudySessionIds}
                primaryStudySessionId={selectionAnchorStudySessionId}
                onSelect={selectStudySession}
                onRemove={removeStudySession}
                onInspect={inspectSession}
              />
            </section>

            <section className="study-section">
              <div className="subsection-header">
                <h3 className="subsection-heading">
                  Groupings
                  <InfoTip text="Named collections of Study Set sessions. Sessions can belong to more than one grouping." />
                </h3>
              </div>
              <div className="grouping-editor">
                <label>
                  <span>New grouping</span>
                  <input
                    value={groupingName}
                    onChange={(event) => setGroupingName(event.target.value)}
                    placeholder="Short name"
                  />
                </label>
                <button className="secondary-action compact-row-action" onClick={createGrouping}>
                  <GitBranch size={16} />
                  Add grouping
                </button>
              </div>
              <div className="grouping-list">
                {currentStudySet.groupings.length === 0 && <p className="empty-note">No groupings yet.</p>}
                {currentStudySet.groupings.map((grouping) => (
                  <span className="group-chip" style={{ borderColor: grouping.color }} key={grouping.id}>
                    <span className="color-dot" style={{ backgroundColor: grouping.color }} />
                    {grouping.name}
                    <small>{grouping.sessionRefs.length}</small>
                    <button onClick={() => removeGrouping(grouping.id)} title={`Remove ${grouping.name}`}>
                      <X size={13} />
                    </button>
                  </span>
                ))}
              </div>
            </section>

            <section className="study-section">
              <div className="subsection-header">
                <h3 className="subsection-heading">
                  Tracks
                  <InfoTip text="Tracks are GPS paths with defined points that can be used for geospatial filtering and sector-based analysis." />
                </h3>
              </div>
              <table className="tracks-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trackpoints</th>
                    <th>Distance</th>
                    <th className="info-action-heading">
                      <span title="Track actions" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {currentStudyTracks.length === 0 && (
                    <tr>
                      <td colSpan={4} className="empty-cell">
                        No tracks attached.
                      </td>
                    </tr>
                  )}
                  {currentStudyTracks.map((track) => (
                    <tr key={track.id}>
                      <td>{track.name}</td>
                      <td>{track.trackpoints.length}</td>
                      <td>{track.distanceKm.toFixed(1)} km</td>
                      <td className="icon-cluster info-action-cell">
                        <IconButton
                          label="Remove Track"
                          onClick={() => removeTrack(track.id)}
                          icon={<Minus size={15} />}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </section>

          <section className={`study-geo-grid${studyGpsCollapsed ? ' study-gps-collapsed' : ''}`}>
            {studyGpsCollapsed ? (
              <button
                className="gps-rail study-gps-rail"
                type="button"
                onClick={() => setStudyGpsCollapsed(false)}
              >
                <ChevronRight size={18} />
                Study Set GPS
              </button>
            ) : (
              <section className="module map-module study-map-module">
                <div className="module-header">
                  <h2 className="module-heading">
                    Study Set GPS Location
                    <InfoTip text="Preview the GPS paths for sessions in the current Study Set and any tracks attached to it." />
                  </h2>
                  <div className="module-header-actions">
                    <span className="module-header-count">
                      {studySetMapSessionPaths.length} session path(s) / {currentStudyTracks.length} track(s)
                    </span>
                    <IconButton
                      label="Collapse Study Set GPS"
                      onClick={() => setStudyGpsCollapsed(true)}
                      icon={<ChevronLeft size={16} />}
                    />
                  </div>
                </div>
                <div className="study-map-frame">
                  <MapRoutePreview
                    primarySession={null}
                    sessionPaths={studySetMapSessionPaths}
                    selectedTracks={[]}
                    currentTracks={currentStudyTracks}
                  />
                </div>
              </section>
            )}

            <div className="support-stack study-geo-support">
              <section className="module saved-study-sets">
                <div className="module-header">
                  <h2 className="module-heading">
                    Saved Study Sets
                    <InfoTip text="Saved Study Sets can be loaded into the editor above, inspected, or opened directly in the analysis view." />
                  </h2>
                  <span className="module-header-count">{savedStudySets.length} saved</span>
                </div>
                <table className="saved-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Sessions</th>
                      <th>Tracks</th>
                      <th>Groups</th>
                      <th className="info-action-heading">
                        <span title="Study Set actions" />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {savedStudySets.map((studySet) => (
                      <tr key={studySet.id ?? studySet.displayName}>
                        <td>{studySet.displayName}</td>
                        <td>{studySet.sessions.length}</td>
                        <td>{studySet.trackIds.length}</td>
                        <td>{studySet.groupings.length}</td>
                        <td className="icon-cluster info-action-cell saved-study-set-action-cell">
                          <IconButton
                            label="Load Study Set"
                            onClick={() => requestLoadStudySet(studySet)}
                            icon={<FileText size={15} />}
                          />
                          <IconButton
                            label="Simple Suspension Analysis"
                            onClick={() => openAnalysisLauncher(studySet)}
                            icon={<Play size={15} />}
                          />
                          <IconButton
                            label="Delete Study Set"
                            disabled={!studySet.id || !activeDataSource.deleteStudySet}
                            onClick={() => void deleteSavedStudySet(studySet)}
                            icon={<Trash2 size={15} />}
                            tone="alert"
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
              <StudySetGpsCoverageCard currentStudySet={currentStudySet} sessions={sessions} />
              <MatchPreviewCard
                currentStudySet={currentStudySet}
                sessions={sessions}
                currentStudyTracks={currentStudyTracks}
              />
            </div>
          </section>
        </aside>

      </section>

      {modal && (
        <Modal
          state={modal}
          libraries={libraries}
          sessions={sessions}
          tracks={tracks}
          dataSource={activeDataSource}
          bookmarkRefreshToken={bookmarkRefreshToken}
          onClose={() => setModal(null)}
          onOpenAnalysis={openAnalysisView}
          onOpenSignalInspector={(session, initialWindow = null) =>
            setModal({ kind: 'signal-inspector', session, initialWindow })
          }
          onSessionBookmarksChanged={() => setBookmarkRefreshToken((current) => current + 1)}
        />
      )}
      {noteEditorSession && (
        <SessionNoteEditorModal
          session={noteEditorSession}
          dataSource={activeDataSource}
          onClose={() => setNoteEditorSession(null)}
          onSaved={updateSessionAfterNoteSave}
        />
      )}
      {filterManagerOpen && (
        <FilterManagerModal
          filters={savedSessionFilters}
          tracks={tracks}
          canWrite={Boolean(activeDataSource.saveSavedSessionFilter)}
          onClose={() => setFilterManagerOpen(false)}
          onSave={saveSessionFilter}
          onDelete={deleteSessionFilter}
        />
      )}
      {pendingStudySetAction && (
        <UnsavedChangesDialog
          actionLabel={pendingActionLabel(pendingStudySetAction)}
          canSave={canSavePendingAction}
          onSave={() => void savePendingStudySetAction()}
          onDiscard={discardPendingStudySetAction}
          onCancel={cancelPendingStudySetAction}
        />
      )}
    </main>
  )
}

function studySetStatus(studySet: StudySet, isDirty: boolean) {
  if (isDirty) {
    return { className: 'pill warning', label: 'unsaved changes' }
  }
  if (isTemporaryStudySet(studySet)) {
    return { className: 'pill neutral', label: 'temporary' }
  }
  if (studySet.id) {
    return { className: 'pill ok', label: `saved r${studySet.revision}` }
  }
  return { className: 'pill neutral', label: 'empty' }
}

function AnalysisRoutePage({
  route,
  studySet,
  loadingScope,
  scopeError,
  scopeNotice,
  sessions,
  tracks,
  dataSource,
  statusMessage,
  connectionMode,
  onRefreshScope,
  onDismissScopeNotice,
}: {
  route: AnalysisRouteState
  studySet: StudySet | null
  loadingScope: boolean
  scopeError: string
  scopeNotice: AnalysisScopeNotice | null
  sessions: SessionRecord[]
  tracks: TrackRecord[]
  dataSource: LibraryDataSource
  statusMessage: string
  connectionMode: 'local-api' | 'fixture'
  onRefreshScope: () => void
  onDismissScopeNotice: () => void
}) {
  const viewTitle = route.viewId === 'simple-suspension' ? 'Simple Suspension Analysis' : route.viewId
  const [routeModal, setRouteModal] = useState<ModalState>(null)
  const [bookmarkRefreshToken, setBookmarkRefreshToken] = useState(0)

  return (
    <main className="app-shell analysis-route-shell">
      <header className="app-header analysis-route-header">
        <div>
          <p className="eyebrow">BODAQS Analysis</p>
          <h1>{viewTitle}</h1>
          <p className="analysis-route-subtitle">
            {studySet?.displayName || 'Analysis scope not loaded'}
            <span>{connectionMode === 'fixture' ? 'fixture data source' : statusMessage}</span>
          </p>
        </div>
      </header>

      {loadingScope ? (
        <section className="analysis-route-empty">
          <h2>Loading analysis scope</h2>
          <p>Loading saved Study Set {route.studySetId} from the Library API.</p>
        </section>
      ) : !studySet ? (
        <section className="analysis-route-empty">
          <h2>Analysis scope unavailable</h2>
          <p>
            {scopeError ||
              'This analysis tab could not find its Study Set scope. Open the analysis again from the Library Browser or Study Set Builder.'}
          </p>
        </section>
      ) : route.viewId === 'simple-suspension' ? (
        <section className="analysis-route-content">
          {scopeNotice && (
            <div className={`analysis-route-notice ${scopeNotice.kind}`}>
              <span>{scopeNotice.message}</span>
              <div className="analysis-route-notice-actions">
                {scopeNotice.refreshable && (
                  <button className="secondary-action compact" type="button" onClick={onRefreshScope}>
                    Refresh analysis
                  </button>
                )}
                <button className="secondary-action compact" type="button" onClick={onDismissScopeNotice}>
                  Dismiss
                </button>
              </div>
            </div>
          )}
          <SuspensionVisualization
            studySet={studySet}
            sessions={sessions}
            tracks={tracks}
            dataSource={dataSource}
            bookmarkRefreshToken={bookmarkRefreshToken}
            onInspectSignals={(sessionRef, window) => {
              const session = sessionByRef(sessionRef, sessions)
              if (session) {
                setRouteModal({ kind: 'signal-inspector', session, initialWindow: window })
              }
            }}
          />
        </section>
      ) : (
        <section className="analysis-route-empty">
          <h2>Analysis view not implemented</h2>
          <p>{route.viewId} is registered as a route, but this prototype does not have a renderer for it yet.</p>
        </section>
      )}
      {routeModal && (
        <Modal
          state={routeModal}
          libraries={[]}
          sessions={sessions}
          tracks={tracks}
          dataSource={dataSource}
          bookmarkRefreshToken={bookmarkRefreshToken}
          onClose={() => setRouteModal(null)}
          onOpenAnalysis={(viewId, nextStudySet) => {
            window.location.href = analysisRouteUrl(viewId, nextStudySet)
          }}
          onOpenSignalInspector={(session, initialWindow = null) =>
            setRouteModal({ kind: 'signal-inspector', session, initialWindow })
          }
          onSessionBookmarksChanged={() => setBookmarkRefreshToken((current) => current + 1)}
        />
      )}
    </main>
  )
}

function pendingActionLabel(action: PendingStudySetAction) {
  if (action.kind === 'load') {
    return 'load another Study Set'
  }
  if (action.kind === 'analyze-now') {
    return 'start Analyze now'
  }
  return 'clear the current Study Set'
}

function parseAnalysisRouteHash(): AnalysisRouteState | null {
  if (typeof window === 'undefined') {
    return null
  }
  const hash = window.location.hash
  if (!hash.startsWith('#/analysis/')) {
    return null
  }
  const hashBody = hash.slice(2)
  const [path, query = ''] = hashBody.split('?')
  const segments = path.split('/')
  const viewId = segments[0] === 'analysis' ? decodeURIComponent(segments[1] ?? '') : ''
  const params = new URLSearchParams(query)
  const scopeToken = params.get('scope')
  const studySetId = params.get('studySet')
  if (!viewId || (!scopeToken && !studySetId)) {
    return null
  }
  return { viewId, scopeToken, studySetId }
}

function browserTabTitle(route: AnalysisRouteState | null) {
  if (!route) {
    return 'BODAQS library'
  }
  if (route.viewId === 'simple-suspension') {
    return 'simple suspension analysis'
  }
  return route.viewId
}

function analysisRouteUrl(viewId: string, studySet: StudySet) {
  const baseUrl = `${window.location.origin}${window.location.pathname}${window.location.search}`
  const params = new URLSearchParams()
  if (studySet.id && studySet.saved) {
    params.set('studySet', studySet.id)
  } else {
    params.set('scope', persistAnalysisScope(studySet))
  }
  return `${baseUrl}#/analysis/${encodeURIComponent(viewId)}?${params.toString()}`
}

function persistAnalysisScope(studySet: StudySet) {
  const token = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  window.localStorage.setItem(`${ANALYSIS_SCOPE_STORAGE_PREFIX}${token}`, JSON.stringify(cloneStudySet(studySet)))
  pruneStoredAnalysisScopes()
  return token
}

function loadAnalysisScope(scopeToken: string): StudySet | null {
  if (!scopeToken) {
    return null
  }
  try {
    const raw = window.localStorage.getItem(`${ANALYSIS_SCOPE_STORAGE_PREFIX}${scopeToken}`)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as unknown
    return isStoredStudySet(parsed) ? cloneStudySet(parsed) : null
  } catch {
    return null
  }
}

function pruneStoredAnalysisScopes() {
  const keys = Object.keys(window.localStorage)
    .filter((key) => key.startsWith(ANALYSIS_SCOPE_STORAGE_PREFIX))
    .sort()
  const excess = keys.slice(0, Math.max(0, keys.length - 12))
  for (const key of excess) {
    window.localStorage.removeItem(key)
  }
}

function isStoredStudySet(value: unknown): value is StudySet {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }
  const candidate = value as Partial<StudySet>
  return (
    typeof candidate.displayName === 'string' &&
    Array.isArray(candidate.sessions) &&
    Array.isArray(candidate.groupings) &&
    Array.isArray(candidate.trackIds)
  )
}

async function fetchWorkbenchData(source: LibraryDataSource) {
  const [loadedLibraries, loadedSessions, loadedTracks, loadedStudySets, loadedSavedFilters] = await Promise.all([
    source.listLibraries(),
    source.listSessions(),
    source.listTracks(),
    source.listStudySets(),
    source.listSavedSessionFilters ? source.listSavedSessionFilters() : Promise.resolve(prototypeSavedSessionFilters),
  ])

  return {
    libraries: applySessionCounts(loadedLibraries, loadedSessions),
    sessions: loadedSessions,
    tracks: loadedTracks,
    studySets: loadedStudySets,
    savedFilters: loadedSavedFilters,
  }
}

function removeSessionFromStudySetValue(studySet: StudySet, refId: string, preserveSavedFlag: boolean) {
  return {
    ...studySet,
    saved: preserveSavedFlag ? studySet.saved : false,
    sessions: studySet.sessions.filter((session) => sessionRefId(session) !== refId),
    groupings: studySet.groupings
      .map((grouping) => ({
        ...grouping,
        sessionRefs: grouping.sessionRefs.filter((sessionRef) => sessionRef !== refId),
      }))
      .filter((grouping) => grouping.sessionRefs.length > 0),
  }
}

function applySessionCounts(libraries: LibraryRecord[], sessions: SessionRecord[]) {
  const sessionCounts = new Map<string, number>()
  for (const session of sessions) {
    sessionCounts.set(session.libraryId, (sessionCounts.get(session.libraryId) ?? 0) + 1)
  }
  return libraries.map((libraryItem) => ({
    ...libraryItem,
    sessionCount: sessionCounts.get(libraryItem.id) ?? libraryItem.sessionCount,
  }))
}

function studySetPathFromSession(session: SessionRecord, path: Array<[number, number]> = session.gps): StudySetMapSessionPath {
  return {
    id: candidateId(session),
    label: session.name,
    path,
  }
}

function hasMapPath(sessionPath: StudySetMapSessionPath) {
  return sessionPath.path.length > 0
}

function queuedGeoFilterState(spec: TrackpointCrossingSpec): GeoFilterQueryState {
  return {
    key: spec.key,
    label: trackpointFilterLabel(spec),
    status: 'queued',
    candidateSessionCount: 0,
    processedSessionCount: 0,
    matchedSessionCount: 0,
    matchedSessionIds: [],
    error: '',
  }
}

function geoFilterStateFromQuery(
  spec: TrackpointCrossingSpec,
  query: TrackpointMatchQueryRecord,
  matchedSessionIds: string[],
): GeoFilterQueryState {
  return {
    key: spec.key,
    label: trackpointFilterLabel(spec),
    status: query.status,
    candidateSessionCount: query.candidateSessionCount,
    processedSessionCount: query.processedSessionCount,
    matchedSessionCount: query.matchedSessionCount,
    matchedSessionIds,
    error: query.error,
  }
}

function trackpointFilterLabel(spec: TrackpointCrossingSpec) {
  const count = spec.trackpointIds.length
  const countLabel = count === 1 ? spec.trackpointIds[0] : `${count} trackpoints`
  return `${spec.trackId}: ${countLabel}`
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function withTrackMatches(tracks: TrackRecord[], matches: SessionTrackMatchRecord[]) {
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

function uniqueStrings(values: string[]) {
  return Array.from(new Set(values))
}

function loadPersistedVisibleColumns(): ColumnId[] {
  if (typeof window === 'undefined') {
    return defaultColumns
  }
  try {
    let raw = window.localStorage.getItem(SESSION_SELECTOR_COLUMNS_STORAGE_KEY)
    const usingLegacyLayout = !raw
    if (!raw) {
      raw = window.localStorage.getItem(LEGACY_SESSION_SELECTOR_COLUMNS_STORAGE_KEY)
    }
    if (!raw) {
      return defaultColumns
    }
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) {
      return defaultColumns
    }
    const columnIds = parsed.filter(isColumnId)
    return normalizeColumnSelection(usingLegacyLayout ? [...columnIds, ...infoActionColumns] : columnIds)
  } catch {
    return defaultColumns
  }
}

function persistVisibleColumns(columns: ColumnId[]) {
  if (typeof window === 'undefined') {
    return
  }
  try {
    window.localStorage.setItem(SESSION_SELECTOR_COLUMNS_STORAGE_KEY, JSON.stringify(columns))
  } catch {
    // Browser storage may be unavailable or full; column layout persistence is non-critical.
  }
}

function isColumnId(value: unknown): value is ColumnId {
  return typeof value === 'string' && value in columnLabels
}

export default App
