import type { SessionRecord, SessionUserAnnotationRecord } from './types'
import { sessionToStudyRef } from './studySets'

export function emptySessionAnnotations(session: SessionRecord): SessionUserAnnotationRecord {
  return { sessionRef: sessionToStudyRef(session), present: false, revision: 0, tags: [],
    gpsIssue: { flagged: false, explanation: '' }, qaIssue: { flagged: false, explanation: '' }, warnings: [] }
}
