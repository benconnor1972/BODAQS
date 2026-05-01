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

	const loIdx = (loPct / 100) * (clean.length - 1);
	const hiIdx = (hiPct / 100) * (clean.length - 1);

	// Linear interpolation for percentiles
	const loLower = Math.floor(loIdx);
	const loUpper = Math.ceil(loIdx);
	const loFrac = loIdx - loLower;
	const lo = clean[loLower] * (1 - loFrac) + clean[loUpper] * loFrac;

	const hiLower = Math.floor(hiIdx);
	const hiUpper = Math.ceil(hiIdx);
	const hiFrac = hiIdx - hiLower;
	const hi = clean[hiLower] * (1 - hiFrac) + clean[hiUpper] * hiFrac;

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
