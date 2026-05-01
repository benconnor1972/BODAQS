import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '$lib/db/dexie';
import type { Run } from '$lib/db/dexie';
import { getAllRuns, getSignalsForSession, saveRun, saveSession } from '$lib/db/artifacts';
import { exportRuns } from '$lib/zip/export';
import { importZip } from '$lib/zip/import';
import { decodeSignalColumn } from '$lib/api/preprocess';
import type { PreprocessResponse } from '$lib/api/preprocess';

function encodeFloat32LE(values: number[]): string {
	const bytes = new Uint8Array(new Float32Array(values).buffer);
	let binary = '';
	for (const b of bytes) binary += String.fromCharCode(b);
	return btoa(binary);
}

function makeRun(id: string): Run {
	return { id, description: `Run ${id}`, created_at: '2026-01-01T00:00:00Z', session_ids: [] };
}

function makeResponse(session_id: string, signalValues: number[]): PreprocessResponse {
	return {
		session_id,
		meta: { source: 'test' },
		source_sha256: 'sha-test',
		signals: {
			column_names: ['disp [mm]'],
			n_rows: signalValues.length,
			columns: { 'disp [mm]': encodeFloat32LE(signalValues) }
		},
		events: [],
		metrics: [],
		warnings: []
	};
}

beforeEach(async () => {
	await db.delete();
	await db.open();
});

describe('exportRuns / importZip round-trip', () => {
	it('produces a non-empty Blob', async () => {
		await saveRun(makeRun('run-1'));
		const runs = await getAllRuns();
		const blob = await exportRuns(runs);
		expect(blob.size).toBeGreaterThan(0);
	});

	it('preserves signal values through float32 precision', async () => {
		const originalValues = [1.0, 2.5, -3.125, 0.0, 100.25];
		await saveRun(makeRun('run-1'));
		await saveSession('run-1', makeResponse('sess-1', originalValues));

		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		// clear db and re-import
		await db.delete();
		await db.open();

		const arrayBuffer = await blob.arrayBuffer();
		const file = new File([arrayBuffer], 'export.bodaqs.zip', { type: 'application/zip' });
		const result = await importZip(file);
		expect(result.imported).toBe(1);
		expect(result.skipped).toBe(0);

		const signals = await getSignalsForSession('sess-1');
		expect(signals).toHaveLength(1);
		const decoded = decodeSignalColumn(signals[0].data);
		expect(decoded).toHaveLength(originalValues.length);
		for (let i = 0; i < originalValues.length; i++) {
			expect(decoded[i]).toBeCloseTo(originalValues[i], 4);
		}
	});

	it('restores run metadata and session_ids', async () => {
		await saveRun(makeRun('run-1'));
		await saveSession('run-1', makeResponse('sess-1', [1.0]));

		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		await db.delete();
		await db.open();

		const arrayBuffer = await blob.arrayBuffer();
		const file = new File([arrayBuffer], 'export.bodaqs.zip');
		await importZip(file);

		const importedRuns = await getAllRuns();
		expect(importedRuns[0].id).toBe('run-1');
		expect(importedRuns[0].description).toBe('Run run-1');
		expect(importedRuns[0].session_ids).toContain('sess-1');
	});

	it('skips a run that already exists in the db (matched by run_id)', async () => {
		await saveRun(makeRun('run-1'));
		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		// run-1 is still in db — re-import should skip it
		const arrayBuffer = await blob.arrayBuffer();
		const file = new File([arrayBuffer], 'export.bodaqs.zip');
		const result = await importZip(file);
		expect(result.skipped).toBe(1);
		expect(result.imported).toBe(0);
	});

	it('exports an empty run list as a valid ZIP with no run entries', async () => {
		const blob = await exportRuns([]);
		expect(blob.size).toBeGreaterThan(0); // valid ZIP even with no content
		const arrayBuffer = await blob.arrayBuffer();
		const file = new File([arrayBuffer], 'empty.bodaqs.zip');
		const result = await importZip(file);
		expect(result.imported).toBe(0);
		expect(result.skipped).toBe(0);
	});
});
