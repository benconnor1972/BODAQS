# Phase 5 — Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 10-tile Plotly suspension dashboard at `/dashboard/[run_id]`, loading processed signal, event, and metric data from Dexie and rendering it with Plotly.

**Architecture:** Pure data-preparation functions in `lib/charts/prepare.ts` are unit-tested in Vitest and handle all array math (histogram bins, event counts, scatter extraction). Four Svelte chart components wrap Plotly and receive pre-prepared data as props — they show a muted placeholder when data is absent. The dashboard page loads from Dexie, drives a session selector and unit toggle, and arranges the 10 tiles in a CSS two-column grid.

**Tech Stack:** SvelteKit 5 runes (`$state`, `$derived`, `$effect`), Plotly.js (`plotly.js-dist-min` already installed), Dexie 4 (read-only — data already in DB from Phase 4), existing `getSessionsForRun`, `getSignalsForSession`, `getEventsForSession`, `getMetricsForSession` from `lib/db/artifacts.ts`, `decodeSignalColumn` from `lib/api/preprocess.ts`.

---

## Signal column reference (from actual test run)

```
front_wheel_disp_dom_wheel [mm]          — front displacement, engineering units
front_wheel_disp_norm_dom_wheel [1]      — front displacement, normalised (0–1)
front_wheel_vel_dom_wheel [mm/s]         — front velocity
rear_wheel_disp_dom_wheel [mm]           — rear displacement, engineering units
rear_wheel_disp_norm_dom_wheel [1]       — rear displacement, normalised (0–1)
rear_wheel_vel_dom_wheel [mm/s]          — rear velocity
```

Event/metric `signal_col` values: `'front_wheel_vel_dom_wheel [mm/s]'` / `'rear_wheel_vel_dom_wheel [mm/s]'` — front/rear determined by `signal_col.includes('front')`.

Event names (actual): `'wheel compression events with max normalized displacement >0.25'` / `'wheel rebound events with max normalized displacement >0.25'` — matched by `event_name.includes('compression')` / `includes('rebound')`.

Metrics fields used: `m_peak_disp_max` (x), `m_interval_vel_max` (compression y), `m_interval_vel_min` (rebound y).

---

## File Map

| File | Responsibility |
|---|---|
| `frontend/src/lib/charts/prepare.ts` | Pure data-prep: signal column lookup, histogram, events bar, metric scatter |
| `frontend/src/lib/charts/prepare.test.ts` | Vitest unit tests for prepare functions |
| `frontend/src/lib/charts/DisplacementHistogram.svelte` | Plotly histogram for displacement data |
| `frontend/src/lib/charts/VelocityHistogram.svelte` | Plotly histogram for velocity data |
| `frontend/src/lib/charts/EventsBar.svelte` | Plotly bar chart for event counts by name |
| `frontend/src/lib/charts/MetricScatter.svelte` | Plotly scatter for compression/rebound metrics |
| `frontend/src/lib/charts/EmptyTile.svelte` | Muted placeholder tile (no Plotly) |
| `frontend/src/routes/dashboard/[run_id]/+page.svelte` | Full dashboard: loads Dexie, renders 10 tiles |

---

## Task 1: Data preparation functions (TDD)

