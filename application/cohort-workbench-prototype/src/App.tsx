import { useEffect, useRef, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Columns3,
  Eye,
  FileText,
  FolderOpen,
  GitBranch,
  Library,
  Minus,
  Play,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import './App.css'
import { IconButton, PanelTitle, SummaryTile } from './components/Common'
import { FilterPanel } from './components/FilterPanel'
import { GeospatialWorkbench } from './components/GeospatialWorkbench'
import { GpsRoutePreview } from './components/GpsRoutePreview'
import { Modal } from './components/Modal'
import { SessionTable, type SessionSelectionGesture } from './components/SessionTable'
import { StudySessionTable } from './components/StudySessionTable'
import { UnsavedChangesDialog } from './components/UnsavedChangesDialog'
import { FixtureLibraryDataSource } from './data/FixtureLibraryDataSource'
import { LocalApiDataSource } from './data/LocalApiDataSource'
import type { LibraryDataSource } from './data/LibraryDataSource'
import {
  columnGroups,
  columnLabels,
  columnPresets,
  defaultColumns,
  lockedColumns,
  matchesSearch,
  normalizeColumnSelection,
  sortSessions,
} from './domain/sessionCatalog'
import { applySavedSessionFilters, prototypeSavedSessionFilters } from './domain/sessionFilters'
import {
  candidateId,
  cloneStudySet,
  emptyStudySet,
  groupingColors,
  hasStudySetContent,
  isTemporaryStudySet,
  sessionRefId,
  sessionToStudyRef,
  slugify,
  studySetsEqual,
  uniqueId,
} from './domain/studySets'
import type {
  ColumnId,
  LibraryRecord,
  ModalState,
  SessionTrackMatchRecord,
  SessionRecord,
  SortDirection,
  StudyGrouping,
  StudySet,
  TrackRecord,
} from './domain/types'

type PendingStudySetAction =
  | { kind: 'load'; studySet: StudySet }
  | { kind: 'analyze-now'; session: SessionRecord }
  | { kind: 'clear' }

function App() {
  const [localDataSource] = useState(() => new LocalApiDataSource())
  const [fixtureDataSource] = useState(() => new FixtureLibraryDataSource())
  const [activeDataSource, setActiveDataSource] = useState<LibraryDataSource>(localDataSource)
  const columnMenuRef = useRef<HTMLDivElement>(null)
  const [libraries, setLibraries] = useState<LibraryRecord[]>([])
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [tracks, setTracks] = useState<TrackRecord[]>([])
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState<ColumnId[]>(defaultColumns)
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
  const [currentStudySet, setCurrentStudySet] = useState<StudySet>(() => emptyStudySet())
  const [lastCommittedStudySet, setLastCommittedStudySet] = useState<StudySet>(() => emptyStudySet())
  const [groupingName, setGroupingName] = useState('')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [librarySelectorCollapsed, setLibrarySelectorCollapsed] = useState(true)
  const [sessionSelectorCollapsed, setSessionSelectorCollapsed] = useState(false)
  const [gpsLocationCollapsed, setGpsLocationCollapsed] = useState(false)
  const [filtersCollapsed, setFiltersCollapsed] = useState(false)
  const [geospatialCollapsed, setGeospatialCollapsed] = useState(false)
  const [activeSavedFilterIds, setActiveSavedFilterIds] = useState<string[]>([])
  const [columnMenuOpen, setColumnMenuOpen] = useState(false)
  const [modal, setModal] = useState<ModalState>(null)
  const [pendingStudySetAction, setPendingStudySetAction] = useState<PendingStudySetAction | null>(null)
  const [libraryRootInput, setLibraryRootInput] = useState('')
  const [connectionMode, setConnectionMode] = useState<'local-api' | 'fixture'>('local-api')
  const [isChangingLibraryRoot, setIsChangingLibraryRoot] = useState(false)
  const [statusMessage, setStatusMessage] = useState('Connecting to configured BODAQS Library API...')

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

  const selectedLibraries = libraries.filter((libraryItem) =>
    selectedLibraryIds.includes(libraryItem.id),
  )
  const libraryScopedSessions = sessions.filter((session) => selectedLibraryIds.includes(session.libraryId))
  const savedSessionFilters = prototypeSavedSessionFilters
  const activeSavedSessionFilters = savedSessionFilters.filter((filter) => activeSavedFilterIds.includes(filter.id))
  const savedFilteredSessions = applySavedSessionFilters(libraryScopedSessions, activeSavedSessionFilters)
  const tableFilteredSessions = savedFilteredSessions
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
      setGroupingName('')
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatusMessage(`Could not select library root through ${localDataSource.baseUrl}: ${message}`)
    } finally {
      setIsChangingLibraryRoot(false)
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
    setModal({ kind: 'study-set', studySet: temporarySet, mode: 'analyze' })
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

  function addSelectedTracksToStudySet() {
    setCurrentStudySet((current) => ({
      ...current,
      saved: false,
      trackIds: Array.from(new Set([...current.trackIds, ...selectedTrackIds])),
    }))
    setStatusMessage(`${selectedTrackIds.length} selected track(s) attached to the Study Set.`)
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
            action={
              <IconButton
                label="Collapse Library Browser"
                onClick={() => setLeftCollapsed(true)}
                icon={<ChevronLeft size={18} />}
              />
            }
          />

          <section className={`module collapsible-module${librarySelectorCollapsed ? ' collapsed' : ''}`}>
            <div className="module-header">
              <h2>Library Selector</h2>
              <div className="module-header-actions">
                <span className="subtle">{selectedLibraries.length} active</span>
                <IconButton
                  label={librarySelectorCollapsed ? 'Expand Library Selector' : 'Collapse Library Selector'}
                  onClick={() => setLibrarySelectorCollapsed((current) => !current)}
                  icon={librarySelectorCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                />
              </div>
            </div>
            {librarySelectorCollapsed ? (
              <div className="collapsed-root-summary">
                <span>Library root</span>
                <strong>{libraryRootInput || 'No library root selected'}</strong>
              </div>
            ) : (
              <>
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
              <h2>Session Selector</h2>
              <div className="module-header-actions">
                <span className="subtle">{visibleSessions.length} shown</span>
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
                <div className="session-filter-status">
                  <span className="filter-status-label">Saved filters</span>
                  {activeSavedSessionFilters.length === 0 ? (
                    <span className="pill neutral">none</span>
                  ) : (
                    activeSavedSessionFilters.map((filter) => (
                      <button
                        className="filter-chip compact-session-filter-chip"
                        key={filter.id}
                        onClick={() => toggleSavedSessionFilter(filter.id)}
                        type="button"
                      >
                        {filter.displayName}
                        <X size={12} />
                      </button>
                    ))
                  )}
                  <span className="filter-status-label">Table filters</span>
                  <span className="pill neutral">none</span>
                </div>
                <SessionTable
                  sessions={visibleSessions}
                  libraries={libraries}
                  visibleColumns={visibleColumns}
                  selectedIds={selectedCandidateIds}
                  primaryId={primaryCandidateId}
                  sortColumn={sortColumn}
                  sortDirection={sortDirection}
                  onSort={setSort}
                  onSelect={selectCandidate}
                  onInspect={(session, tab) => setModal({ kind: 'session', session, tab })}
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
                  <h2>GPS Location</h2>
                  <div className="module-header-actions">
                    <span className="subtle">{primarySession ? primarySession.name : 'No primary session'}</span>
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
                  <h2>Filters</h2>
                  <div className="module-header-actions">
                    <span className={activeSavedSessionFilters.length ? 'pill ok' : 'pill neutral'}>
                      {activeSavedSessionFilters.length ? `${activeSavedSessionFilters.length} saved active` : 'saved stack'}
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
                    totalCount={libraryScopedSessions.length}
                    savedFilteredCount={savedFilteredSessions.length}
                    visibleCount={visibleSessions.length}
                    onToggleSavedFilter={toggleSavedSessionFilter}
                    onClearSavedFilters={clearSavedSessionFilters}
                  />
                )}
              </section>

              <section className={`module collapsible-module${geospatialCollapsed ? ' collapsed' : ''}`}>
                <div className="module-header">
                  <h2>Geospatial Workbench</h2>
                  <div className="module-header-actions">
                    <span className="pill neutral">v0 endpoints</span>
                    <IconButton
                      label={geospatialCollapsed ? 'Expand Geospatial Workbench' : 'Collapse Geospatial Workbench'}
                      onClick={() => setGeospatialCollapsed((current) => !current)}
                      icon={geospatialCollapsed ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
                    />
                  </div>
                </div>
                {!geospatialCollapsed && (
                  <GeospatialWorkbench
                    primarySession={primarySession}
                    currentStudySet={currentStudySet}
                    sessions={sessions}
                    tracks={tracks}
                    selectedTrackIds={selectedTrackIds}
                    currentStudyTracks={currentStudyTracks}
                    dataSource={activeDataSource}
                    onToggleTrack={toggleTrack}
                    onAttachSelectedTracks={addSelectedTracksToStudySet}
                    onInspectTrack={(track) => setModal({ kind: 'track', track })}
                    onTrackSaved={upsertTrack}
                    onTrackDeleted={deleteTrackFromWorkbench}
                  />
                )}
              </section>
            </div>
          </section>
        </aside>

        {leftCollapsed && (
          <button className="rail rail-left" onClick={() => setLeftCollapsed(false)}>
            <ChevronRight size={18} />
            Library Browser
          </button>
        )}

        <aside className="panel study-panel" aria-label="Study Set Builder">
          <PanelTitle
            icon={<BookOpen size={18} />}
            title="Study Set Builder"
            action={
              <IconButton
                label="Collapse Study Set Builder"
                onClick={() => setRightCollapsed(true)}
                icon={<ChevronRight size={18} />}
              />
            }
          />

          <section className="module current-study-set">
            <div className="module-header">
              <h2>Current Study Set</h2>
              <span className={currentStudySetStatus.className}>{currentStudySetStatus.label}</span>
            </div>

            <div className="study-name-row">
              <label>
                Study Set name
                <input
                  value={currentStudySet.displayName}
                  onChange={(event) => updateStudySetName(event.target.value)}
                  placeholder="Name this Study Set"
                />
              </label>
              <button
                className="primary-action"
                disabled={!canSaveCurrentStudySet}
                onClick={() => void saveCurrentStudySet()}
              >
                <Save size={17} />
                Save
              </button>
              <button className="danger-action" disabled={!currentStudySetHasContent} onClick={requestClearStudySet}>
                <Trash2 size={17} />
                Clear
              </button>
              <button
                className="secondary-action"
                onClick={() => setModal({ kind: 'study-set', studySet: currentStudySet, mode: 'analyze' })}
              >
                <BarChart3 size={17} />
                Analyze
              </button>
            </div>

            <div className="study-summary-grid">
              <SummaryTile label="Sessions" value={currentStudySet.sessions.length} />
              <SummaryTile label="Groupings" value={currentStudySet.groupings.length} />
              <SummaryTile label="Tracks" value={currentStudySet.trackIds.length} />
              <SummaryTile
                label="Libraries"
                value={new Set(currentStudySet.sessions.map((item) => item.libraryId)).size}
              />
            </div>

            <section className="study-section">
              <div className="subsection-header">
                <h3>Sessions</h3>
                <span className="subtle">Sessions can appear in multiple groupings.</span>
              </div>
              <StudySessionTable
                studySet={currentStudySet}
                libraries={libraries}
                sessions={sessions}
                visibleColumns={visibleColumns}
                selectedStudySessionIds={selectedStudySessionIds}
                onSelect={selectStudySession}
                onRemove={removeStudySession}
                onInspect={(session, tab) => setModal({ kind: 'session', session, tab })}
              />
              <div className="grouping-editor">
                <label>
                  New grouping
                  <input
                    value={groupingName}
                    onChange={(event) => setGroupingName(event.target.value)}
                    placeholder="Short name"
                  />
                </label>
                <button className="secondary-action" onClick={createGrouping}>
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
                <h3>Tracks</h3>
                <span className="subtle">Attached root-level tracks for this Study Set.</span>
              </div>
              <table className="tracks-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Trackpoints</th>
                    <th>Distance</th>
                    <th>Controls</th>
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
                      <td>
                        <IconButton
                          label="Inspect Track"
                          onClick={() => setModal({ kind: 'track', track })}
                          icon={<Eye size={15} />}
                        />
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

          <section className="module saved-study-sets">
            <div className="module-header">
              <h2>Saved Study Sets</h2>
              <span className="subtle">{savedStudySets.length} saved</span>
            </div>
            <table className="saved-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Sessions</th>
                  <th>Tracks</th>
                  <th>Groups</th>
                  <th>Controls</th>
                </tr>
              </thead>
              <tbody>
                {savedStudySets.map((studySet) => (
                  <tr key={studySet.id ?? studySet.displayName}>
                    <td>{studySet.displayName}</td>
                    <td>{studySet.sessions.length}</td>
                    <td>{studySet.trackIds.length}</td>
                    <td>{studySet.groupings.length}</td>
                    <td>
                      <IconButton
                        label="Analyze Study Set"
                        onClick={() => setModal({ kind: 'study-set', studySet, mode: 'analyze' })}
                        icon={<Play size={15} />}
                      />
                      <IconButton
                        label="View Study Set"
                        onClick={() => setModal({ kind: 'study-set', studySet, mode: 'view' })}
                        icon={<Eye size={15} />}
                      />
                      <IconButton
                        label="Load Study Set"
                        onClick={() => requestLoadStudySet(studySet)}
                        icon={<FileText size={15} />}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </aside>

        {rightCollapsed && (
          <button className="rail rail-right" onClick={() => setRightCollapsed(false)}>
            Study Set Builder
            <ChevronLeft size={18} />
          </button>
        )}
      </section>

      {modal && (
        <Modal
          state={modal}
          libraries={libraries}
          sessions={sessions}
          tracks={tracks}
          dataSource={activeDataSource}
          onClose={() => setModal(null)}
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

function pendingActionLabel(action: PendingStudySetAction) {
  if (action.kind === 'load') {
    return 'load another Study Set'
  }
  if (action.kind === 'analyze-now') {
    return 'start Analyze now'
  }
  return 'clear the current Study Set'
}

async function fetchWorkbenchData(source: LibraryDataSource) {
  const [loadedLibraries, loadedSessions, loadedTracks, loadedStudySets] = await Promise.all([
    source.listLibraries(),
    source.listSessions(),
    source.listTracks(),
    source.listStudySets(),
  ])

  return {
    libraries: applySessionCounts(loadedLibraries, loadedSessions),
    sessions: loadedSessions,
    tracks: loadedTracks,
    studySets: loadedStudySets,
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

export default App
