import { cloneStudySet, slugify, uniqueId } from '../domain/studySets'
import type { SessionRecord, StudySet, TrackRecord } from '../domain/types'
import {
  fixtureLibraries,
  fixtureSavedStudySets,
  fixtureSessions,
  fixtureTracks,
} from './fixtures'
import type { LibraryDataSource } from './LibraryDataSource'

export class FixtureLibraryDataSource implements LibraryDataSource {
  private savedStudySets = fixtureSavedStudySets.map(cloneStudySet)

  async listLibraries() {
    return fixtureLibraries.map((libraryItem) => ({ ...libraryItem }))
  }

  async listSessions() {
    return fixtureSessions.map(cloneSession)
  }

  async listTracks() {
    return fixtureTracks.map(cloneTrack)
  }

  async listStudySets() {
    return this.savedStudySets.map(cloneStudySet)
  }

  async saveStudySet(studySet: StudySet) {
    const displayName = studySet.displayName.trim()
    const existingIds = this.savedStudySets
      .map((savedStudySet) => savedStudySet.id)
      .filter((id): id is string => Boolean(id))
    const nextId = studySet.id ?? uniqueId(slugify(displayName), existingIds)
    const previous = this.savedStudySets.find((savedStudySet) => savedStudySet.id === nextId)
    const saved: StudySet = {
      ...cloneStudySet(studySet),
      id: nextId,
      displayName,
      revision: previous ? previous.revision + 1 : 1,
      saved: true,
      provenance: studySet.provenance || 'Created in the Library Browser prototype',
    }
    const exists = this.savedStudySets.some((savedStudySet) => savedStudySet.id === nextId)
    this.savedStudySets = exists
      ? this.savedStudySets.map((savedStudySet) => (savedStudySet.id === nextId ? saved : savedStudySet))
      : [...this.savedStudySets, saved]
    return cloneStudySet(saved)
  }
}

function cloneSession(session: SessionRecord): SessionRecord {
  return {
    ...session,
    qcAlerts: [...session.qcAlerts],
    signals: [...session.signals],
    gps: session.gps.map(([x, y]) => [x, y]),
  }
}

function cloneTrack(track: TrackRecord): TrackRecord {
  return {
    ...track,
    points: track.points.map(([x, y]) => [x, y]),
  }
}
