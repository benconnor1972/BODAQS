import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import { Activity } from 'lucide-react'
import { InfoTip } from './Common'
import type { LibraryDataSource } from '../data/LibraryDataSource'
import type { SessionRecord, SessionSignalSummary, TimeseriesWindowResponse } from '../domain/types'
import { sessionToStudyRef } from '../domain/studySets'

const PREVIEW_POINTS = 900
const PREVIEW_COLORS = ['#008c95', '#101820']

type PreviewLoadState =
  | { status: 'idle'; message: string }
  | { status: 'loading'; message: string; data?: TimeseriesWindowResponse }
  | { status: 'ready'; message: string; data: TimeseriesWindowResponse }
  | { status: 'error'; message: string; data?: TimeseriesWindowResponse }

type PreviewSeries = {
  label: string
  values: Array<number | null>
}

type PreviewModel = {
  alignedData: uPlot.AlignedData
  times: number[]
  series: PreviewSeries[]
}

export function SessionSignalPreview({
  session,
  dataSource,
  onInspect,
}: {
  session: SessionRecord | null
  dataSource: LibraryDataSource
  onInspect: (session: SessionRecord) => void
}) {
  const [loadState, setLoadState] = useState<PreviewLoadState>({
    status: 'idle',
    message: 'Select a primary session to preview wheel displacement.',
  })
  const gpsDurationS = positiveNumberOrNull(session?.gpsSummary.sessionDurationS)
  const tabularDurationS = positiveNumberOrNull((session?.durationMin ?? 0) * 60)
  const durationS = Math.max(1, gpsDurationS ?? tabularDurationS ?? 1)
  const previewSignals = useMemo(() => previewWheelDisplacementSignals(session), [session])
  const previewSignalKey = previewSignals.map((signal) => signal.column).join('|')

  useEffect(() => {
    let cancelled = false
    async function loadPreview() {
      if (!session) {
        setLoadState({ status: 'idle', message: 'Select a primary session to preview wheel displacement.' })
        return
      }
      if (previewSignals.length === 0) {
        setLoadState({ status: 'idle', message: 'No front/rear normalized wheel displacement signals are available for this session.' })
        return
      }
      setLoadState((current) => {
        const data = loadStateData(current)
        return data
          ? { status: 'loading', message: 'Updating signal preview...', data }
          : { status: 'loading', message: 'Loading signal preview...' }
      })
      try {
        const data = await dataSource.loadTimeseriesWindow(session.libraryId, {
          session: sessionToStudyRef(session),
          signals: previewSignals.map((signal) => ({ column: signal.column })),
          window: { startS: 0, endS: durationS },
          resolution: { targetPoints: PREVIEW_POINTS },
          includeEvents: false,
          includeMarks: false,
        })
        if (!cancelled) {
          setLoadState({ status: 'ready', message: 'Signal preview loaded.', data })
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : String(error)
          setLoadState((current) => {
            const data = loadStateData(current)
            return data ? { status: 'error', message, data } : { status: 'error', message }
          })
        }
      }
    }
    void loadPreview()
    return () => {
      cancelled = true
    }
  }, [dataSource, durationS, previewSignalKey, session?.libraryId, session?.sessionKey])

  return (
    <section className="module session-signal-preview-module">
      <div className="module-header">
        <h2 className="module-heading">
          Signal Preview
          <InfoTip text="A read-only full-session preview of front and rear normalized wheel displacement for the primary selected session." />
        </h2>
        <div className="module-header-actions">
          <span className="module-header-count">{session ? session.name : 'No primary session'}</span>
          <button
            className="secondary-action compact-row-action"
            disabled={!session}
            onClick={() => {
              if (session) {
                onInspect(session)
              }
            }}
            type="button"
          >
            <Activity size={15} />
            Inspect signals
          </button>
        </div>
      </div>
      <SignalPreviewPlot state={loadState} />
    </section>
  )
}

