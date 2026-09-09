import { type PointerEvent as ReactPointerEvent, useEffect, useMemo, useState } from 'react'
import { Activity } from 'lucide-react'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import { sessionToStudyRef } from '../domain/studySets'
import type { SessionRecord, SpatialContextWindowResponse, TimeseriesWindowSignal } from '../domain/types'
import { InfoTip, PanelTitle } from './Common'

type SpatialContextPanelProps = {
  sessions: SessionRecord[]
  dataSource: LibraryDataSource
  videoSession: SessionRecord | null
  videoSessionTimeS: number | null
  settings: SpatialContextSettings
}

export type SpatialContextSettings = {
  sessionId: string
  selected: Set<string>
  binCount: number
  gradientMinimum: number
  gradientMaximum: number
  twistinessMaximum: number
  activityMaximum: number
  showGridlines: boolean
}

type SpatialContextControlsProps = {
  sessions: SessionRecord[]
  settings: SpatialContextSettings
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
  { column: 'gradient_fraction', label: 'Gradient', unit: 'rise / run', color: '#008c95', group: 'gradient' },
  { column: 'twistiness_rad_per_m', label: 'Twistiness', unit: 'rad / m', color: '#b66a2c', group: 'twistiness' },
  { column: 'front_suspension_activity', label: 'Front activity', unit: 'm / m', color: '#1769aa', group: 'activity' },
  { column: 'rear_suspension_activity', label: 'Rear activity', unit: 'm / m', color: '#8f4aa8', group: 'activity' },
  { column: 'combined_suspension_activity', label: 'Combined activity', unit: 'm / m', color: '#455a64', group: 'activity' },
]

const HISTOGRAM_COLOR = '#008c95'

export function SpatialContextControls({ sessions, settings, onChange }: SpatialContextControlsProps) {
  const session = sessions.find((item) => sessionKey(item) === settings.sessionId) ?? sessions[0] ?? null

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
        <span>Evidence session</span>
        <select
          disabled={!sessions.length}
          value={session ? sessionKey(session) : ''}
          onChange={(event) => update({ sessionId: event.target.value })}
        >
          {sessions.map((item) => <option key={sessionKey(item)} value={sessionKey(item)}>{item.name}</option>)}
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
      <div className="track-analysis-spatial-range-controls">
        <NumberControl
          label="In-range bins"
          value={settings.binCount}
          min={1}
          max={100}
          step={1}
          normalize={(value) => Math.max(1, Math.min(100, Math.round(value)))}
          onChange={(binCount) => update({ binCount })}
        />
        <NumberControl
          label="Gradient min"
          value={settings.gradientMinimum}
          max={settings.gradientMaximum - 0.0001}
          step={0.05}
          normalize={(value) => Math.min(value, settings.gradientMaximum - 0.0001)}
          onChange={(gradientMinimum) => update({ gradientMinimum })}
        />
        <NumberControl
          label="Gradient max"
          value={settings.gradientMaximum}
          min={settings.gradientMinimum + 0.0001}
          step={0.05}
          normalize={(value) => Math.max(value, settings.gradientMinimum + 0.0001)}
          onChange={(gradientMaximum) => update({ gradientMaximum })}
        />
        <NumberControl
          label="Twistiness max"
          value={settings.twistinessMaximum}
          min={0.0001}
          step={0.05}
          normalize={(value) => Math.max(0.0001, value)}
          onChange={(twistinessMaximum) => update({ twistinessMaximum })}
        />
        <NumberControl
          label="Activity max"
          value={settings.activityMaximum}
          min={0.0001}
          step={0.01}
          normalize={(value) => Math.max(0.0001, value)}
          onChange={(activityMaximum) => update({ activityMaximum })}
        />
      </div>
      <small className="track-analysis-spatial-range-note">
        Bin count applies inside each stated range. Gradient adds underflow and overflow bins; the other metrics add an overflow bin.
      </small>
    </div>
  )
}