**Files:**
- Create: `frontend/src/lib/charts/prepare.ts`
- Create: `frontend/src/lib/charts/prepare.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/prepare.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import {
	findDisplacementColumn,
	findVelocityColumn,
	computePercentileRange,
	computeHistogram,
	prepareEventsBar,
	prepareMetricScatter
} from '$lib/charts/prepare';

const COLUMNS = [
	'front_wheel_disp_dom_wheel [mm]',
	'front_wheel_disp_norm_dom_wheel [1]',
	'front_wheel_vel_dom_wheel [mm/s]',
	'rear_wheel_disp_dom_wheel [mm]',
	'rear_wheel_disp_norm_dom_wheel [1]',
	'rear_wheel_vel_dom_wheel [mm/s]',
	'mark'
];

describe('findDisplacementColumn', () => {
	it('finds front engineering displacement column', () => {
		expect(findDisplacementColumn(COLUMNS, 'front', false)).toBe(
			'front_wheel_disp_dom_wheel [mm]'
		);
	});

	it('finds front normalised displacement column', () => {
		expect(findDisplacementColumn(COLUMNS, 'front', true)).toBe(
			'front_wheel_disp_norm_dom_wheel [1]'
		);
	});

	it('finds rear engineering displacement column', () => {
		expect(findDisplacementColumn(COLUMNS, 'rear', false)).toBe(
			'rear_wheel_disp_dom_wheel [mm]'
		);
	});

	it('finds rear normalised displacement column', () => {
		expect(findDisplacementColumn(COLUMNS, 'rear', true)).toBe(
			'rear_wheel_disp_norm_dom_wheel [1]'
		);
	});

	it('returns null when no matching column exists', () => {
		expect(findDisplacementColumn(['mark'], 'front', false)).toBeNull();
	});
});

describe('findVelocityColumn', () => {
	it('finds front velocity column', () => {
		expect(findVelocityColumn(COLUMNS, 'front')).toBe('front_wheel_vel_dom_wheel [mm/s]');
	});

	it('finds rear velocity column', () => {
		expect(findVelocityColumn(COLUMNS, 'rear')).toBe('rear_wheel_vel_dom_wheel [mm/s]');
	});

	it('returns null when no matching column exists', () => {
		expect(findVelocityColumn(['mark'], 'rear')).toBeNull();
	});
});

describe('computePercentileRange', () => {
	it('returns [p5, p95] range for a sorted array', () => {
		// 100 values: 0..99
		const data = new Float32Array(Array.from({ length: 100 }, (_, i) => i));
		const [lo, hi] = computePercentileRange(data, 5, 95);
		expect(lo).toBeCloseTo(4.95, 0);
		expect(hi).toBeCloseTo(94.05, 0);
	});

	it('filters NaN before computing range', () => {
		const data = new Float32Array([NaN, 1, 2, 3, NaN]);
		const [lo, hi] = computePercentileRange(data, 0, 100);
		expect(lo).toBeCloseTo(1, 1);
		expect(hi).toBeCloseTo(3, 1);
	});
});

describe('computeHistogram', () => {
	it('returns bins+1 edges and bins counts', () => {
		const data = new Float32Array([0, 1, 2, 3, 4]);
		const result = computeHistogram(data, 5, [0, 4]);
		expect(result.binEdges).toHaveLength(6);
		expect(result.counts).toHaveLength(5);
	});

	it('counts values into correct bins', () => {
		// 10 values uniformly in [0, 10], 2 bins → 5 each
		const data = new Float32Array(Array.from({ length: 10 }, (_, i) => i));
		const result = computeHistogram(data, 2, [0, 9]);
		expect(result.counts[0]).toBe(5);
		expect(result.counts[1]).toBe(5);
	});

	it('ignores NaN and Infinity values', () => {
		const data = new Float32Array([1, 2, NaN, Infinity, -Infinity, 3]);
		const result = computeHistogram(data, 3, [1, 3]);
		const total = result.counts.reduce((a, b) => a + b, 0);
		expect(total).toBe(3);
	});
});

describe('prepareEventsBar', () => {
	const events = [
		{ event_name: 'compression', signal_col: 'front_wheel_vel_dom_wheel [mm/s]' },
		{ event_name: 'compression', signal_col: 'front_wheel_vel_dom_wheel [mm/s]' },
		{ event_name: 'rebound', signal_col: 'front_wheel_vel_dom_wheel [mm/s]' },
		{ event_name: 'compression', signal_col: 'rear_wheel_vel_dom_wheel [mm/s]' },
		{ event_name: 'rebound', signal_col: 'rear_wheel_vel_dom_wheel [mm/s]' }
	] as Record<string, unknown>[];

	it('returns front event counts (2 compressions, 1 rebound)', () => {
		const result = prepareEventsBar(events, 'front');
		const comprIdx = result.labels.indexOf('compression');
		const rebIdx = result.labels.indexOf('rebound');
		expect(result.counts[comprIdx]).toBe(2);
		expect(result.counts[rebIdx]).toBe(1);
	});

	it('returns rear event counts (1 compression, 1 rebound)', () => {
		const result = prepareEventsBar(events, 'rear');
		const comprIdx = result.labels.indexOf('compression');
		const rebIdx = result.labels.indexOf('rebound');
		expect(result.counts[comprIdx]).toBe(1);
		expect(result.counts[rebIdx]).toBe(1);
	});

	it('returns empty when no matching side', () => {
		const result = prepareEventsBar([], 'front');
		expect(result.labels).toHaveLength(0);
		expect(result.counts).toHaveLength(0);
	});

	it('omits labels with zero count', () => {
		const result = prepareEventsBar(events, 'rear');
		expect(result.labels.length).toBe(result.counts.length);
		expect(result.counts.every((c) => c > 0)).toBe(true);
	});
});

describe('prepareMetricScatter', () => {
	const metrics = [
		{
			event_name: 'wheel compression events with max normalized displacement >0.25',
			signal_col: 'front_wheel_vel_dom_wheel [mm/s]',
			m_peak_disp_max: 10,
			m_interval_vel_max: 200
		},
		{
			event_name: 'wheel rebound events with max normalized displacement >0.25',
			signal_col: 'rear_wheel_vel_dom_wheel [mm/s]',
			m_peak_disp_max: 15,
			m_interval_vel_min: -300
		},
		{
			event_name: 'wheel compression events with max normalized displacement >0.25',
			signal_col: 'rear_wheel_vel_dom_wheel [mm/s]',
			m_peak_disp_max: 20,
			m_interval_vel_max: 400
		}
	] as Record<string, unknown>[];

	it('extracts front compression scatter points', () => {
		const result = prepareMetricScatter(metrics, 'compression', 'front', 'm_peak_disp_max', 'm_interval_vel_max');
		expect(result.x).toEqual([10]);
		expect(result.y).toEqual([200]);
	});

	it('extracts rear rebound scatter points', () => {
		const result = prepareMetricScatter(metrics, 'rebound', 'rear', 'm_peak_disp_max', 'm_interval_vel_min');
		expect(result.x).toEqual([15]);
		expect(result.y).toEqual([-300]);
	});

	it('returns empty arrays when nothing matches', () => {
		const result = prepareMetricScatter([], 'compression', 'front', 'm_peak_disp_max', 'm_interval_vel_max');
		expect(result.x).toHaveLength(0);
		expect(result.y).toHaveLength(0);
	});

	it('skips rows with null/undefined metric values', () => {
		const sparse = [
			{
				event_name: 'wheel compression events',
				signal_col: 'front_wheel_vel_dom_wheel [mm/s]',
				m_peak_disp_max: null,
				m_interval_vel_max: 200
			}
		] as Record<string, unknown>[];
		const result = prepareMetricScatter(sparse, 'compression', 'front', 'm_peak_disp_max', 'm_interval_vel_max');
		expect(result.x).toHaveLength(0);
	});
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/charts/prepare.test.ts
```

