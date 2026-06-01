import { AlertTriangle, FileText, Info } from 'lucide-react'
import type { QcLevel, SessionInspectionTab, SessionRecord } from '../domain/types'
import { IconButton } from './Common'

type InfoTone = 'good' | 'warning' | 'alert'

export function SessionInfoButtons({
  session,
  onInspect,
}: {
  session: SessionRecord
  onInspect: (session: SessionRecord, tab: SessionInspectionTab) => void
}) {
  return (
    <>
      <IconButton
        label={`View note: ${noteStatusLabel(session.noteStatus)}`}
        onClick={() => onInspect(session, 'note')}
        icon={<FileText size={15} />}
        tone={noteTone(session.noteStatus)}
      />
      <IconButton
        label={`View QC: ${qcStatusLabel(session.qcLevel, session.qcAlerts.length)}`}
        onClick={() => onInspect(session, 'qc')}
        icon={<AlertTriangle size={15} />}
        tone={qcTone(session.qcLevel)}
      />
      <IconButton
        label="View metadata"
        onClick={() => onInspect(session, 'metadata')}
        icon={<Info size={15} />}
      />
    </>
  )
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
