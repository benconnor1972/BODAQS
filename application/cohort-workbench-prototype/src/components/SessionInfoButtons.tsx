import { Activity, AlertTriangle, FileText, Info, MapPin, Trash2 } from 'lucide-react'
import { gpsQualityTone, gpsSummaryLine } from '../domain/geospatial'
import type { ColumnId, QcLevel, SessionInspectionTab, SessionRecord } from '../domain/types'
import { IconButton } from './Common'

type InfoTone = 'good' | 'warning' | 'alert'
export type SessionInfoAction = 'note' | 'qc' | 'gps' | 'signals' | 'metadata' | 'delete'
const defaultInfoActions: SessionInfoAction[] = ['note', 'qc', 'gps', 'signals', 'metadata']

export function SessionInfoButtons({
  session,
  onInspect,
  actions,
  showDelete = false,
  onDelete,
}: {
  session: SessionRecord
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
  actions?: SessionInfoAction[]
  showDelete?: boolean
  onDelete?: (session: SessionRecord) => void
}) {
  const activeActions = actions ?? (showDelete ? [...defaultInfoActions, 'delete'] : defaultInfoActions)

  return (
    <>
      {activeActions.map((action) => (
        <SessionInfoButton
          action={action}
          key={action}
          session={session}
          onInspect={onInspect}
          onDelete={onDelete}
        />
      ))}
    </>
  )
}

function SessionInfoButton({
  action,
  session,
  onInspect,
  onDelete,
}: {
  action: SessionInfoAction
  session: SessionRecord
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
  onDelete?: (session: SessionRecord) => void
}) {
  if (action === 'note') {
    return (
      <IconButton
        label={`View/edit note: ${noteStatusLabel(session.noteStatus)}`}
        onClick={() => onInspect(session, 'note')}
        icon={<FileText size={15} />}
        tone={noteTone(session.noteStatus)}
      />
    )
  }
  if (action === 'qc') {
    return (
      <IconButton
        label={`View QA: ${qcStatusLabel(session.qcLevel, session.qcAlerts.length)}`}
        onClick={() => onInspect(session, 'qc')}
        icon={<AlertTriangle size={15} />}
        tone={qcTone(session.qcLevel)}
      />
    )
  }
  if (action === 'gps') {
    return (
      <IconButton
        label={`View GPS: ${gpsSummaryLine(session.gpsSummary)}`}
        onClick={() => onInspect(session, 'gps')}
        icon={<MapPin size={15} />}
        tone={gpsQualityTone(session.gpsSummary.quality)}
      />
    )
  }
  if (action === 'signals') {
    return (
      <IconButton
        label="Inspect signals"
        onClick={() => onInspect(session, 'signals')}
        icon={<Activity size={15} />}
      />
    )
  }
  if (action === 'metadata') {
    return (
      <IconButton
        label="View metadata"
        onClick={() => onInspect(session, 'metadata')}
        icon={<Info size={15} />}
      />
    )
  }
  return <SessionDeleteButton session={session} onDelete={onDelete} />
}

export function SessionDeleteButton({
  session,
  onDelete,
}: {
  session: SessionRecord
  onDelete?: (session: SessionRecord) => void
}) {
  return (
    <IconButton
      label={onDelete ? 'Delete session' : 'Delete session unavailable until library API support is added'}
      onClick={onDelete ? () => onDelete(session) : undefined}
      icon={<Trash2 size={15} />}
      tone="alert"
      disabled={!onDelete}
    />
  )
}

export function sessionInfoActionForColumn(columnId: ColumnId): SessionInfoAction | null {
  switch (columnId) {
    case 'noteAction':
      return 'note'
    case 'qaAction':
      return 'qc'
    case 'gpsAction':
      return 'gps'
    case 'signalInspectorAction':
      return 'signals'
    case 'metadataAction':
      return 'metadata'
    default:
      return null
  }
}

function noteTone(status: SessionRecord['noteStatus']): InfoTone {
  if (status === 'edited') {
    return 'good'
  }
  if (status === 'draft') {
    return 'warning'
  }
  return 'alert'
}

function qcTone(level: QcLevel): InfoTone {
  if (level === 'ok') {
    return 'good'
  }
  if (level === 'warning') {
    return 'warning'
  }
  return 'alert'
}

function noteStatusLabel(status: SessionRecord['noteStatus']) {
  if (status === 'edited') {
    return 'edited'
  }
  if (status === 'draft') {
    return 'draft'
  }
  return 'missing'
}

function qcStatusLabel(level: QcLevel, alertCount: number) {
  if (level === 'ok') {
    return 'clear'
  }
  if (level === 'warning') {
    return `${alertCount} warning${alertCount === 1 ? '' : 's'}`
  }
  return `${alertCount} alert${alertCount === 1 ? '' : 's'}`
}