export function SpatialContextPanel({
  sessions,
  dataSource,
  videoSession,
  videoSessionTimeS,
  settings,
}: SpatialContextPanelProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: 'idle', data: null, message: '' })
  const [hoverDistanceM, setHoverDistanceM] = useState<number | null>(null)

  const session = sessions.find((item) => sessionKey(item) === settings.sessionId) ?? sessions[0] ?? null

  useEffect(() => {
    let cancelled = false
    if (!session || !dataSource.loadSpatialContextWindow) {
      queueMicrotask(() => {
        if (!cancelled) {
          setLoadState({
            status: 'idle',
            data: null,
            message: dataSource.loadSpatialContextWindow
              ? 'Select an active session.'
              : 'Spatial-context data is not supported by this data source.',
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
  }, [dataSource, session])

  const data = loadState.status === 'ready' ? loadState.data : null
  const distanceAxis = useMemo(() => spatialDistanceAxis(data?.distance.values ?? []), [data])
  const availableColumns = useMemo(() => new Set(data?.metrics.map((metric) => metric.column) ?? []), [data])
  const selectedMetrics = METRICS.filter((metric) => settings.selected.has(metric.column) && availableColumns.has(metric.column))
  const playbackDistanceM = useMemo(() => {
    if (!data || !session || !videoSession || videoSessionTimeS === null || sessionKey(session) !== sessionKey(videoSession)) {
      return null
    }
    return distanceForTime(data, videoSessionTimeS)
  }, [data, session, videoSession, videoSessionTimeS])

  return (
    <section className="track-analysis-spatial-card">
      <PanelTitle
        icon={<Activity size={15} />}
        title="Spatial context"
        action={
          <span className="track-analysis-title-meta">
            {data ? `${data.sampling.sourcePoints.toLocaleString()} spatial samples` : loadState.message}
            <InfoTip text="Canonical session-derived metrics on cumulative session distance. These plots do not replace full-resolution time-domain signals." />
          </span>
        }
      />
      <div className="track-analysis-spatial-body">
        {loadState.status === 'loading' || loadState.status === 'idle' || loadState.status === 'error' ? (
          <div className="track-analysis-placeholder">{loadState.message}</div>
        ) : selectedMetrics.length ? (
          <div className="track-analysis-spatial-content">
            <div className="track-analysis-spatial-plots">
              {selectedMetrics.map((definition) => (
                <MetricLineChart
                  key={definition.column}
                  data={loadState.data!}
                  definition={definition}
                  distanceAxis={distanceAxis}
                  hoverDistanceM={hoverDistanceM}
                  onHoverDistance={(distanceM) => setHoverDistanceM(
                    distanceM === null ? null : nearestDistance(loadState.data!.distance.values, distanceM),
                  )}
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
      </div>
    </section>
  )
}

function NumberControl({ label, value, min, max, step, normalize, onChange }: { label: string; value: number; min?: number; max?: number; step: number; normalize: (value: number) => number; onChange: (value: number) => void }) {
  return (
    <label className="track-analysis-field">
      <span>{label}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(event) => {
        const next = Number(event.target.value)
        if (Number.isFinite(next)) onChange(normalize(next))
      }} />
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
  const height = 150
  const padding = { top: 15, right: 20, bottom: 34, left: 64 }
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
            <text x={padding.left - 8} y={y(tick) + 4} textAnchor="end">{formatMetricValue(tick)}</text>
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
            {definition.label}: {hoverValue === null ? 'No value' : `${formatMetricValue(hoverValue)} ${definition.unit}`}
          </span>
        </div>
      )}
    </div>
  )
}

function MetricHistogram({ definition, signal, binCount, lower, upper }: { definition: MetricDefinition; signal: TimeseriesWindowSignal | null; binCount: number; lower: number; upper: number }) {
  const values = (signal?.values ?? []).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const histogram = makeHistogram(values, lower, upper, binCount, definition.group === 'gradient')
  const width = 280
  const height = 145
  const padding = { top: 18, right: 12, bottom: 34, left: 38 }
  const plotWidth = width - padding.left - padding.right
  const plotHeight = height - padding.top - padding.bottom
  const maximum = Math.max(1, ...histogram.map((bin) => bin.count))
  const barWidth = plotWidth / Math.max(1, histogram.length)
  return (
    <div className="track-analysis-spatial-histogram">
      <strong>{definition.label}</strong>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${definition.label} histogram`}>
        <line className="track-analysis-spatial-axis" x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
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
        <text x={padding.left} y={height - 8} textAnchor="start">{histogram[0]?.label ?? ''}</text>
        <text x={width - padding.right} y={height - 8} textAnchor="end">{histogram.at(-1)?.label ?? ''}</text>
        <text x={padding.left - 6} y={padding.top + 4} textAnchor="end">{maximum}</text>
      </svg>
    </div>
  )
}

function spatialDistanceAxis(distances: Array<number | null>) {
  const maximumDistance = Math.max(0, ...distances.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)))
  const step = gridStep(maximumDistance, [100, 200, 500, 1000, 2000], 3)
  const max = Math.max(step * 4, Math.ceil(maximumDistance / step) * step)
  return { min: 0, max, step, ticks: gridTicks(0, max, step) }
}

function spatialValueAxis(minimum: number, maximum: number) {
  const step = niceNumericStep(maximum - minimum, 5)
  const ticks = gridTicks(minimum, maximum, step)
  if (!ticks.some((tick) => Math.abs(tick - minimum) < step * 0.001)) ticks.unshift(minimum)
  if (!ticks.some((tick) => Math.abs(tick - maximum) < step * 0.001)) ticks.push(maximum)
  return { min: minimum, max: maximum, ticks }
}

function niceNumericStep(span: number, targetIntervals: number) {
  const roughStep = Math.max(Number.EPSILON, span / Math.max(1, targetIntervals))
  const magnitude = 10 ** Math.floor(Math.log10(roughStep))
  const normalized = roughStep / magnitude
  const factor = [1, 2, 5, 10].find((candidate) => normalized <= candidate) ?? 10
  return factor * magnitude
}

function gridStep(span: number, candidates: number[], minimumGridlines: number) {
  const safeSpan = Math.max(0, span)
  return [...candidates].reverse().find((candidate) => safeSpan / candidate >= minimumGridlines) ?? candidates[0]
}

function gridTicks(minimum: number, maximum: number, step: number) {
  const ticks: number[] = []
  const start = Math.ceil(minimum / step) * step
  for (let value = start; value <= maximum + step * 0.001; value += step) {
    ticks.push(Math.round(value * 1e9) / 1e9)
  }
  return ticks
}

function nearestDistance(distances: Array<number | null>, target: number) {
  let nearest: number | null = null
  let nearestDelta = Number.POSITIVE_INFINITY
  distances.forEach((distance) => {
    if (typeof distance !== 'number' || !Number.isFinite(distance)) return
    const delta = Math.abs(distance - target)
    if (delta < nearestDelta) {
      nearest = distance
      nearestDelta = delta
    }
  })
  return nearest
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

function makeHistogram(values: number[], lower: number, upper: number, binCount: number, twoSided: boolean) {
  const width = (upper - lower) / binCount
  const counts = Array.from({ length: binCount }, () => 0)
  let below = 0
  let above = 0
  values.forEach((value) => {
    if (value < lower) below += 1
    else if (value > upper) above += 1
    else counts[Math.min(binCount - 1, Math.floor((value - lower) / width))] += 1
  })
  const bins = counts.map((count, index) => ({ count, label: `${formatMetricValue(lower + index * width)}–${formatMetricValue(lower + (index + 1) * width)}` }))
  if (twoSided) bins.unshift({ count: below, label: `<${formatMetricValue(lower)}` })
  bins.push({ count: above, label: `>${formatMetricValue(upper)}` })
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

function distanceForTime(data: SpatialContextWindowResponse, timeS: number) {
  const times = data.timeMapping.values
  const distances = data.distance.values
  for (let index = 1; index < times.length; index += 1) {
    const before = times[index - 1]
    const after = times[index]
    const beforeDistance = distances[index - 1]
    const afterDistance = distances[index]
    if (typeof before !== 'number' || typeof after !== 'number' || typeof beforeDistance !== 'number' || typeof afterDistance !== 'number' || after <= before || timeS < before || timeS > after) continue
    const fraction = (timeS - before) / (after - before)
    return beforeDistance + fraction * (afterDistance - beforeDistance)
  }
  return null
}

function sessionKey(session: SessionRecord) {
  return `${session.libraryId}:${session.runId}:${session.sessionId}`
}

function formatMetricValue(value: number) {
  return Math.abs(value) >= 10 ? value.toFixed(1) : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
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
