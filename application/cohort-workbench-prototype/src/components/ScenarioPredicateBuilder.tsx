import { Plus, X } from 'lucide-react'
import type { LibrarySignalCatalog } from '../data/LibraryDataSource'
import { ScenarioColumnPicker } from './ScenarioColumnPicker'
import { ScenarioMeaningPicker } from './ScenarioMeaningPicker'
import { InfoTip } from './Common'
import {
  MAX_SCENARIO_CRITERIA,
  defaultScenarioCondition,
  scenarioOperatorLabels,
  scenarioSeriesDefinitions,
  type ScenarioBuilderCondition,
  type ScenarioBuilderJoin,
  type ScenarioNumericOperator,
  type ScenarioPredicateBuilderState,
} from '../domain/scenarioPredicateBuilder'

export function ScenarioPredicateBuilder({
  builder,
  onChange,
  catalog,
}: {
  builder: ScenarioPredicateBuilderState
  onChange: (builder: ScenarioPredicateBuilderState) => void
  catalog?: LibrarySignalCatalog
}) {
  function updateCondition(editorId: string, updates: Partial<ScenarioBuilderCondition>) {
    onChange({
      ...builder,
      conditions: builder.conditions.map((condition) =>
        condition.editorId === editorId ? { ...condition, ...updates } : condition,
      ),
    })
  }

  function removeCondition(editorId: string) {
    const remaining = builder.conditions.filter((condition) => condition.editorId !== editorId)
    onChange({
      ...builder,
      conditions: remaining.length ? remaining : [defaultScenarioCondition(1)],
    })
  }

  function addCondition() {
    if (builder.conditions.length >= MAX_SCENARIO_CRITERIA) return
    onChange({
      ...builder,
      conditions: [...builder.conditions, defaultScenarioCondition(builder.conditions.length + 1)],
    })
  }

  return (
    <section className="visual-filter-builder scenario-predicate-builder" aria-label="Visual Scenario predicate builder">
      <div className="visual-filter-toolbar">
        <label>
          <span className="inline-heading">Match <InfoTip label="About scenario criteria" text="Up to four criteria. Advanced JSON supports categorical operators, nested groups and additional selector formats." /></span>
          <select
            aria-label="Match"
            value={builder.join}
            onChange={(event) => onChange({ ...builder, join: event.target.value as ScenarioBuilderJoin })}
          >
            <option value="and">All criteria</option>
            <option value="or">Any criterion</option>
          </select>
        </label>
        <button
          className="ghost-action compact-filter-action"
          disabled={builder.conditions.length >= MAX_SCENARIO_CRITERIA}
          onClick={addCondition}
          type="button"
        >
          <Plus size={13} />
          Criterion
        </button>
      </div>

      <div className="condition-stack">
        {builder.conditions.map((condition, index) => {
          const definition = definitionForCondition(condition)
          const recordedUnits = [...new Set((catalog?.signals ?? [])
            .filter((signal) => signal.streamName === condition.streamName && signal.column === condition.column)
            .map((signal) => signal.unit))]
          const unit = condition.seriesKey === 'meaning' ? condition.selector?.unit || 'source units'
            : definition?.unit ?? (recordedUnits.length === 1 && recordedUnits[0] ? recordedUnits[0] : 'source units')
          const isRange = condition.op === 'between' || condition.op === 'outside'
          return (
            <div className="condition-card" key={condition.editorId}>
              <div className="condition-card-header">
                <strong className="inline-heading">Criterion {index + 1}{condition.seriesKey === 'gradient' && <InfoTip label="About gradient values" text="Enter gradient as a fraction: −0.10 means −10%." />}</strong>
                <button
                  aria-label={`Remove criterion ${index + 1}`}
                  className="icon-button"
                  onClick={() => removeCondition(condition.editorId)}
                  type="button"
                >
                  <X size={14} />
                </button>
              </div>
              <div className="scenario-condition-grid">
                <label>
                  Metric
                  <select
                    value={condition.seriesKey}
                    onChange={(event) => {
                      const key = event.target.value
                      const next = scenarioSeriesDefinitions.find((item) => item.key === key)
                      if (next) {
                        updateCondition(condition.editorId, {
                          seriesKey: next.key,
                          streamName: next.streamName,
                          column: next.column,
                          value: String(next.defaultValue),
                        })
                      } else if (key === 'meaning') {
                        const candidates = (catalog?.signals ?? []).filter((signal) => signal.streamName === condition.streamName && signal.column === condition.column)
                        const selector: Record<string, string> = { ...condition.selector }
                        if (Object.keys(selector).length === 0 && candidates.length) {
                          for (const attribute of ['domain', 'quantity', 'end', 'component', 'unit']) {
                            const values = candidates.map((entry) => attribute === 'unit' ? entry.unit : entry.metadata?.[attribute])
                            if (typeof values[0] === 'string' && values[0] && values.every((value) => value === values[0])) selector[attribute] = values[0]
                          }
                        }
                        updateCondition(condition.editorId, { seriesKey: 'meaning', selector })
                      } else {
                        updateCondition(condition.editorId, { seriesKey: 'custom' })
                      }
                    }}
                  >
                    {scenarioSeriesDefinitions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                    <option value="custom">Custom column</option>
                    <option value="meaning">Choose by meaning</option>
                  </select>
                </label>
                {condition.seriesKey === 'custom' && (
                  <ScenarioColumnPicker
                    key={condition.editorId}
                    streamName={condition.streamName}
                    column={condition.column}
                    catalog={catalog}
                    onChange={(reference) => updateCondition(condition.editorId, reference)}
                  />
                )}
                {condition.seriesKey === 'meaning' && (
                  <ScenarioMeaningPicker
                    streamName={condition.streamName}
                    selector={condition.selector ?? {}}
                    catalog={catalog}
                    onChange={(reference) => updateCondition(condition.editorId, reference)}
                  />
                )}
                <label>
                  Operator
                  <select value={condition.op} onChange={(event) => updateCondition(condition.editorId, { op: event.target.value as ScenarioNumericOperator })}>
                    {(Object.keys(scenarioOperatorLabels) as ScenarioNumericOperator[]).map((operator) => (
                      <option key={operator} value={operator}>{scenarioOperatorLabels[operator]}</option>
                    ))}
                  </select>
                </label>
                {isRange ? (
                  <div className="scenario-range-editor">
                    <label>
                      Lower ({unit})
                      <input inputMode="decimal" value={condition.lower} onChange={(event) => updateCondition(condition.editorId, { lower: event.target.value })} />
                    </label>
                    <label>
                      Upper ({unit})
                      <input inputMode="decimal" value={condition.upper} onChange={(event) => updateCondition(condition.editorId, { upper: event.target.value })} />
                    </label>
                    <label className="mini-check scenario-bound-check">
                      <input checked={condition.includeLower} onChange={(event) => updateCondition(condition.editorId, { includeLower: event.target.checked })} type="checkbox" />
                      Include lower
                    </label>
                    <label className="mini-check scenario-bound-check">
                      <input checked={condition.includeUpper} onChange={(event) => updateCondition(condition.editorId, { includeUpper: event.target.checked })} type="checkbox" />
                      Include upper
                    </label>
                  </div>
                ) : (
                  <label>
                    Value ({unit})
                    <input inputMode="decimal" value={condition.value} onChange={(event) => updateCondition(condition.editorId, { value: event.target.value })} />
                  </label>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function definitionForCondition(condition: ScenarioBuilderCondition) {
  return scenarioSeriesDefinitions.find((item) => item.key === condition.seriesKey)
}
