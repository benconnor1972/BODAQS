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

	it('places value exactly at range max in the last bin', () => {
		const data = new Float32Array([0, 5, 10]);
		const result = computeHistogram(data, 2, [0, 10]);
		expect(result.counts[0]).toBe(1); // 0 → bin 0
		expect(result.counts[1]).toBe(2); // 5 and 10 → bin 1 (10 is clamped)
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

	it('returns empty when no events', () => {
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