function SignalPreviewPlot({ state }: { state: PreviewLoadState }) {
  const plotHostRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const hostWidth = useElementWidth(plotHostRef, state.status)
  const data = loadStateData(state)
  const model = useMemo(() => (data ? buildPreviewModel(data) : null), [data])
  const plotWidth = Math.max(0, Math.floor(hostWidth))
  const plotHeight = 108

  useEffect(() => {
    if (!plotHostRef.current || plotWidth < 120 || !model || model.times.length === 0 || model.series.length === 0) {
      return
    }
    plotHostRef.current.replaceChildren()
    const plot = new uPlot(previewPlotOptions(model, plotWidth, plotHeight), model.alignedData, plotHostRef.current)
    plotRef.current = plot
    return () => {
      plot.destroy()
      if (plotRef.current === plot) {
        plotRef.current = null
      }
    }
  }, [model, plotHeight, plotWidth])

  if (state.status === 'loading' && !data) {
    return <div className="session-signal-preview-message">{state.message}</div>
  }
  if (state.status === 'error' && !data) {
    return <div className="session-signal-preview-message warning">Could not load signal preview: {state.message}</div>
  }
  if (state.status === 'idle') {
    return <div className="session-signal-preview-message">{state.message}</div>
  }
  if (!model || model.times.length === 0 || previewValues(model.series).length === 0) {
    return <div className="session-signal-preview-message">No normalized wheel displacement samples were returned.</div>
  }

  return (
    <div className="session-signal-preview-frame">
      <div className="signal-inspector-uplot-host signal-inspector-uplot-host-navigator session-signal-preview-host" ref={plotHostRef} />
      <div className="session-signal-preview-legend">
        {model.series.map((series, index) => (
          <span key={series.label}>
            <i style={{ backgroundColor: PREVIEW_COLORS[index % PREVIEW_COLORS.length] }} />
            {series.label}
          </span>
        ))}
      </div>
    </div>
  )
}

function loadStateData(state: PreviewLoadState) {
  return state.status === 'ready' || state.status === 'loading' || state.status === 'error' ? state.data : undefined
}

function previewWheelDisplacementSignals(session: SessionRecord | null) {
  if (!session?.availableSignals?.length) {
    return []
  }
  const selected: SessionSignalSummary[] = []
  for (const end of ['front', 'rear']) {
    const candidates = session.availableSignals
      .filter((signal) => isNormalizedWheelDisplacement(signal) && normalize(signal.end) === end)
      .sort(
        (a, b) =>
          processingRoleRank(a.processingRole) - processingRoleRank(b.processingRole) ||
          originRank(a.origin) - originRank(b.origin) ||
          a.column.localeCompare(b.column),
      )
    if (candidates[0]) {
      selected.push(candidates[0])
    }
  }
  return selected
}

function isNormalizedWheelDisplacement(signal: SessionSignalSummary) {
  return (
    normalize(signal.domain) === 'wheel' &&
    normalize(signal.quantity) === 'disp_norm' &&
    normalize(signal.unit) === '1' &&
    Boolean(signal.column)
  )
}

function processingRoleRank(value: string) {
  return normalize(value) === 'primary_analysis' ? 0 : 1
}

function originRank(value: string) {
  return normalize(value) === 'analysis' ? 0 : 1
}

function normalize(value: unknown) {
  return typeof value === 'string' ? value.trim().toLowerCase() : ''
}

function buildPreviewModel(data: TimeseriesWindowResponse): PreviewModel {
  const signals = data.signals.slice(0, 2)
  const times: number[] = []
  const seriesValues = signals.map((): Array<number | null> => [])
  for (let index = 0; index < data.time.values.length; index += 1) {
    const timeS = data.time.values[index]
    if (typeof timeS !== 'number' || !Number.isFinite(timeS)) {
      continue
    }
    times.push(timeS)
    signals.forEach((signal, signalIndex) => {
      const value = signal.values[index]
      seriesValues[signalIndex].push(typeof value === 'number' && Number.isFinite(value) ? value : null)
    })
  }
  const series = signals.map((signal, index) => ({
    label: signalLabel(signal, index),
    values: seriesValues[index],
  }))
  return {
    alignedData: [times, ...seriesValues],
    times,
    series,
  }
}

