import { Save, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionToStudyRef } from '../domain/studySets'
import type {
  SessionNoteFieldDef,
  SessionNoteRecord,
  SessionNoteValue,
  SessionRecord,
} from '../domain/types'
import { IconButton } from './Common'
import { NoteBadge } from './StatusBadges'

type NoteDraft = {
  title: string
  values: Record<string, SessionNoteValue>
  customValues: Record<string, SessionNoteValue>
  freeTextNotes: string
  draft: boolean
}

type NoteFieldRow = {
  field: SessionNoteFieldDef
  source: 'values' | 'customValues'
}

const SECTION_ORDER = ['overview', 'bike', 'front', 'rear', 'notes', 'custom']

export function SessionNoteEditorModal({
  session,
  dataSource,
  onClose,
  onSaved,
}: {
  session: SessionRecord
  dataSource: LibraryDataSource
  onClose: () => void
  onSaved: (session: SessionRecord) => void
}) {
  const [note, setNote] = useState<SessionNoteRecord | null>(null)
  const [draft, setDraft] = useState<NoteDraft>(() => draftFromNote(sessionNoteFromSession(session)))
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const canSave = Boolean(note && dataSource.saveSessionNote && !loading && !saving)
  const groupedFields = note ? groupedNoteFields(note) : []

  useEffect(() => {
    let cancelled = false

    async function loadNote() {
      setLoading(true)
      setError('')
      setMessage('')
      try {
        const loaded = dataSource.loadSessionNote
          ? await dataSource.loadSessionNote(session)
          : sessionNoteFromSession(session)
        if (cancelled) {
          return
        }
        setNote(loaded)
        setDraft(draftFromNote(loaded))
      } catch (loadError) {
        if (cancelled) {
          return
        }
        const fallback = sessionNoteFromSession(session)
        setNote(fallback)
        setDraft(draftFromNote(fallback))
        setError(`Could not load note from the Library API: ${errorMessage(loadError)}`)
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadNote()
    return () => {
      cancelled = true
    }
  }, [dataSource, session])

  async function saveNote() {
    if (!note || !dataSource.saveSessionNote) {
      setError('This data source does not support note saves.')
      return
    }
    setSaving(true)
    setError('')
    setMessage('')
    try {
      const nextNote: SessionNoteRecord = {
        ...note,
        title: draft.title.trim() || 'Session note',
        values: draft.values,
        customValues: draft.customValues,
        freeTextNotes: draft.freeTextNotes,
        draft: draft.draft,
      }
      const saved = await dataSource.saveSessionNote(nextNote)
      setNote(saved)
      setDraft(draftFromNote(saved))
      onSaved(sessionFromSavedNote(session, saved))
      setMessage('Note saved.')
    } catch (saveError) {
      setError(`Could not save note: ${errorMessage(saveError)}`)
    } finally {
      setSaving(false)
    }
  }

  function setFieldValue(source: NoteFieldRow['source'], fieldId: string, value: SessionNoteValue) {
    setDraft((current) => ({
      ...current,
      [source]: {
        ...current[source],
        [fieldId]: value,
      },
    }))
  }

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="modal note-editor-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`View/edit note for ${session.name}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2>View/edit note</h2>
            <p className="modal-kicker">{session.name}</p>
          </div>
          <IconButton label="Close" onClick={onClose} icon={<X size={18} />} />
        </div>

        <div className="modal-content note-editor-content">
          <section className="note-editor-summary">
            <dl className="detail-list compact-detail-list">
              <dt>Status</dt>
              <dd>
                <NoteBadge status={draft.draft ? 'draft' : note?.present ? 'edited' : session.noteStatus} />
              </dd>
              <dt>Run</dt>
              <dd>{session.runName}</dd>
              <dt>Session ID</dt>
              <dd>{session.sessionId}</dd>
              <dt>Template</dt>
              <dd>{note?.templateId ? `${note.templateId} ${note.templateVersion}` : 'not set'}</dd>
            </dl>
          </section>

          {loading ? (
            <p className="modal-status">Loading note...</p>
          ) : (
            <form className="note-editor-form note-editor-form-full" onSubmit={(event) => event.preventDefault()}>
              <label className="wide-field">
                Title
                <input
                  value={draft.title}
                  onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
                />
              </label>

              <label>
                Status
                <select
                  value={draft.draft ? 'draft' : 'reviewed'}
                  onChange={(event) => setDraft((current) => ({ ...current, draft: event.target.value === 'draft' }))}
                >
                  <option value="draft">Draft</option>
                  <option value="reviewed">Reviewed / edited</option>
                </select>
              </label>

              {note?.templateStatus === 'missing' && (
                <p className="modal-status warning wide-field">
                  Template metadata could not be resolved. Showing stored note fields with fallback labels.
                  {note.templateError ? ` ${note.templateError}` : ''}
                </p>
              )}

              <div className="note-field-groups wide-field">
                {groupedFields.length === 0 && (
                  <p className="empty-note">This note does not contain any structured fields yet.</p>
                )}
                {groupedFields.map((group) => (
                  <fieldset className="note-field-group" key={group.section}>
                    <legend>{group.section}</legend>
                    <div className="note-field-grid">
                      {group.rows.map((row) => (
                        <NoteFieldEditor
                          field={row.field}
                          value={draft[row.source][row.field.fieldId] ?? null}
                          key={`${row.source}:${row.field.fieldId}`}
                          onChange={(value) => setFieldValue(row.source, row.field.fieldId, value)}
                        />
                      ))}
                    </div>
                  </fieldset>
                ))}
              </div>

              <label className="wide-field">
                Free text notes
                <textarea
                  value={draft.freeTextNotes}
                  onChange={(event) => setDraft((current) => ({ ...current, freeTextNotes: event.target.value }))}
                  placeholder="Setup notes, conditions, observations..."
                />
              </label>
            </form>
          )}

          {note && (
            <p className="note-editor-timestamp">
              Created {note.createdAtUtc || 'unknown'} - Updated {note.updatedAtUtc || 'unknown'}
            </p>
          )}
          {message && <p className="modal-status">{message}</p>}
          {error && <p className="modal-status warning">{error}</p>}
        </div>

        <div className="modal-actions">
          <button className="secondary-action" onClick={onClose} type="button">
            Close
          </button>
          <button className="primary-action" disabled={!canSave} onClick={() => void saveNote()} type="button">
            <Save size={16} />
            {saving ? 'Saving...' : 'Save note'}
          </button>
        </div>
      </section>
    </div>
  )
}

function NoteFieldEditor({
  field,
  value,
  onChange,
}: {
  field: SessionNoteFieldDef
  value: SessionNoteValue
  onChange: (value: SessionNoteValue) => void
}) {
  const label = `${field.label}${field.unit ? ` [${field.unit}]` : ''}`
  const numericFieldType = field.fieldType === 'int' ? 'int' : 'float'

  return (
    <label className={field.fieldType === 'text' ? 'wide-field note-field-row' : 'note-field-row'}>
      <span>
        {label}
        {field.required ? <em> required</em> : null}
      </span>
      {field.fieldType === 'bool' ? (
        <span className="note-bool-control">
          <input
            checked={value === true}
            onChange={(event) => onChange(event.target.checked)}
            type="checkbox"
          />
          Yes
        </span>
      ) : field.fieldType === 'enum' ? (
        <select value={noteValueText(value)} onChange={(event) => onChange(event.target.value || null)}>
          <option value="">Not set</option>
          {field.enumOptions.map((option) => (
            <option value={option} key={option}>
              {option}
            </option>
          ))}
        </select>
      ) : field.fieldType === 'multi_enum' ? (
        <span className="enum-picker note-enum-picker">
          {field.enumOptions.map((option) => {
            const values = Array.isArray(value) ? value : []
            return (
              <label className="mini-check" key={option}>
                <input
                  checked={values.includes(option)}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...values, option]
                      : values.filter((item) => item !== option)
                    onChange(next)
                  }}
                  type="checkbox"
                />
                {option}
              </label>
            )
          })}
        </span>
      ) : field.fieldType === 'text' ? (
        <textarea value={noteValueText(value)} onChange={(event) => onChange(event.target.value)} />
      ) : field.fieldType === 'int' || field.fieldType === 'float' ? (
        <input
          inputMode="decimal"
          value={noteValueText(value)}
          onChange={(event) => onChange(numberNoteValue(event.target.value, numericFieldType))}
        />
      ) : (
        <input
          value={noteValueText(value)}
          onChange={(event) => onChange(event.target.value)}
          type={field.fieldType === 'date' ? 'date' : 'text'}
        />
      )}
      {field.helpText ? <small>{field.helpText}</small> : null}
    </label>
  )
}

