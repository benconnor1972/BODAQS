import type { StudySet } from '../domain/types'

export type WorkbenchSyncMessage =
  | {
      type: 'study-set-updated'
      studySetId: string
      displayName: string
      revision?: number
      sourceId: string
      sentAt: string
    }
  | {
      type: 'study-set-deleted'
      studySetId: string
      displayName: string
      sourceId: string
      sentAt: string
    }
  | {
      type: 'session-deleted'
      sessionRefId: string
      sessionName: string
      sourceId: string
      sentAt: string
    }

const WORKBENCH_SYNC_CHANNEL = 'bodaqs-workbench-sync-v1'
const workbenchSyncSourceId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

export function subscribeWorkbenchSync(onMessage: (message: WorkbenchSyncMessage) => void) {
  if (typeof BroadcastChannel === 'undefined') {
    return () => {}
  }

  const channel = new BroadcastChannel(WORKBENCH_SYNC_CHANNEL)
  channel.onmessage = (event) => {
    const message = event.data as WorkbenchSyncMessage | null
    if (!message || message.sourceId === workbenchSyncSourceId) {
      return
    }
    onMessage(message)
  }

  return () => channel.close()
}

export function broadcastStudySetUpdated(studySet: StudySet) {
  if (!studySet.id) {
    return
  }
  postWorkbenchSync({
    type: 'study-set-updated',
    studySetId: studySet.id,
    displayName: studySet.displayName,
    revision: studySet.revision,
    sourceId: workbenchSyncSourceId,
    sentAt: new Date().toISOString(),
  })
}

export function broadcastStudySetDeleted(studySet: StudySet) {
  if (!studySet.id) {
    return
  }
  postWorkbenchSync({
    type: 'study-set-deleted',
    studySetId: studySet.id,
    displayName: studySet.displayName,
    sourceId: workbenchSyncSourceId,
    sentAt: new Date().toISOString(),
  })
}

export function broadcastSessionDeleted(sessionRefId: string, sessionName: string) {
  postWorkbenchSync({
    type: 'session-deleted',
    sessionRefId,
    sessionName,
    sourceId: workbenchSyncSourceId,
    sentAt: new Date().toISOString(),
  })
}

function postWorkbenchSync(message: WorkbenchSyncMessage) {
  if (typeof BroadcastChannel === 'undefined') {
    return
  }
  const channel = new BroadcastChannel(WORKBENCH_SYNC_CHANNEL)
  channel.postMessage(message)
  channel.close()
}

