import { type PointerEvent as ReactPointerEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import { Activity, ChevronDown, ChevronRight } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { nearestSpatialDistance, spatialDistanceAxis, spatialDistanceForTime } from '../domain/spatialContext'
import { sessionRefId, sessionToStudyRef } from '../domain/studySets'
import type { SessionRecord, SpatialContextWindowResponse, TimeseriesWindowSignal } from '../domain/types'
import { InfoTip, PanelTitle } from './Common'

type SpatialContextPanelProps = {
  session: SessionRecord | null
  dataSource: LibraryDataSource
  videoSession: SessionRecord | null
  videoSessionTimeS: number | null
  settings: SpatialContextSettings
  cursorDistanceM: number | null
  altitudeContent: ReactNode
  unavailableMessage?: string
  onCursorDistanceChange: (distanceM: number | null) => void
  onDataChange?: (data: SpatialContextWindowResponse | null) => void
}

export type SpatialContextSettings = {
  selected: Set<string>
  binCount: number
  gradientMinimum: number
  gradientMaximum: number
  twistinessMaximum: number
  activityMaximum: number
  showGridlines: boolean
}

type SpatialContextControlsProps = {
  focusOptions: Array<{ value: string; label: string; group: 'Sessions' | 'Tracks' }>
  focusValue: string
  settings: SpatialContextSettings
  onFocusChange: (value: string) => void
  onChange: (settings: SpatialContextSettings) => void
}

type LoadState =
  | { status: 'idle' | 'loading'; data: SpatialContextWindowResponse | null; message: string }
  | { status: 'ready'; data: SpatialContextWindowResponse; message: string }
  | { status: 'error'; data: null; message: string }

type MetricDefinition = {
  column: string
  label: string
  unit: string
  color: string
  group: 'gradient' | 'twistiness' | 'activity'
}

const METRICS: MetricDefinition[] = [
  { column: 'gradient_fraction', label: 'Gradient', unit: '%', color: '#008c95', group: 'gradient' },
  { column: 'twistiness_rad_per_m', label: 'Twistiness', unit: 'rad / m', color: '#b66a2c', group: 'twistiness' },
  { column: 'front_suspension_activity', label: 'Front activity', unit: 'm / m', color: '#1769aa', group: 'activity' },
  { column: 'rear_suspension_activity', label: 'Rear activity', unit: 'm / m', color: '#8f4aa8', group: 'activity' },
  { column: 'combined_suspension_activity', label: 'Combined activity', unit: 'm / m', color: '#455a64', group: 'activity' },
]

const HISTOGRAM_COLOR = '#008c95'

export function SpatialContextControls({ focusOptions, focusValue, settings, onFocusChange, onChange }: SpatialContextControlsProps) {
  function update(patch: Partial<SpatialContextSettings>) {
    onChange({ ...settings, ...patch })
  }

  function toggleMetric(column: string) {
    const selected = new Set(settings.selected)
    if (selected.has(column)) selected.delete(column)
    else selected.add(column)
    update({ selected })
  }

  return (
    <div className="track-analysis-spatial-controls">
      <label className="track-analysis-field">
        <span>Session or Track</span>
        <select
          disabled={!focusOptions.length}
          value={focusValue}
          onChange={(event) => onFocusChange(event.target.value)}
        >
          {(['Sessions', 'Tracks'] as const).map((group) => {
            const options = focusOptions.filter((option) => option.group === group)
            return options.length ? (
              <optgroup key={group} label={group}>
                {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </optgroup>
            ) : null
          })}
        </select>
      </label>
      <fieldset>
        <legend>Metrics</legend>
        <div className="track-analysis-label-options">
          {METRICS.map((metric) => (
            <label key={metric.column}>
              <input
                checked={settings.selected.has(metric.column)}
                type="checkbox"
                onChange={() => toggleMetric(metric.column)}
              />
              <span>{metric.label}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <label className="track-analysis-inline-toggle">
        <input
          checked={settings.showGridlines}
          type="checkbox"
          onChange={(event) => update({ showGridlines: event.target.checked })}
        />
        <span>Show gridlines</span>
      </label>
      <NumberControl
        label="In-range bins"
        value={settings.binCount}
        min={1}
        max={100}
        step={1}
        normalize={(value) => Math.max(1, Math.min(100, Math.round(value)))}
        onChange={(binCount) => update({ binCount })}
      />
      <div className="track-analysis-spatial-range-table" role="table" aria-label="Spatial metric ranges">
        <span aria-hidden="true" />
        <strong role="columnheader">Min</strong>
        <strong role="columnheader">Max</strong>
        <span role="rowheader">Gradient (%)</span>
        <NumberControl
          compact
          label="Gradient minimum (%)"
          value={settings.gradientMinimum * 100}
          max={settings.gradientMaximum * 100 - 0.01}
          step={5}
          normalize={(value) => Math.min(value, settings.gradientMaximum * 100 - 0.01)}
          onChange={(gradientMinimumPercent) => update({ gradientMinimum: gradientMinimumPercent / 100 })}
        />
        <NumberControl
          compact
          label="Gradient maximum (%)"
          value={settings.gradientMaximum * 100}
          min={settings.gradientMinimum * 100 + 0.01}
          step={5}
          normalize={(value) => Math.max(value, settings.gradientMinimum * 100 + 0.01)}
          onChange={(gradientMaximumPercent) => update({ gradientMaximum: gradientMaximumPercent / 100 })}
        />
        <span role="rowheader">Twistiness (rad/m)</span>
        <span aria-hidden="true" />
        <NumberControl
          compact
          label="Twistiness maximum (rad/m)"
          value={settings.twistinessMaximum}
          min={0.0001}
          step={0.05}
          normalize={(value) => Math.max(0.0001, value)}
          onChange={(twistinessMaximum) => update({ twistinessMaximum })}
        />
        <span role="rowheader">Activity (m/m)</span>
        <span aria-hidden="true" />
        <NumberControl
          compact
          label="Activity maximum (m/m)"
          value={settings.activityMaximum}
          min={0.0001}
          step={0.01}
          normalize={(value) => Math.max(0.0001, value)}
          onChange={(activityMaximum) => update({ activityMaximum })}
        />
      </div>
    </div>
  )
}

export function SpatialContextPanel({
  session,
  dataSource,
  videoSession,
  videoSessionTimeS,
  settings,
  cursorDistanceM,
  altitudeContent,
  unavailableMessage,
  onCursorDistanceChange,
  onDataChange,
}: SpatialContextPanelProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle', data: null, message: '' })
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    let cancelled = false
    if (!session || !dataSource.loadSpatialContextWindow) {
      queueMicrotask(() => {
        if (!cancelled) {
          setLoadState({
            status: 'idle',
            data: null,
            message: unavailableMessage ?? (dataSource.loadSpatialContextWindow
              ? 'Select a session as the focus entity.'
              : 'Spatial-context data is not supported by this data source.'),
          })
        }
      })
      return () => {
        cancelled = true
      }
    }
    queueMicrotask(() => {
      if (!cancelled) setLoadState({ status: 'loading', data: null, message: 'Loading spatial context…' })
    })
    dataSource
      .loadSpatialContextWindow(session.libraryId, {
        session: sessionToStudyRef(session),
        resolution: { targetPoints: 25_000 },
      })
      .then((data) => {
        if (!cancelled) setLoadState({ status: 'ready', data, message: '' })
      })
      .catch((error) => {
        if (!cancelled) {
          setLoadState({
            status: 'error',
            data: null,
            message: error instanceof Error ? error.message : 'Could not load spatial-context data.',
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [dataSource, session, unavailableMessage])

  const data = loadState.status === 'ready' && session &&
    sessionRefId(loadState.data.sessionRef) === sessionRefId(sessionToStudyRef(session))
    ? loadState.data
    : null
  useEffect(() => {
    onDataChange?.(data)
  }, [data, onDataChange])
  const distanceAxis = useMemo(() => spatialDistanceAxis(data?.distance.values ?? []), [data])
  const availableColumns = useMemo(() => new Set(data?.metrics.map((metric) => metric.column) ?? []), [data])
  const selectedMetrics = METRICS.filter((metric) => settings.selected.has(metric.column) && availableColumns.has(metric.column))
  const playbackDistanceM = useMemo(() => {
    if (!data || !session || !videoSession || videoSessionTimeS === null || sessionKey(session) !== sessionKey(videoSession)) {
      return null
    }
    return spatialDistanceForTime(data, videoSessionTimeS)
  }, [data, session, videoSession, videoSessionTimeS])

  function handleHoverDistance(distanceM: number | null) {
    const resolvedDistanceM = data && distanceM !== null ? nearestSpatialDistance(data.distance.values, distanceM) : null
    onCursorDistanceChange(resolvedDistanceM)
  }

  return (
    <section className={`track-analysis-spatial-card${expanded ? '' : ' collapsed'}`}>
      <PanelTitle
        icon={<Activity size={15} />}
        title="Spatial context"
        action={
          <span className="track-analysis-title-meta">
            {data ? `${data.sampling.sourcePoints.toLocaleString()} spatial samples` : loadState.message}
            <InfoTip text="Distance-domain altitude evidence and canonical session-derived metrics. Track focus provides track altitude; metrics remain session-derived and do not replace full-resolution time-domain signals." />
            <button
              type="button"
              className="track-analysis-panel-toggle"
              aria-expanded={expanded}
              aria-label={expanded ? 'Collapse spatial context' : 'Expand spatial context'}
              onClick={() => setExpanded((current) => !current)}
              title={expanded ? 'Collapse spatial context' : 'Expand spatial context'}
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
          </span>
        }
      />
      {expanded && <div className="track-analysis-spatial-body">
        {altitudeContent}
        {!data ? (
          <div className="track-analysis-placeholder">{loadState.message || 'Loading spatial contextâ€¦'}</div>
        ) : selectedMetrics.length ? (
          <div className="track-analysis-spatial-content">
            <div className="track-analysis-spatial-plots">
              {selectedMetrics.map((definition) => (
                <MetricLineChart
                  key={definition.column}
                  data={loadState.data!}
                  definition={definition}
                  distanceAxis={distanceAxis}
                  hoverDistanceM={cursorDistanceM}
                  onHoverDistance={handleHoverDistance}
                  playbackDistanceM={playbackDistanceM}
                  showGridlines={settings.showGridlines}
                  valueMinimum={definition.group === 'gradient' ? settings.gradientMinimum : 0}
                  valueMaximum={definition.group === 'gradient' ? settings.gradientMaximum : definition.group === 'twistiness' ? settings.twistinessMaximum : settings.activityMaximum}
                />
              ))}
            </div>
            <div className="track-analysis-spatial-histograms">
              {selectedMetrics.map((definition) => (
                <MetricHistogram
                  key={definition.column}
                  definition={definition}
                  signal={metricSignal(loadState.data!, definition.column)}
                  binCount={settings.binCount}
                  lower={definition.group === 'gradient' ? settings.gradientMinimum : 0}
                  upper={definition.group === 'gradient' ? settings.gradientMaximum : definition.group === 'twistiness' ? settings.twistinessMaximum : settings.activityMaximum}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="track-analysis-placeholder">Select at least one available metric.</div>
        )}
      </div>}
    </section>
  )
}

function NumberControl({ label, value, min, max, step, normalize, onChange, compact = false }: { label: string; value: number; min?: number; max?: number; step: number; normalize: (value: number) => number; onChange: (value: number) => void; compact?: boolean }) {
  const [draft, setDraft] = useState(String(value))

  function commit() {
    const parsed = Number(draft)
    if (!draft.trim() || !Number.isFinite(parsed)) {
      setDraft(String(value))
      return
    }
    const committed = normalize(parsed)
    setDraft(String(committed))
    onChange(committed)
  }

  return (
    <label className={`track-analysis-field${compact ? ' compact-number-control' : ''}`}>
      {!compact && <span>{label}</span>}
      <input
        aria-label={label}
        type="number"
        value={draft}
        min={min}
        max={max}
        step={step}
        onBlur={commit}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
          if (event.key === 'Escape') {
            setDraft(String(value))
          }
        }}
      />
    </label>
  )
}

function MetricLineChart({
  data,
  definition,
  distanceAxis,
  hoverDistanceM,
  onHoverDistance,
  playbackDistanceM,
  showGridlines,
  valueMinimum,
  valueMaximum,
}: {
  data: SpatialContextWindowResponse
  definition: MetricDefinition
  distanceAxis: { min: number; max: number; step: number; ticks: number[] }
  hoverDistanceM: number | null
  onHoverDistance: (distanceM: number | null) => void
  playbackDistanceM: number | null
  showGridlines: boolean
  valueMinimum: number
  valueMaximum: number
}) {
  const signal = metricSignal(data, definition.column)
  const points = alignedPoints(data.distance.values, signal?.values ?? [])
  if (points.length < 2) return <div className="track-analysis-spatial-chart-empty">No valid {definition.label.toLowerCase()} data.</div>
  const width = 920
  const height = 105
  const padding = { top: 10, right: 20, bottom: 28, left: 64 }
  const valueAxis = spatialValueAxis(valueMinimum, valueMaximum)
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const x = (value: number) => padding.left + ((value - distanceAxis.min) / Math.max(1e-9, distanceAxis.max - distanceAxis.min)) * plotWidth
  const y = (value: number) => padding.top + (1 - (value - valueAxis.min) / Math.max(1e-9, valueAxis.max - valueAxis.min)) * plotHeight
  const path = metricPath(data.distance.values, signal?.values ?? [], x, y)
  const markerX = playbackDistanceM !== null && playbackDistanceM >= distanceAxis.min && playbackDistanceM <= distanceAxis.max ? x(playbackDistanceM) : null
  const hoverValue = hoverDistanceM === null ? null : metricValueAtDistance(data.distance.values, signal?.values ?? [], hoverDistanceM)
  const hoverX = hoverDistanceM === null ? null : x(hoverDistanceM)
  const clipId = `spatial-clip-${definition.column}`
  function handlePointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    const viewBoxX = ((event.clientX - bounds.left) / Math.max(1, bounds.width)) * width
    const plotX = Math.max(padding.left, Math.min(width - padding.right, viewBoxX))
    onHoverDistance(distanceAxis.min + ((plotX - padding.left) / plotWidth) * (distanceAxis.max - distanceAxis.min))
  }
  return (
    <div className="track-analysis-spatial-chart-wrap">
      <strong>{definition.label}</strong><small>{definition.unit}</small>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${definition.label} by session distance`}
        onPointerMove={handlePointerMove}
        onPointerLeave={() => onHoverDistance(null)}
      >
        <defs><clipPath id={clipId}><rect x={padding.left} y={padding.top} width={plotWidth} height={plotHeight} /></clipPath></defs>
        {distanceAxis.ticks.map((tick) => (
          <g key={`distance-${tick}`}>
            {showGridlines
              ? <line className="track-analysis-spatial-grid" x1={x(tick)} x2={x(tick)} y1={padding.top} y2={height - padding.bottom} />
              : <line className="track-analysis-spatial-tick" x1={x(tick)} x2={x(tick)} y1={height - padding.bottom} y2={height - padding.bottom + 4} />}
            <text x={x(tick)} y={height - 8} textAnchor="middle">{formatDistanceTick(tick)}</text>
          </g>
        ))}
        {valueAxis.ticks.map((tick) => (
          <g key={`value-${tick}`}>
            {showGridlines
              ? <line className="track-analysis-spatial-grid" x1={padding.left} x2={width - padding.right} y1={y(tick)} y2={y(tick)} />
              : <line className="track-analysis-spatial-tick" x1={padding.left - 4} x2={padding.left} y1={y(tick)} y2={y(tick)} />}
            <text x={padding.left - 8} y={y(tick) + 4} textAnchor="end">{formatMetricDisplayValue(definition, tick)}</text>
          </g>
        ))}
        <line className="track-analysis-spatial-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
        <line className="track-analysis-spatial-axis" x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
        {definition.group === 'gradient' && (
          <line className="track-analysis-spatial-zero" x1={padding.left} x2={width - padding.right} y1={y(0)} y2={y(0)} />
        )}
        <path d={path} fill="none" stroke={definition.color} strokeWidth={1.35} clipPath={`url(#${clipId})`} />
        {markerX !== null && <line className="track-analysis-spatial-playback" x1={markerX} x2={markerX} y1={padding.top} y2={height - padding.bottom} />}
        {hoverX !== null && (
          <g className="track-analysis-spatial-hover">
            <line x1={hoverX} x2={hoverX} y1={padding.top} y2={height - padding.bottom} />
            {hoverValue !== null && <circle cx={hoverX} cy={y(hoverValue)} r={3} fill={definition.color} />}
          </g>
        )}
      </svg>
      {hoverDistanceM !== null && (
        <div
          className="track-analysis-spatial-readout"
          style={{ left: `clamp(95px, ${(x(hoverDistanceM) / width) * 100}%, calc(100% - 95px))` }}
        >
          <strong>{formatDistance(hoverDistanceM)}</strong>
          <span>
            <i style={{ background: definition.color }} />
            {definition.label}: {hoverValue === null ? 'No value' : formatMetricDisplayValue(definition, hoverValue, true)}
          </span>
        </div>
      )}
    </div>
  )
}

function MetricHistogram({ definition, signal, binCount, lower, upper }: { definition: MetricDefinition; signal: TimeseriesWindowSignal | null; binCount: number; lower: number; upper: number }) {
  const values = (signal?.values ?? []).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const twoSided = definition.group === 'gradient'
  const histogram = makeHistogram(values, lower, upper, binCount, twoSided, (value) => formatMetricDisplayValue(definition, value))
  const boundaries = Array.from({ length: binCount + 1 }, (_, index) => lower + ((upper - lower) * index) / binCount)
  const width = 280
  const height = 168
  const padding = { top: 18, right: 12, bottom: 57, left: 24 }
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const maximum = Math.max(1, ...histogram.map((bin) => bin.count))
  const barWidth = plotWidth / Math.max(1, histogram.length)
  const zeroX = padding.left + (
    (twoSided ? 1 : 0) + Math.max(0, Math.min(binCount, ((0 - lower) / (upper - lower)) * binCount))
  ) * barWidth
  return (
    <div className="track-analysis-spatial-histogram">
      <strong>{definition.label}</strong>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${definition.label} histogram`}>
        <line className="track-analysis-spatial-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
        <line className="track-analysis-spatial-axis" x1={zeroX} x2={zeroX} y1={padding.top} y2={height - padding.bottom} />
        {histogram.map((bin, index) => {
          const barHeight = (bin.count / maximum) * plotHeight
          return (
            <rect
              className="track-analysis-spatial-histogram-bar"
              key={`${bin.label}-${index}`}
              x={padding.left + index * barWidth + 1}
              y={padding.top + plotHeight - barHeight}
              width={Math.max(1, barWidth - 2)}
              height={barHeight}
              fill={HISTOGRAM_COLOR}
              fillOpacity={0.3}
              stroke={HISTOGRAM_COLOR}
              strokeOpacity={0.66}
            >
              <title>{bin.label}: {bin.count}</title>
            </rect>
          )
        })}
        {boundaries.map((boundary, index) => {
          const boundaryX = padding.left + (index + (twoSided ? 1 : 0)) * barWidth
          return (
            <g key={`boundary-${index}`}>
              <line className="track-analysis-spatial-tick" x1={boundaryX} x2={boundaryX} y1={height - padding.bottom} y2={height - padding.bottom + 4} />
              <text
                className="track-analysis-spatial-histogram-boundary"
                x={boundaryX}
                y={height - padding.bottom + 9}
                dy="0.35em"
                textAnchor="end"
                transform={`rotate(-90 ${boundaryX} ${height - padding.bottom + 9})`}
              >
                {formatMetricDisplayValue(definition, boundary)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function spatialValueAxis(minimum: number, maximum: number) {
  const step = niceNumericStep(maximum - minimum, 5)
  const ticks = gridTicks(minimum, maximum, step)
  return { min: minimum, max: maximum, ticks }
}

function niceNumericStep(span: number, targetIntervals: number) {
  const roughStep = Math.max(Number.EPSILON, span / Math.max(1, targetIntervals))
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const factor = [1, 2, 5, 10].find((candidate) => normalized <= candidate) ?? 10
  return factor * magnitude
}

function gridTicks(minimum: number, maximum: number, step: number) {
  const ticks: number[] = []
  const start = Math.ceil(minimum / step) * step
  for (let value = start; value <= maximum + step * 0.001; value += step) {
    ticks.push(Math.round(value * 1e9) / 1e9)
  }
  return ticks
}

function metricValueAtDistance(distances: Array<number | null>, values: Array<number | null>, target: number) {
  let nearestIndex = -1
  let nearestDelta = Number.POSITIVE_INFINITY
  distances.forEach((distance, index) => {
    if (typeof distance !== 'number' || !Number.isFinite(distance)) return
    const delta = Math.abs(distance - target)
    if (delta < nearestDelta) {
      nearestIndex = index
      nearestDelta = delta
    }
  })
  const value = values[nearestIndex]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function makeHistogram(values: number[], lower: number, upper: number, binCount: number, twoSided: boolean, formatValue: (value: number) => string) {
  const width = (upper - lower) / binCount
  const counts = Array.from({ length: binCount }, () => 0)
  let below = 0
  let above = 0
  values.forEach((value) => {
    if (value < lower) below += 1
    else if (value > upper) above += 1
    else counts[Math.min(binCount - 1, Math.floor((value - lower) / width))] += 1
  })
  const bins = counts.map((count, index) => ({ count, label: `${formatValue(lower + index * width)}–${formatValue(lower + (index + 1) * width)}` }))
  if (twoSided) bins.unshift({ count: below, label: `<${formatValue(lower)}` })
  bins.push({ count: above, label: `>${formatValue(upper)}` })
  return bins
}

function metricSignal(data: SpatialContextWindowResponse, column: string) {
  return data.metrics.find((metric) => metric.column === column) ?? null
}

function alignedPoints(distances: Array<number | null>, values: Array<number | null>) {
  return distances.flatMap((distance, index) => {
    const value = values[index]
    return typeof distance === 'number' && Number.isFinite(distance) && typeof value === 'number' && Number.isFinite(value)
      ? [{ distance, value }]
      : []
  })
}

function metricPath(distances: Array<number | null>, values: Array<number | null>, x: (value: number) => number, y: (value: number) => number) {
  let drawing = false
  return distances.map((distance, index) => {
    const value = values[index]
    if (typeof distance !== 'number' || !Number.isFinite(distance) || typeof value !== 'number' || !Number.isFinite(value)) {
      drawing = false
      return ''
    }
    const command = drawing ? 'L' : 'M'
    drawing = true
    return `${command} ${x(distance).toFixed(1)} ${y(value).toFixed(1)}`
  }).join(' ')
}

function sessionKey(session: SessionRecord) {
  return `${session.libraryId}:${session.runId}:${session.sessionId}`
}

function formatMetricValue(value: number) {
  return Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
}

function formatMetricDisplayValue(definition: MetricDefinition, value: number, includeUnit = false) {
  if (definition.group === 'gradient') {
    return `${Math.round(value * 100)}%`
  }
  const formatted = formatMetricValue(value)
  return includeUnit && definition.unit ? `${formatted} ${definition.unit}` : formatted
}

function formatDistance(distanceM: number) {
  return distanceM >= 1000 ? `${(distanceM / 1000).toFixed(2)} km` : `${Math.round(distanceM)} m`
}

function formatDistanceTick(distanceM: number) {
  if (Math.abs(distanceM) >= 1000) {
    return `${(distanceM / 1000).toFixed(distanceM % 1000 === 0 ? 0 : 1)} km`
  }
  return `${Math.round(distanceM)} m`
}
