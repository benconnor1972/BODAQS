import type { NoteStatus, SessionRecord, StudySessionRef, StudySet } from './types'

export const groupingColors = ['#2f7d6d', '#b66a2c', '#4d70a8', '#8a5a7b', '#6f7e2e']

export function candidateId(session: SessionRecord) {
  return `${session.libraryId}|||${session.sessionKey}`
}

export function sessionRefId(sessionRef: StudySessionRef) {
  return `${sessionRef.libraryId}|||${sessionRef.sessionKey}`
}

export function sessionToStudyRef(session: SessionRecord): StudySessionRef {
  return {
    libraryId: session.libraryId,
    sessionKey: session.sessionKey,
    runId: session.runId,
    sessionId: session.sessionId,
    label: session.name,
  }
}

export function sessionByRef(sessionRef: StudySessionRef, sessions: SessionRecord[]) {
  return sessions.find(
    (session) =>
      session.libraryId === sessionRef.libraryId &&
      session.runId === sessionRef.runId &&
      session.sessionId === sessionRef.sessionId,
  )
}

export function emptyStudySet(): StudySet {
  return {
    id: null,
    displayName: '',
    revision: 0,
    saved: false,
    sessions: [],
    groupings: [],
    trackIds: [],
    provenance: '',
  }
}

export function cloneStudySet(studySet: StudySet): StudySet {
  return {
    ...studySet,
    sessions: studySet.sessions.map((session) => ({ ...session })),
    groupings: studySet.groupings.map((grouping) => ({
      ...grouping,
      sessionRefs: [...grouping.sessionRefs],
    })),
    trackIds: [...studySet.trackIds],
  }
}

export function hasStudySetContent(studySet: StudySet) {
  return Boolean(
    studySet.id ||
      studySet.displayName.trim() ||
      studySet.sessions.length ||
      studySet.groupings.length ||
      studySet.trackIds.length ||
      studySet.provenance.trim(),
  )
}

export function isTemporaryStudySet(studySet: StudySet) {
  return !studySet.id && studySet.provenance.startsWith('Temporary one-session Study Set')
}

export function studySetsEqual(a: StudySet, b: StudySet) {
  return JSON.stringify(normalizeStudySetForComparison(a)) === JSON.stringify(normalizeStudySetForComparison(b))
}

function normalizeStudySetForComparison(studySet: StudySet) {
  return {
    id: studySet.id,
    displayName: studySet.displayName.trim(),
    revision: studySet.revision,
    sessions: studySet.sessions.map((session) => ({
      libraryId: session.libraryId,
      sessionKey: session.sessionKey,
      runId: session.runId,
      sessionId: session.sessionId,
      label: session.label,
    })),
    groupings: studySet.groupings.map((grouping) => ({
      id: grouping.id,
      name: grouping.name.trim(),
      color: grouping.color,
      sessionRefs: [...grouping.sessionRefs],
    })),
    trackIds: [...studySet.trackIds],
    provenance: studySet.provenance.trim(),
  }
}

export function noteSummary(status: NoteStatus) {
  if (status === 'edited') {
    return 'Reviewed setup note is available for filtering and display.'
  }
  if (status === 'draft') {
    return 'Draft note exists and should be reviewed outside this first prototype pass.'
  }
  return 'No session note has been attached yet.'
}

export function slugify(value: string) {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'study-set'
}

export function uniqueId(base: string, existingIds: string[]) {
  if (!existingIds.includes(base)) {
    return base
  }
  let index = 2
  while (existingIds.includes(`${base}-${index}`)) {
    index += 1
  }
  return `${base}-${index}`
}
