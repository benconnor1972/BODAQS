import { Plus, X } from 'lucide-react'
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
}: {
  builder: ScenarioPredicateBuilderState
  onChange: (builder: ScenarioPredicateBuilderState) => void
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
          Match
          <select
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
          const isRange = condition.op === 'between' || condition.op === 'outside'
          return (
            <div className="condition-card" key={condition.editorId}>
              <div className="condition-card-header">
                <strong>Criterion {index + 1}</strong>
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
                      } else {
                        updateCondition(condition.editorId, { seriesKey: 'custom' })
                      }
                    }}
                  >
                    {scenarioSeriesDefinitions.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                    <option value="custom">Custom column</option>
                  </select>
                </label>
                {condition.seriesKey === 'custom' && (
                  <>
                    <label>
                      Stream
                      <select value={condition.streamName} onChange={(event) => updateCondition(condition.editorId, { streamName: event.target.value })}>
                        <option value="spatial_context">Spatial context</option>
                        <option value="primary">Primary</option>
                      </select>
                    </label>
                    <label>
                      Column
                      <input value={condition.column} onChange={(event) => updateCondition(condition.editorId, { column: event.target.value })} />
                    </label>
                  </>
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
                      Lower ({definition?.unit ?? 'source units'})
                      <input inputMode="decimal" value={condition.lower} onChange={(event) => updateCondition(condition.editorId, { lower: event.target.value })} />
                    </label>
                    <label>
                      Upper ({definition?.unit ?? 'source units'})
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
                    Value ({definition?.unit ?? 'source units'})
                    <input inputMode="decimal" value={condition.value} onChange={(event) => updateCondition(condition.editorId, { value: event.target.value })} />
                  </label>
                )}
              </div>
              {condition.seriesKey === 'gradient' && <p className="condition-help">Enter gradient as a fraction: −0.10 means −10%.</p>}
            </div>
          )
        })}
      </div>
      <p className="condition-help">Up to four criteria. Advanced JSON supports semantic selectors, categorical operators and nested groups.</p>
    </section>
  )
}

function definitionForCondition(condition: ScenarioBuilderCondition) {
  return scenarioSeriesDefinitions.find((item) => item.key === condition.seriesKey)
}
