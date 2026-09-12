import { Copy, Plus, Save, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { cloneScenario, emptyScenario, scenarioDefinitionJson, scenarioFromDefinitionJson, scratchScenario } from '../domain/scenarios'
import type { ScenarioRecord } from '../domain/types'
import {
  scenarioBuilderFromPredicate,
  scenarioPredicateFromBuilder,
  type ScenarioPredicateBuilderState,
} from '../domain/scenarioPredicateBuilder'
import { ScenarioPredicateBuilder } from './ScenarioPredicateBuilder'

type EditorMode = 'visual' | 'advanced'

export function ScenarioEditorModal({
  dataSource,
  canWrite,
  initialScenario = null,
  allowScratch = false,
  onApplyScratch,
  onClose,
  onSaved,
}: {
  dataSource: LibraryDataSource
  canWrite: boolean
  initialScenario?: ScenarioRecord | null
  allowScratch?: boolean
  onApplyScratch?: (scenario: ScenarioRecord) => void
  onClose: () => void
  onSaved?: (scenario: ScenarioRecord) => void
}) {
  const firstDraft = initialScenario ? cloneScenario(initialScenario) : emptyScenario()
  const [scenarios, setScenarios] = useState<ScenarioRecord[]>(initialScenario?.id ? [cloneScenario(initialScenario)] : [])
  const [selectedId, setSelectedId] = useState(initialScenario?.id ?? '')
  const [draft, setDraft] = useState(firstDraft)
  const [editorMode, setEditorMode] = useState<EditorMode>(() => scenarioBuilderFromPredicate(firstDraft.predicate) ? 'visual' : 'advanced')
  const [builder, setBuilder] = useState<ScenarioPredicateBuilderState>(() => scenarioBuilderFromPredicate(firstDraft.predicate) ?? fallbackBuilder())
  const [definitionText, setDefinitionText] = useState(() => scenarioDefinitionJson(firstDraft))
  const [status, setStatus] = useState(() => dataSource.listScenarios ? '' : 'The current data source does not provide saved Scenarios.')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!dataSource.listScenarios) {
      return
    }
    let cancelled = false
    void dataSource.listScenarios()
      .then((loaded) => {
        if (!cancelled) {
          setScenarios(sortScenarios(loaded))
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setStatus(`Could not load saved Scenarios: ${errorMessage(error)}`)
        }
      })
    return () => {
      cancelled = true
    }
  }, [dataSource])

  function loadScenario(scenario: ScenarioRecord) {
    const next = cloneScenario(scenario)
    const nextBuilder = scenarioBuilderFromPredicate(next.predicate)
    setSelectedId(next.id ?? '')
    setDraft(next)
    setEditorMode(nextBuilder ? 'visual' : 'advanced')
    setBuilder(nextBuilder ?? fallbackBuilder())
    setDefinitionText(scenarioDefinitionJson(next))
    setStatus(nextBuilder ? '' : 'This predicate uses features available through Advanced JSON.')
  }

  function startNew() {
    loadScenario(emptyScenario())
  }

  function parsedDraft(previous = draft) {
    if (editorMode === 'visual') {
      const next = { ...draft, predicate: scenarioPredicateFromBuilder(builder) }
      return scenarioFromDefinitionJson(scenarioDefinitionJson(next), {
        displayName: draft.displayName,
        description: draft.description,
        category: draft.category,
      }, previous)
    }
    return scenarioFromDefinitionJson(definitionText, {
      displayName: draft.displayName,
      description: draft.description,
      category: draft.category,
    }, previous)
  }

  function toggleEditorMode() {
    if (editorMode === 'visual') {
      try {
        const next = { ...draft, predicate: scenarioPredicateFromBuilder(builder) }
        setDraft(next)
        setDefinitionText(scenarioDefinitionJson(next))
        setEditorMode('advanced')
        setStatus('')
      } catch (error) {
        setStatus(`Scenario predicate is not valid: ${errorMessage(error)}`)
      }
      return
    }
    try {
      const parsed = scenarioFromDefinitionJson(definitionText, {
        displayName: draft.displayName || 'Untitled Scenario',
        description: draft.description,
        category: draft.category,
      }, draft)
      const nextBuilder = scenarioBuilderFromPredicate(parsed.predicate)
      if (!nextBuilder) {
        setStatus('This predicate uses nested groups, selectors or operators that the visual builder cannot represent.')
        return
      }
      setDraft({ ...parsed, displayName: draft.displayName })
      setBuilder(nextBuilder)
      setEditorMode('visual')
      setStatus('')
    } catch (error) {
      setStatus(`Scenario definition is not valid: ${errorMessage(error)}`)
    }
  }

  function applyScratch() {
    try {
      const next = scratchScenario(parsedDraft())
      onApplyScratch?.(next)
      onClose()
    } catch (error) {
      setStatus(`Scenario definition is not valid: ${errorMessage(error)}`)
    }
  }

  async function save(saveAs: boolean) {
    if (!canWrite || !dataSource.saveScenario) {
      return
    }
    let next: ScenarioRecord
    try {
      next = parsedDraft()
      if (saveAs) {
        next = scratchScenario(next)
      }
    } catch (error) {
      setStatus(`Scenario definition is not valid: ${errorMessage(error)}`)
      return
    }
    setBusy(true)
    try {
      const saved = await dataSource.saveScenario(next)
      setScenarios((current) => sortScenarios([...current.filter((item) => item.id !== saved.id), saved]))
      loadScenario(saved)
      setStatus(`Saved "${saved.displayName}" as revision ${saved.revision}.`)
      onSaved?.(saved)
    } catch (error) {
      setStatus(`Could not save Scenario: ${errorMessage(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const isPersisted = Boolean(draft.id && draft.revision)

  return (
    <div className="modal-backdrop" role="presentation">
      <section aria-label="Scenario editor" className="modal scenario-editor-modal" role="dialog" aria-modal="true">
        <div className="modal-header">
          <div>
            <p className="eyebrow">Scenario library</p>
            <h2>Create or edit Scenario</h2>
          </div>
          <button aria-label="Close Scenario editor" className="icon-button" onClick={onClose} type="button">
            <X size={16} />
          </button>
        </div>

        <div className="modal-content scenario-editor-content">
          <aside className="scenario-editor-list" aria-label="Saved Scenarios">
            <div className="filter-manager-list-header">
              <strong>{scenarios.length} saved</strong>
              <button className="ghost-action compact-filter-action" onClick={startNew} type="button">
                <Plus size={13} />
                New
              </button>
            </div>
            {scenarios.length === 0 ? (
              <p className="empty-note">No persisted Scenarios yet.</p>
            ) : scenarios.map((scenario) => (
              <button
                className={`filter-manager-list-item${scenario.id === selectedId ? ' selected' : ''}`}
                key={scenario.id}
                onClick={() => loadScenario(scenario)}
                type="button"
              >
                <strong>{scenario.displayName}</strong>
                <small>{scenario.category ? `${scenario.category} / ` : ''}r{scenario.revision}</small>
              </button>
            ))}
          </aside>

          <section className="scenario-editor-form" aria-label="Scenario definition">
            <div className="filter-manager-row two-columns">
              <label>
                Name
                <input placeholder="Steep and twisty" value={draft.displayName} onChange={(event) => setDraft((current) => ({ ...current, displayName: event.target.value }))} />
              </label>
              <label>
                Category
                <input value={draft.category} onChange={(event) => setDraft((current) => ({ ...current, category: event.target.value }))} />
              </label>
            </div>
            <label className="filter-manager-row">
              Description
              <input value={draft.description} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} />
            </label>
            {isPersisted && (
              <div className="scenario-editor-identity">
                <span>ID <strong>{draft.id}</strong></span>
                <span>Revision <strong>{draft.revision}</strong></span>
              </div>
            )}
            {editorMode === 'visual' ? (
              <ScenarioPredicateBuilder builder={builder} onChange={setBuilder} />
            ) : (
              <>
                <label className="filter-manager-row scenario-editor-json">
                  Advanced definition JSON
                  <textarea
                    className="filter-manager-textarea"
                    spellCheck={false}
                    value={definitionText}
                    onChange={(event) => setDefinitionText(event.target.value)}
                  />
                </label>
                <p className="scenario-editor-help">
                  JSON uses the canonical Scenario contract and includes Episode and eligibility policies. Identity and descriptive metadata are managed separately.
                </p>
              </>
            )}
            <div className="filter-builder-footer">
              <button className="ghost-action compact-filter-action" onClick={toggleEditorMode} type="button">
                {editorMode === 'visual' ? 'Advanced JSON' : 'Try visual builder'}
              </button>
            </div>
            {status && <p className="modal-status">{status}</p>}
            {!canWrite && <p className="modal-status warning">Saved Scenario changes are unavailable in read-only mode.</p>}
            <div className="dialog-actions">
              {allowScratch && (
                <button className="ghost-action" disabled={busy} onClick={applyScratch} type="button">
                  Apply scratch
                </button>
              )}
              <button className="ghost-action" disabled={!canWrite || !isPersisted || busy} onClick={() => void save(true)} type="button">
                <Copy size={14} />
                Save as
              </button>
              <button className="primary-action" disabled={!canWrite || busy} onClick={() => void save(false)} type="button">
                <Save size={14} />
                {isPersisted ? 'Save' : 'Save persisted'}
              </button>
            </div>
          </section>
        </div>
      </section>
    </div>
  )
}

function sortScenarios(scenarios: ScenarioRecord[]) {
  return [...scenarios].sort((left, right) => left.displayName.localeCompare(right.displayName, undefined, { sensitivity: 'base' }))
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

function fallbackBuilder(): ScenarioPredicateBuilderState {
  const predicate = emptyScenario().predicate
  const builder = scenarioBuilderFromPredicate(predicate)
  if (!builder) throw new Error('The default Scenario predicate must be supported by the visual builder.')
  return builder
}