function previewPlotOptions(model: PreviewModel, width: number, height: number): uPlot.Options {
  return {
    width,
    height,
    class: 'signal-inspector-uplot-navigator',
    scales: {
      x: { time: false, range: [0, model.times.at(-1) ?? 1] },
      y: { range: previewRange(previewValues(model.series)) },
    },
    axes: [
      {
        scale: 'x',
        side: 2,
        values: (_plot, splits) => splits.map((value) => formatTime(value)),
        stroke: '#5b6670',
        grid: { show: false },
        ticks: { stroke: '#9fb0ad', width: 1, size: 4 },
        font: '10px Aptos, "IBM Plex Sans", "Segoe UI", sans-serif',
        size: 22,
      },
      { scale: 'y', side: 3, show: false },
    ],
    series: [
      {},
      ...model.series.map((series, index): uPlot.Series => ({
        label: series.label,
        scale: 'y',
        stroke: PREVIEW_COLORS[index % PREVIEW_COLORS.length],
        width: 0.95,
        points: { show: false },
        spanGaps: false,
      })),
    ],
    legend: { show: false },
    cursor: { show: false, drag: { x: false, y: false, setScale: false } },
  }
}

function previewValues(series: PreviewSeries[]) {
  return series.flatMap((item) =>
    item.values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value)),
  )
}

function previewRange(values: number[]): [number, number] {
  if (values.length === 0) {
    return [0, 1]
  }
  const minimum = Math.min(...values)
  const robustMin = percentile(values, 0.01)
  const robustMax = percentile(values, 0.99)
  if (robustMin >= -0.1 && robustMax <= 1.05) {
    return [minimum < 0 ? minimum * 1.1 : -0.1, 1]
  }
  const padding = Math.max((robustMax - robustMin) * 0.08, 0.05)
  // Preserve brief negative excursions that would otherwise be excluded by
  // the robust percentile range, with a small margin below the lowest value.
  const lowerBound = minimum < 0 ? minimum * 1.1 : robustMin - padding
  return [lowerBound, robustMax + padding]
}

function percentile(values: number[], fraction: number) {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b)
  if (sorted.length === 0) {
    return 0
  }
  const index = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * fraction)))
  return sorted[index]
}

function positiveNumberOrNull(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

function signalLabel(signal: TimeseriesWindowResponse['signals'][number], index: number) {
  const end = signal.end.trim().toLowerCase()
  if (end === 'front') {
    return 'Front wheel disp norm'
  }
  if (end === 'rear') {
    return 'Rear wheel disp norm'
  }
  return signal.displayName || signal.column || `Signal ${index + 1}`
}

function useElementWidth(ref: RefObject<HTMLElement | null>, observeKey: unknown) {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const element = ref.current
    if (!element) {
      return
    }
    const setNextWidth = (rawWidth: number) => {
      const nextWidth = Math.max(0, Math.floor(rawWidth))
      setWidth((current) => (current === nextWidth ? current : nextWidth))
    }
    setNextWidth(element.getBoundingClientRect().width)
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      setNextWidth(entry?.contentRect.width ?? element.getBoundingClientRect().width)
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [observeKey, ref])
  return width
}

function formatTime(value: number) {
  if (!Number.isFinite(value)) {
    return ''
  }
  if (value < 60) {
    return `${Math.max(0, Math.round(value))}s`
  }
  const minutes = Math.floor(value / 60)
  const seconds = Math.max(0, Math.round(value - minutes * 60)).toString().padStart(2, '0')
  return `${minutes}:${seconds}`
}
