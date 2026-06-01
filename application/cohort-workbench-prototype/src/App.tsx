import { useEffect, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Columns3,
  Eye,
  FileText,
  Filter,
  GitBranch,
  Library,
  Minus,
  Play,
  Plus,
  Save,
  Search,
  X,
} from 'lucide-react'
import './App.css'
import { IconButton, PanelTitle, SummaryTile } from './components/Common'
import { Modal } from './components/Modal'
import { RoutePreview } from './components/RoutePreview'
import { SessionTable } from './components/SessionTable'
import { StudySessionTable } from './components/StudySessionTable'
import { FixtureLibraryDataSource } from './data/FixtureLibraryDataSource'
import { columnLabels, defaultColumns, matchesSearch, sortSessions } from './domain/sessionCatalog'
import {
  candidateId,
  cloneStudySet,
  emptyStudySet,
  groupingColors,
  sessionRefId,
  sessionToStudyRef,
  slugify,
  uniqueId,
} from './domain/studySets'
import type {
  ColumnId,
  LibraryRecord,
  ModalState,
  SessionRecord,
  SortDirection,
  StudyGrouping,
  StudySet,
  TrackRecord,
} from './domain/types'

function App() {
  const [dataSource] = useState(() => new FixtureLibraryDataSource())
  const [libraries, setLibraries] = useState<LibraryRecord[]>([])
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [tracks, setTracks] = useState<TrackRecord[]>([])
  const [selectedLibraryIds, setSelectedLibraryIds] = useState<string[]>([])
  const [visibleColumns, setVisibleColumns] = useState<ColumnId[]>(defaultColumns)
  const [searchText, setSearchText] = useState('')
  const [sortColumn, setSortColumn] = useState<ColumnId>('date')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [selectedCandidateIds, setSelectedCandidateIds] = useState<string[]>([])
  const [primaryCandidateId, setPrimaryCandidateId] = useState<string | null>(null)
  const [selectedStudySessionIds, setSelectedStudySessionIds] = useState<string[]>([])
  const [selectedTrackIds, setSelectedTrackIds] = useState<string[]>([])
  const [savedStudySets, setSavedStudySets] = useState<StudySet[]>([])
  const [currentStudySet, setCurrentStudySet] = useState<StudySet>(emptyStudySet())
  const [groupingName, setGroupingName] = useState('')
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightCollapsed, setRightCollapsed] = useState(false)
  const [modal, setModal] = useState<ModalState>(null)
  const [statusMessage, setStatusMessage] = useState('Loading fixture-backed prototype data source...')

  useEffect(() => {
    let cancelled = false

    async function loadPrototypeData() {
      try {
        const [loadedLibraries, loadedSessions, loadedTracks, loadedStudySets] = await Promise.all([
          dataSource.listLibraries(),
          dataSource.listSessions(),
          dataSource.listTracks(),
          dataSource.listStudySets(),
        ])

        if (cancelled) {
          return
        }

        setLibraries(loadedLibraries)
        setSessions(loadedSessions)
        setTracks(loadedTracks)
        setSavedStudySets(loadedStudySets)
        setSelectedLibraryIds(loadedLibraries.map((libraryItem) => libraryItem.id))
        setStatusMessage('Fixture-backed prototype ready. Study Sets save to in-memory mock state.')
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        setStatusMessage(`Could not load prototype fixture data: ${message}`)
      }
    }

    void loadPrototypeData()
    return () => {
      cancelled = true
    }
  }, [dataSource])

  const selectedLibraries = libraries.filter((libraryItem) =>
    selectedLibraryIds.includes(libraryItem.id),
  )
  const visibleSessions = sortSessions(
    sessions.filter((session) => selectedLibraryIds.includes(session.libraryId)),
    sortColumn,
    sortDirection,
    libraries,
  ).filter((session) => matchesSearch(session, searchText, visibleColumns, libraries))
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

  function toggleColumn(columnId: ColumnId) {
    setVisibleColumns((current) => {
      if (current.includes(columnId)) {
        return current.length === 1 ? current : current.filter((id) => id !== columnId)
      }
      return [...current, columnId]
    })
  }

  function setSort(columnId: ColumnId) {
    if (sortColumn === columnId) {
      setSortDirection((current) => (current === 'asc' ? 'desc' : 'asc'))
      return
    }
    setSortColumn(columnId)
    setSortDirection('asc')
  }

  function toggleCandidate(session: SessionRecord) {
    const id = candidateId(session)
    setSelectedCandidateIds((current) => {
      if (current.includes(id)) {
        const next = current.filter((item) => item !== id)
        if (primaryCandidateId === id) {
          setPrimaryCandidateId(next[0] ?? null)
        }
        return next
      }
      if (!primaryCandidateId) {
        setPrimaryCandidateId(id)
      }
      return [...current, id]
    })
  }

  function selectSingleCandidate(session: SessionRecord) {
    const id = candidateId(session)
    setSelectedCandidateIds([id])
    setPrimaryCandidateId(id)
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
    const temporarySet: StudySet = {
      ...emptyStudySet(),
      displayName: `Analyze now: ${primarySession.name}`,
      sessions: [sessionToStudyRef(primarySession)],
      provenance: 'Temporary one-session Study Set created by Analyze now',
    }
    setCurrentStudySet(temporarySet)
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
  }

  function toggleStudySession(refId: string) {
    setSelectedStudySessionIds((current) => {
      if (current.includes(refId)) {
        return current.filter((id) => id !== refId)
      }
      return [...current, refId]
    })
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

  async function saveCurrentStudySet() {
    const displayName = currentStudySet.displayName.trim()
    if (!displayName) {
      setStatusMessage('Name the Study Set before saving.')
      return
    }
    if (currentStudySet.sessions.length === 0) {
      setStatusMessage('Add at least one session before saving a Study Set.')
      return
    }

    try {
      const saved = await dataSource.saveStudySet({
        ...currentStudySet,
        displayName,
      })
      setSavedStudySets(await dataSource.listStudySets())
      setCurrentStudySet(saved)
      setStatusMessage(`Saved "${saved.displayName}" at revision ${saved.revision}.`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      setStatusMessage(`Could not save Study Set: ${message}`)
    }
  }

  function loadStudySet(studySet: StudySet) {
    setCurrentStudySet(cloneStudySet(studySet))
    setSelectedStudySessionIds([])
    setStatusMessage(`Loaded "${studySet.displayName}" into the current Study Set editor.`)
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

          <section className="module">
            <div className="module-header">
              <h2>Library Selector</h2>
              <span className="subtle">{selectedLibraries.length} active</span>
            </div>
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
          </section>

          <section className="module session-selector">
            <div className="module-header">
              <h2>Session Selector</h2>
              <span className="subtle">{visibleSessions.length} shown</span>
            </div>
            <div className="toolbar">
              <label className="search-field">
                <Search size={16} />
                <input
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="Search visible fields"
                />
              </label>
              <details className="column-menu">
                <summary>
                  <Columns3 size={16} />
                  Columns
                </summary>
                <div className="column-popover">
                  {(Object.keys(columnLabels) as ColumnId[]).map((columnId) => (
                    <label className="check-row compact" key={columnId}>
                      <input
                        type="checkbox"
                        checked={visibleColumns.includes(columnId)}
                        onChange={() => toggleColumn(columnId)}
                      />
                      <span>{columnLabels[columnId]}</span>
                    </label>
                  ))}
                </div>
              </details>
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
              onToggle={toggleCandidate}
              onSelectSingle={selectSingleCandidate}
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
          </section>

          <section className="lower-grid">
            <section className="module map-module">
              <div className="module-header">
                <h2>GPS Location</h2>
                <span className="subtle">{primarySession ? primarySession.name : 'No primary session'}</span>
              </div>
              <RoutePreview
                primarySession={primarySession}
                selectedTracks={selectedTracks}
                currentTracks={currentStudyTracks}
              />
            </section>

            <section className="module support-stack">
              <div className="module-header">
                <h2>Filters</h2>
                <span className="pill neutral">reserved</span>
              </div>
              <div className="placeholder-list">
                <Filter size={18} />
                <p>Reusable filters will sit here after the catalog path is stable.</p>
              </div>

              <div className="module-header spaced">
                <h2>Track Manager</h2>
                <span className="subtle">{tracks.length} fixture tracks</span>
              </div>
              <div className="track-list">
                {tracks.map((track) => (
                  <label className="check-row compact track-row" key={track.id}>
                    <input
                      type="checkbox"
                      checked={selectedTrackIds.includes(track.id)}
                      onChange={() => toggleTrack(track.id)}
                    />
                    <span>
                      <strong>{track.name}</strong>
                      <small>
                        {track.pointCount} points, {track.distanceKm.toFixed(1)} km
                      </small>
                    </span>
                    <IconButton
                      label="Inspect Track"
                      onClick={() => setModal({ kind: 'track', track })}
                      icon={<Eye size={16} />}
                    />
                  </label>
                ))}
              </div>
              <div className="action-row tight">
                <button className="secondary-action" onClick={addSelectedTracksToStudySet}>
                  <Plus size={16} />
                  Attach track
                </button>
                <button className="ghost-action" disabled>
                  New track later
                </button>
              </div>
            </section>
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
              <span className={currentStudySet.saved ? 'pill ok' : 'pill neutral'}>
                {currentStudySet.saved ? `saved r${currentStudySet.revision}` : 'unsaved'}
              </span>
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
              <button className="primary-action" onClick={() => void saveCurrentStudySet()}>
                <Save size={17} />
                Save
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
                sessions={sessions}
                selectedStudySessionIds={selectedStudySessionIds}
                onToggle={toggleStudySession}
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
                <span className="subtle">Track authoring is reserved for a later prototype pass.</span>
              </div>
              <table className="tracks-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Points</th>
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
                      <td>{track.pointCount}</td>
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
                        onClick={() => loadStudySet(studySet)}
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

      {modal && <Modal state={modal} libraries={libraries} onClose={() => setModal(null)} />}
    </main>
  )
}

export default App