Expected: all fail with "Cannot find module '$lib/charts/prepare'"

- [ ] **Step 3: Write `prepare.ts`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/prepare.ts`:

```ts
export interface HistogramData {
	binEdges: number[];
	counts: number[];
}

export interface EventsBarData {
	labels: string[];
	counts: number[];
}

export interface ScatterData {
	x: number[];
	y: number[];
}

export function findDisplacementColumn(
	columnNames: string[],
	end: 'front' | 'rear',
	normalised: boolean
): string | null {
	if (normalised) {
		return (
			columnNames.find(
				(c) => c.startsWith(end + '_') && c.includes('_disp_norm_') && c.endsWith('[1]')
			) ?? null
		);
	}
	return (
		columnNames.find(
			(c) =>
				c.startsWith(end + '_') &&
				c.includes('_disp_') &&
				!c.includes('_norm_') &&
				!c.includes('_vel_') &&
				!c.includes('_acc_') &&
				c.endsWith('[mm]')
		) ?? null
	);
}

export function findVelocityColumn(
	columnNames: string[],
	end: 'front' | 'rear'
): string | null {
	return (
		columnNames.find(
			(c) =>
				c.startsWith(end + '_') &&
				c.includes('_vel_dom_') &&
				!c.includes('_disp_') &&
				!c.includes('_acc_') &&
				c.endsWith('[mm/s]')
		) ?? null
	);
}