function sessionNoteFromSession(session: SessionRecord): SessionNoteRecord {
  const now = new Date().toISOString()
  return {
    sessionRef: sessionToStudyRef(session),
    present: session.noteStatus !== 'missing',
    title: 'Session note',
    templateId: 'web_session_note',
    templateVersion: '1.0',
    templateStatus: 'missing',
    templateError: '',
    fields: [],
    customFieldSection: 'Custom',
    values: {
      bike: session.bike,
      rider: session.rider,
    },
    customValues: {},
    freeTextNotes: '',
    draft: session.noteStatus !== 'edited',
    createdAtUtc: now,
    updatedAtUtc: now,
  }
}

function draftFromNote(note: SessionNoteRecord): NoteDraft {
  return {
    title: note.title,
    values: { ...note.values },
    customValues: { ...note.customValues },
    freeTextNotes: note.freeTextNotes,
    draft: note.draft,
  }
}

function sessionFromSavedNote(session: SessionRecord, note: SessionNoteRecord): SessionRecord {
  return {
    ...session,
    bike: noteValueText(note.values.bike),
    rider: noteValueText(note.values.rider),
    noteStatus: note.draft ? 'draft' : 'edited',
  }
}

function groupedNoteFields(note: SessionNoteRecord) {
  const templateFieldsById = new Map(note.fields.map((field) => [field.fieldId, field]))
  const rows: NoteFieldRow[] = [
    ...Object.keys(note.values).map((fieldId) => ({
      field: templateFieldsById.get(fieldId) ?? fallbackField(fieldId, 'Other'),
      source: 'values' as const,
    })),
    ...Object.keys(note.customValues).map((fieldId) => ({
      field: fallbackField(fieldId, note.customFieldSection || 'Custom'),
      source: 'customValues' as const,
    })),
  ]
  const groups = new Map<string, NoteFieldRow[]>()
  for (const row of rows) {
    const section = row.field.section || 'Other'
    groups.set(section, [...(groups.get(section) ?? []), row])
  }
  return Array.from(groups.entries())
    .sort(([left], [right]) => sectionSortKey(left).localeCompare(sectionSortKey(right)))
    .map(([section, groupRows]) => ({ section, rows: groupRows }))
}

function fallbackField(fieldId: string, section: string): SessionNoteFieldDef {
  return {
    fieldId,
    label: humanizeFieldId(fieldId),
    fieldType: 'string',
    section,
    required: false,
    default: '',
    unit: '',
    helpText: '',
    enumOptions: [],
  }
}

function sectionSortKey(section: string) {
  const normalized = section.trim().toLowerCase()
  const index = SECTION_ORDER.indexOf(normalized)
  return `${index === -1 ? 99 : index}:${section}`
}

function humanizeFieldId(fieldId: string) {
  return fieldId
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (match) => match.toUpperCase())
}

function numberNoteValue(value: string, fieldType: 'int' | 'float'): SessionNoteValue {
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  const parsed = Number(trimmed)
  if (!Number.isFinite(parsed)) {
    return null
  }
  return fieldType === 'int' ? Math.trunc(parsed) : parsed
}

function noteValueText(value: SessionNoteValue | undefined) {
  if (typeof value === 'string') {
    return value
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (Array.isArray(value)) {
    return value.join(', ')
  }
  return ''
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
