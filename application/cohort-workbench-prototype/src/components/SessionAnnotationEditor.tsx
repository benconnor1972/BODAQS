import { useEffect, useState } from 'react'
import { Plus, Save, X } from 'lucide-react'
import { IconButton, InfoTip } from './Common'
import { TagTiles } from './TagTiles'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { SessionRecord, SessionUserAnnotationRecord } from '../domain/types'

export function SessionAnnotationEditor({ session, dataSource, canWrite, knownTags, onSaved, onClose }: {
  session: SessionRecord
  dataSource: LibraryDataSource
  canWrite: boolean
  knownTags: string[]
  onSaved: (record: SessionUserAnnotationRecord) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<SessionUserAnnotationRecord | null>(null)
  const [tagInput, setTagInput] = useState('')
  const [message, setMessage] = useState('Loading annotations...')
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    if (!dataSource.loadSessionUserAnnotations) return
    void dataSource.loadSessionUserAnnotations(session).then((record) => {
      if (cancelled) return
      const next = structuredClone(record)
      setDraft(next)
      setMessage('')
    }).catch((error: unknown) => {
      if (!cancelled) setMessage(error instanceof Error ? error.message : 'Could not load annotations.')
    })
    return () => { cancelled = true }
  }, [session, dataSource, reload])

  const writable = canWrite && Boolean(dataSource.saveSessionUserAnnotations)
  function addTag(tag: string) {
    const value = tag.trim().toLowerCase()
    if (!draft || !value) return
    if (value.length > 80 || [...value].some((char) => char.charCodeAt(0) < 32) || draft.tags.length >= 100) {
      setMessage('Use up to 100 tags, each with 1–80 characters and no control characters.')
      return
    }
    setDraft({ ...draft, tags: [...new Set([...draft.tags, value])].sort() })
    setTagInput('')
  }
  async function save() {
    if (!draft || !writable || !dataSource.saveSessionUserAnnotations) return
    if (tagInput.trim()) { setMessage('Add the typed tag before saving, or clear the tag input.'); return }
    setBusy(true)
    try {
      const saved = await dataSource.saveSessionUserAnnotations(draft)
      onSaved(saved)
      onClose()
    } catch (error) {
      setMessage(`${error instanceof Error ? error.message : 'Could not save annotations.'} Your edits are still here. Reload to use the latest saved version.`)
    } finally { setBusy(false) }
  }
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal note-editor-modal session-annotation-modal" role="dialog" aria-modal="true" aria-label="Session flags and tags" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-header"><h2 className="inline-heading">Flag and tag <InfoTip label="About flags and tags" text="User reports are kept alongside automatic GPS and QA results." /></h2><IconButton label="Close" onClick={onClose} icon={<X size={18} />} /></div>
        <div className="modal-content note-editor-content">
          <section className="note-editor-summary">
            <div><p className="modal-kicker">Session description</p><h3>{session.name}</h3><p>Session ID {session.sessionId}</p></div>
            <dl className="analysis-scope-summary note-editor-status-summary"><dt>Run</dt><dd>{session.runName}</dd><dt>Revision</dt><dd>{draft?.revision ?? '—'}</dd></dl>
          </section>
          {message && <p className="modal-status" role="status">{message}</p>}
          {!dataSource.loadSessionUserAnnotations && <p className="modal-status warning">Annotations are unavailable from this data source.</p>}
          {!writable && <p className="modal-status">Annotations are read-only.</p>}
          {draft && <form className="note-editor-form note-editor-form-full session-annotation-form" onSubmit={(event) => event.preventDefault()}>
            {(['gpsIssue', 'qaIssue'] as const).map((key) => {
              const issue = draft[key]
              if (!issue) return <p key={key}>Issue information is unavailable.</p>
              const label = key === 'gpsIssue' ? 'GPS issue' : 'QA issue'
              return <fieldset className="note-field-group" disabled={!writable || busy} key={key}>
                <legend>{label}</legend>
                <label className="session-annotation-checkbox"><input type="checkbox" checked={issue.flagged} onChange={(event) => setDraft({ ...draft, [key]: { ...issue, flagged: event.target.checked } })} /> Flag {label}</label>
                <label>{label} explanation (optional)<textarea maxLength={4000} value={issue.explanation} onChange={(event) => setDraft({ ...draft, [key]: { ...issue, explanation: event.target.value } })} /></label>
              </fieldset>
            })}
            <fieldset className="note-field-group wide-field" disabled={!writable || busy}>
            <legend>Tags</legend>
            <div className="session-tag-entry"><label>New tag<input aria-label="New tag" list="annotation-tag-suggestions" value={tagInput} onChange={(event) => setTagInput(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addTag(tagInput) } }} /></label><button className="secondary-action" type="button" onClick={() => addTag(tagInput)}><Plus size={14} />Add tag</button></div>
            <datalist id="annotation-tag-suggestions">{knownTags.map((tag) => <option key={tag} value={tag} />)}</datalist>
            <TagTiles tags={draft.tags} disabled={!writable || busy} onRemove={(tag) => setDraft({ ...draft, tags: draft.tags.filter((value) => value !== tag) })} />
            {draft.tags.length === 0 && <p className="empty-note">No tags yet.</p>}
            </fieldset>
          </form>}
        </div>
        <div className="modal-actions"><button className="secondary-action" type="button" disabled={busy} onClick={() => { setDraft(null); setMessage('Loading annotations...'); setReload((value) => value + 1) }}>Reload saved annotations</button><button className="primary-action" type="button" disabled={busy || !draft || !writable} onClick={() => void save()}><Save size={16} />{busy ? 'Saving...' : 'Save'}</button></div>
      </section>
    </div>
  )
}