export function computePercentileRange(
	data: Float32Array,
	loPct: number,
	hiPct: number
): [number, number] {
	const clean = Array.from(data).filter((v) => isFinite(v));
	if (clean.length === 0) return [0, 1];
	clean.sort((a, b) => a - b);
	const lo = clean[Math.floor((loPct / 100) * (clean.length - 1))];
	const hi = clean[Math.ceil((hiPct / 100) * (clean.length - 1))];
	return [lo, hi];
}

export function computeHistogram(
	data: Float32Array,
	bins: number,
	range: [number, number]
): HistogramData {
	const [min, max] = range;
	const span = max - min;
	if (span <= 0 || bins <= 0) return { binEdges: [], counts: [] };

	const counts = new Array<number>(bins).fill(0);
	const binEdges = Array.from({ length: bins + 1 }, (_, i) => min + (i / bins) * span);

	for (let i = 0; i < data.length; i++) {
		const v = data[i];
		if (!isFinite(v)) continue;
		const idx = Math.floor(((v - min) / span) * bins);
		if (idx >= 0 && idx < bins) counts[idx]++;
		else if (idx === bins) counts[bins - 1]++;
	}

	return { binEdges, counts };
}

export function prepareEventsBar(
	events: Record<string, unknown>[],
	end: 'front' | 'rear'
): EventsBarData {
	const filtered = events.filter(
		(e) => typeof e.signal_col === 'string' && e.signal_col.includes(end)
	);
	const tally = new Map<string, number>();
	for (const e of filtered) {
		const name = String(e.event_name ?? 'unknown');
		tally.set(name, (tally.get(name) ?? 0) + 1);
	}
	const labels = Array.from(tally.keys());
	const counts = labels.map((l) => tally.get(l)!);
	return { labels, counts };
}

