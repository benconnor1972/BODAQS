import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '$lib/db/dexie';
import type { Run } from '$lib/db/dexie';
import {
	getAllRuns,
	getEventsForSession,
	getMetricsForSession,
	getSessionsForRun,
	getSignalsForSession,
	saveRun,
	saveSession
} from '$lib/db/artifacts';
import type { PreprocessResponse } from '$lib/api/preprocess';

function makeRun(id: string, created_at: string): Run {
	return { id, description: `Run ${id}`, created_at, session_ids: [] };
}

function makeResponse(session_id: string, withData = false): PreprocessResponse {
	return {
		session_id,
		meta: { source: 'test' },
		source_sha256: 'abc',
		signals: {
			column_names: withData ? ['disp'] : [],
			n_rows: withData ? 1 : 0,
			columns: withData ? { disp: btoa('\x00\x00\x80\x3f') } : {}
		},
		events: withData ? [{ type: 'bottom_out', t: 1.0 }] : [],
		metrics: withData ? [{ name: 'travel', value: 0.5 }] : [],
		warnings: []
	};
}

beforeEach(async () => {
	await db.delete();
	await db.open();
});

describe('saveRun / getAllRuns', () => {
	it('stores a run and retrieves it', async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
		const runs = await getAllRuns();
		expect(runs).toHaveLength(1);
		expect(runs[0].id).toBe('run-1');
	});

	it('returns runs newest-first by created_at', async () => {
		await saveRun(makeRun('run-a', '2026-01-01T00:00:00Z'));
		await saveRun(makeRun('run-b', '2026-02-01T00:00:00Z'));
		const runs = await getAllRuns();
		expect(runs[0].id).toBe('run-b');
		expect(runs[1].id).toBe('run-a');
	});

	it('upserts on repeated saveRun with same id', async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
		await saveRun({ id: 'run-1', description: 'Updated', created_at: '2026-01-01T00:00:00Z', session_ids: [] });
		const runs = await getAllRuns();
		expect(runs).toHaveLength(1);
		expect(runs[0].description).toBe('Updated');
	});
});

describe('saveSession', () => {
	beforeEach(async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
	});

	it('persists session with meta and sha256', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		const sessions = await getSessionsForRun('run-1');
		expect(sessions).toHaveLength(1);
		expect(sessions[0].id).toBe('sess-1');
		expect(sessions[0].meta).toEqual({ source: 'test' });
		expect(sessions[0].source_sha256).toBe('abc');
	});

	it('persists signals', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const signals = await getSignalsForSession('sess-1');
		expect(signals).toHaveLength(1);
		expect(signals[0].column_name).toBe('disp');
	});

	it('persists events', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const events = await getEventsForSession('sess-1');
		expect(events).toHaveLength(1);
		expect(events[0].schema_id).toBe('default');
		expect(events[0].rows).toHaveLength(1);
	});

	it('persists metrics', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const metrics = await getMetricsForSession('sess-1');
		expect(metrics).toHaveLength(1);
		expect(metrics[0].schema_id).toBe('default');
	});

	it('skips events and metrics rows when arrays are empty', async () => {
		await saveSession('run-1', makeResponse('sess-1', false));
		const events = await getEventsForSession('sess-1');
		const metrics = await getMetricsForSession('sess-1');
		expect(events).toHaveLength(0);
		expect(metrics).toHaveLength(0);
	});

	it('updates Run.session_ids to include the new session', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		const runs = await getAllRuns();
		expect(runs[0].session_ids).toContain('sess-1');
	});

	it('does not duplicate session_ids on repeated saveSession', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		await saveSession('run-1', makeResponse('sess-1'));
		const runs = await getAllRuns();
		expect(runs[0].session_ids.filter((id) => id === 'sess-1')).toHaveLength(1);
	});
});

describe('getSessionsForRun', () => {
	it('returns empty array for unknown run', async () => {
		const sessions = await getSessionsForRun('nonexistent');
		expect(sessions).toHaveLength(0);
	});

	it('returns only sessions belonging to the requested run', async () => {
		await saveRun(makeRun('run-2', '2026-02-01T00:00:00Z'));
		await saveSession('run-1', makeResponse('sess-a'));
		await saveSession('run-2', makeResponse('sess-b'));
		const sessionsForRun1 = await getSessionsForRun('run-1');
		expect(sessionsForRun1.every((s) => s.run_id === 'run-1')).toBe(true);
	});
});