export function prepareMetricScatter(
	metrics: Record<string, unknown>[],
	eventType: 'compression' | 'rebound',
	end: 'front' | 'rear',
	xKey: string,
	yKey: string
): ScatterData {
	const filtered = metrics.filter(
		(m) =>
			typeof m.event_name === 'string' &&
			m.event_name.includes(eventType) &&
			typeof m.signal_col === 'string' &&
			m.signal_col.includes(end)
	);
	const x: number[] = [];
	const y: number[] = [];
	for (const m of filtered) {
		const xv = m[xKey];
		const yv = m[yKey];
		if (typeof xv === 'number' && xv !== null && typeof yv === 'number' && yv !== null) {
			x.push(xv);
			y.push(yv);
		}
	}
	return { x, y };
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/charts/prepare.test.ts
```

Expected: all 20 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/charts/
git commit -m "feat(frontend): add dashboard data-prep functions with full test suite"
```

---

## Task 2: Chart components

**Files:**
- Create: `frontend/src/lib/charts/EmptyTile.svelte`
- Create: `frontend/src/lib/charts/DisplacementHistogram.svelte`
- Create: `frontend/src/lib/charts/VelocityHistogram.svelte`
- Create: `frontend/src/lib/charts/EventsBar.svelte`
- Create: `frontend/src/lib/charts/MetricScatter.svelte`

No unit tests for these — they depend on browser DOM. Verified via `svelte-check` and `npm run build`.

- [ ] **Step 1: Write `EmptyTile.svelte`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/EmptyTile.svelte`:

```svelte
<script lang="ts">
	interface Props {
		title: string;
	}
	const { title }: Props = $props();
</script>

<div class="empty-tile">
	<span class="title">{title}</span>
	<span class="msg">No data</span>
</div>

<style>
	.empty-tile {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		height: 300px;
		background: #f5f5f5;
		border: 1px dashed #ccc;
		border-radius: 4px;
		color: #999;
		gap: 8px;
	}
	.title {
		font-size: 0.85rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}
	.msg {
		font-size: 0.75rem;
	}
</style>
```

- [ ] **Step 2: Write `DisplacementHistogram.svelte`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/DisplacementHistogram.svelte`:

```svelte
<script lang="ts">
	import { onDestroy } from 'svelte';
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import { computeHistogram, computePercentileRange } from './prepare';

	interface Props {
		title: string;
		data: Float32Array | null;
		normalised: boolean;
	}
	const { title, data, normalised }: Props = $props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.length === 0) return;

		const range = computePercentileRange(data, 5, 95);
		const { binEdges, counts } = computeHistogram(data, 50, range);
		const xLabel = normalised ? 'Displacement (normalised)' : 'Displacement (mm)';

		Plotly.newPlot(
			container,
			[
				{
					x: binEdges.slice(0, -1),
					y: counts,
					type: 'bar',
					name: title,
					marker: { color: '#1f77b4' }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: xLabel } },
				yaxis: { title: { text: 'Count' } },
				margin: { t: 40, r: 20, b: 50, l: 55 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			if (container) Plotly.purge(container);
		};
	});

	onDestroy(() => {
		if (container) Plotly.purge(container);
	});
</script>

{#if data && data.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
```

- [ ] **Step 3: Write `VelocityHistogram.svelte`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/VelocityHistogram.svelte`:

```svelte
<script lang="ts">
	import { onDestroy } from 'svelte';
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import { computeHistogram } from './prepare';

	interface Props {
		title: string;
		data: Float32Array | null;
	}
	const { title, data }: Props = $props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.length === 0) return;

		const ABS_LIMIT = 2000;
		const { binEdges, counts } = computeHistogram(data, 100, [-ABS_LIMIT, ABS_LIMIT]);

		Plotly.newPlot(
			container,
			[
				{
					x: binEdges.slice(0, -1),
					y: counts,
					type: 'bar',
					name: title,
					marker: { color: '#ff7f0e' }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: 'Velocity (mm/s)' } },
				yaxis: { title: { text: 'Count' } },
				margin: { t: 40, r: 20, b: 50, l: 55 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			if (container) Plotly.purge(container);
		};
	});

	onDestroy(() => {
		if (container) Plotly.purge(container);
	});
</script>

{#if data && data.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
```

- [ ] **Step 4: Write `EventsBar.svelte`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/EventsBar.svelte`:

```svelte
<script lang="ts">
	import { onDestroy } from 'svelte';
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import type { EventsBarData } from './prepare';

	interface Props {
		title: string;
		data: EventsBarData | null;
	}
	const { title, data }: Props = $props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.labels.length === 0) return;

		Plotly.newPlot(
			container,
			[
				{
					x: data.labels,
					y: data.counts,
					type: 'bar',
					marker: { color: '#2ca02c' }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: 'Event type' }, tickangle: -20 },
				yaxis: { title: { text: 'Count' } },
				margin: { t: 40, r: 20, b: 80, l: 55 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			if (container) Plotly.purge(container);
		};
	});

	onDestroy(() => {
		if (container) Plotly.purge(container);
	});
</script>

{#if data && data.labels.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
```

- [ ] **Step 5: Write `MetricScatter.svelte`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/charts/MetricScatter.svelte`:

```svelte
<script lang="ts">
	import { onDestroy } from 'svelte';
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import type { ScatterData } from './prepare';

	interface Props {
		title: string;
		data: ScatterData | null;
		xLabel?: string;
		yLabel?: string;
	}
	const { title, data, xLabel = 'Peak displacement (mm)', yLabel = 'Velocity (mm/s)' }: Props =
		$props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.x.length === 0) return;

		Plotly.newPlot(
			container,
			[
				{
					x: data.x,
					y: data.y,
					mode: 'markers',
					type: 'scatter',
					marker: { color: '#9467bd', size: 6, opacity: 0.7 }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: xLabel } },
				yaxis: { title: { text: yLabel } },
				margin: { t: 40, r: 20, b: 50, l: 65 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			if (container) Plotly.purge(container);
		};
	});

	onDestroy(() => {
		if (container) Plotly.purge(container);
	});
</script>

{#if data && data.x.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
```

- [ ] **Step 6: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 7: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/charts/
git commit -m "feat(frontend): add Plotly chart components for dashboard tiles"
```

---

## Task 3: Dashboard page

**Files:**
- Modify: `frontend/src/routes/dashboard/[run_id]/+page.svelte`

The current file is a placeholder (just a heading). Replace it with the full dashboard.

- [ ] **Step 1: Read the current placeholder**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/dashboard/[run_id]/+page.svelte`.

- [ ] **Step 2: Write the full dashboard page**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/dashboard/[run_id]/+page.svelte`:

```svelte
<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { decodeSignalColumn } from '$lib/api/preprocess';
	import {
		getAllRuns,
		getSessionsForRun,
		getSignalsForSession,
		getEventsForSession,
		getMetricsForSession
	} from '$lib/db/artifacts';
	import type { Session } from '$lib/db/dexie';
	import {
		findDisplacementColumn,
		findVelocityColumn,
		computePercentileRange,
		computeHistogram,
		prepareEventsBar,
		prepareMetricScatter
	} from '$lib/charts/prepare';
	import DisplacementHistogram from '$lib/charts/DisplacementHistogram.svelte';
	import VelocityHistogram from '$lib/charts/VelocityHistogram.svelte';
	import EventsBar from '$lib/charts/EventsBar.svelte';
	import MetricScatter from '$lib/charts/MetricScatter.svelte';

	const run_id = $derived(page.params.run_id);

	let sessions = $state<Session[]>([]);
	let selectedSessionId = $state<string | null>(null);
	let normalised = $state(true);
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Decoded signals for the selected session
	let signals = $state<Record<string, Float32Array>>({});
	let events = $state<Record<string, unknown>[]>([]);
	let metrics = $state<Record<string, unknown>[]>([]);
	let columnNames = $state<string[]>([]);

	onMount(async () => {
		try {
			const sessionList = await getSessionsForRun(run_id);
			sessions = sessionList;
			if (sessionList.length > 0) {
				selectedSessionId = sessionList[0].id;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load sessions.';
		}
	});

	$effect(() => {
		if (!selectedSessionId) return;
		loadSession(selectedSessionId);
	});

	async function loadSession(session_id: string): Promise<void> {
		loading = true;
		error = null;
		try {
			const [signalRows, eventRows, metricRows] = await Promise.all([
				getSignalsForSession(session_id),
				getEventsForSession(session_id),
				getMetricsForSession(session_id)
			]);

			const decoded: Record<string, Float32Array> = {};
			for (const row of signalRows) {
				decoded[row.column_name] = decodeSignalColumn(row.data);
			}

			signals = decoded;
			columnNames = Object.keys(decoded);
			events = eventRows.flatMap((r) => r.rows);
			metrics = metricRows.flatMap((r) => r.rows);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load session data.';
		} finally {
			loading = false;
		}
	}

	// Derived: signal data for each tile
	let frontDispCol = $derived(findDisplacementColumn(columnNames, 'front', normalised));
	let rearDispCol = $derived(findDisplacementColumn(columnNames, 'rear', normalised));
	let frontVelCol = $derived(findVelocityColumn(columnNames, 'front'));
	let rearVelCol = $derived(findVelocityColumn(columnNames, 'rear'));

	let frontDispData = $derived(frontDispCol ? (signals[frontDispCol] ?? null) : null);
	let rearDispData = $derived(rearDispCol ? (signals[rearDispCol] ?? null) : null);
	let frontVelData = $derived(frontVelCol ? (signals[frontVelCol] ?? null) : null);
	let rearVelData = $derived(rearVelCol ? (signals[rearVelCol] ?? null) : null);

	let frontEventsBar = $derived(prepareEventsBar(events, 'front'));
	let rearEventsBar = $derived(prepareEventsBar(events, 'rear'));

	let frontCompScatter = $derived(
		prepareMetricScatter(metrics, 'compression', 'front', 'm_peak_disp_max', 'm_interval_vel_max')
	);
	let rearCompScatter = $derived(
		prepareMetricScatter(metrics, 'compression', 'rear', 'm_peak_disp_max', 'm_interval_vel_max')
	);
	let frontReboundScatter = $derived(
		prepareMetricScatter(metrics, 'rebound', 'front', 'm_peak_disp_max', 'm_interval_vel_min')
	);
	let rearReboundScatter = $derived(
		prepareMetricScatter(metrics, 'rebound', 'rear', 'm_peak_disp_max', 'm_interval_vel_min')
	);
</script>

<svelte:head>
	<title>BODAQS — Dashboard</title>
</svelte:head>

<h1>Dashboard</h1>

{#if error}
	<p role="alert">{error}</p>
{/if}

<div class="controls">
	{#if sessions.length > 1}
		<label>
			Session
			<select
				value={selectedSessionId}
				onchange={(e) => {
					selectedSessionId = (e.target as HTMLSelectElement).value;
				}}
			>
				{#each sessions as s (s.id)}
					<option value={s.id}>{s.id}</option>
				{/each}
			</select>
		</label>
	{/if}

	<label>
		<input type="checkbox" bind:checked={normalised} />
		Normalised (0–1)
	</label>
</div>

{#if loading}
	<p>Loading…</p>
{:else}
	<div class="grid">
		<DisplacementHistogram
			title="Front Suspension: Displacement"
			data={frontDispData}
			{normalised}
		/>
		<DisplacementHistogram
			title="Rear Suspension: Displacement"
			data={rearDispData}
			{normalised}
		/>

		<VelocityHistogram title="Front Suspension: Velocity" data={frontVelData} />
		<VelocityHistogram title="Rear Suspension: Velocity" data={rearVelData} />

		<EventsBar title="Front Suspension: Events" data={frontEventsBar.labels.length > 0 ? frontEventsBar : null} />
		<EventsBar title="Rear Suspension: Events" data={rearEventsBar.labels.length > 0 ? rearEventsBar : null} />

		<MetricScatter
			title="Front Suspension: Compressions >25%"
			data={frontCompScatter.x.length > 0 ? frontCompScatter : null}
			yLabel="Max velocity (mm/s)"
		/>
		<MetricScatter
			title="Rear Suspension: Compressions >25%"
			data={rearCompScatter.x.length > 0 ? rearCompScatter : null}
			yLabel="Max velocity (mm/s)"
		/>

		<MetricScatter
			title="Front Suspension: Rebounds >25%"
			data={frontReboundScatter.x.length > 0 ? frontReboundScatter : null}
			yLabel="Min velocity (mm/s)"
		/>
		<MetricScatter
			title="Rear Suspension: Rebounds >25%"
			data={rearReboundScatter.x.length > 0 ? rearReboundScatter : null}
			yLabel="Min velocity (mm/s)"
		/>
	</div>
{/if}

<style>
	.controls {
		display: flex;
		gap: 1.5rem;
		align-items: center;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}
	.grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1rem;
	}
	@media (max-width: 700px) {
		.grid {
			grid-template-columns: 1fr;
		}
	}
</style>
```

- [ ] **Step 3: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 4: Run full test suite**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test
```

Expected: all 63 tests pass (43 from Phases 3–4 + 20 new prepare tests).

- [ ] **Step 5: Run build**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Update SESSION.md**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/SESSION.md`.

In the Phase status table:
- Change Phase 5 from `🔜 Next` to `✅ Complete, 63/63 tests passing`
- Change Phase 6 from `⬜ Not started` to `🔜 Next`

Add a "Phase 5 — What was built" section immediately after the Phase 4 section:

```markdown
## Phase 5 — What was built

### Files created/modified
```
frontend/src/lib/charts/
├── prepare.ts                  — findDisplacementColumn, findVelocityColumn, computePercentileRange, computeHistogram, prepareEventsBar, prepareMetricScatter
├── prepare.test.ts             — 20 tests: signal lookup, histogram, events bar, scatter
├── DisplacementHistogram.svelte — Plotly bar histogram, 50 bins, 5–95th percentile trim, normalised/mm toggle
├── VelocityHistogram.svelte    — Plotly bar histogram, 100 bins, ±2000 mm/s range
├── EventsBar.svelte            — Plotly bar, event counts by name for front/rear
├── MetricScatter.svelte        — Plotly scatter, compression/rebound metrics
└── EmptyTile.svelte            — Muted placeholder shown when data is absent

frontend/src/routes/dashboard/[run_id]/
└── +page.svelte                — Full 10-tile dashboard: loads Dexie, session selector, unit toggle, 2-column CSS grid
```

### Key decisions made

**Signal column matching:** `findDisplacementColumn` and `findVelocityColumn` use substring matching (`startsWith(end + '_')` + quantity/unit keywords). This is robust to column name variations as long as the naming convention (end prefix, `_dom_`, unit suffix) is preserved.

**Histogram trimming:** Displacement tiles trim to [5th, 95th] percentile via `computePercentileRange`; velocity tiles clamp to ±2000 mm/s. Both handled in the chart component (not the prepare function) so the pure prepare.ts stays testable without browser context.

**Event/metric filtering:** Events and metrics are filtered by `signal_col.includes('front'/'rear')` for side, and `event_name.includes('compression'/'rebound')` for event type. This matches actual event names from the pipeline (`'wheel compression events with max normalized displacement >0.25'`).

**Missing tile:** Each chart component conditionally renders `EmptyTile` when its data prop is null or empty — never an error state.
```

- [ ] **Step 7: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/routes/dashboard/ webapp.bodaqs.net/SESSION.md
git commit -m "feat(frontend): 10-tile suspension dashboard with Plotly and session/unit controls"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| 10 tiles in 2-column grid | Task 3 (CSS grid, 10 tile components) |
| Row 1: Front/Rear displacement histograms | Tasks 2+3 (DisplacementHistogram × 2) |
| Row 2: Front/Rear velocity histograms | Tasks 2+3 (VelocityHistogram × 2) |
| Row 3: Front/Rear events bar | Tasks 2+3 (EventsBar × 2) |
| Row 4: Front/Rear compressions >25% scatter | Tasks 2+3 (MetricScatter × 2, `compression`) |
| Row 5: Front/Rear rebounds >25% scatter | Tasks 2+3 (MetricScatter × 2, `rebound`) |
| Session selector (single session at a time) | Task 3 (`<select>` bound to `selectedSessionId`) |
| Unit toggle: normalised vs mm | Task 3 (`normalised` checkbox → `findDisplacementColumn` arg) |
| Missing tile: muted placeholder, not error | Tasks 2+3 (EmptyTile shown when data null/empty) |
| Signals decoded from base64 float32 | Task 3 (`decodeSignalColumn` from existing lib) |
| Data read from Dexie (no re-upload) | Task 3 (`getSignalsForSession`, `getEventsForSession`, `getMetricsForSession`) |

### Placeholder scan

No TBD, no "implement later", all code blocks complete. ✅

### Type consistency

- `findDisplacementColumn(columnNames: string[], end: 'front'|'rear', normalised: boolean): string | null` — defined in prepare.ts, used in page with matching args ✅
- `findVelocityColumn(columnNames: string[], end: 'front'|'rear'): string | null` — consistent ✅
- `computeHistogram(data: Float32Array, bins: number, range: [number, number]): HistogramData` — called in chart components with matching signature ✅
- `prepareEventsBar(events: Record<string,unknown>[], end: 'front'|'rear'): EventsBarData` — consistent ✅
- `prepareMetricScatter(metrics, eventType: 'compression'|'rebound', end, xKey, yKey): ScatterData` — consistent ✅
- `EventsBarData` / `ScatterData` / `HistogramData` — all exported from prepare.ts, imported by chart components ✅
- `Session` — imported from `$lib/db/dexie`, used for `sessions: Session[]` ✅
