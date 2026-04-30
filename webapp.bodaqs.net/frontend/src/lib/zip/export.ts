import JSZip from 'jszip';
import {
	getEventsForSession,
	getMetricsForSession,
	getSessionsForRun,
	getSignalsForSession
} from '$lib/db/artifacts';
import type { Run } from '$lib/db/dexie';

export async function exportRuns(runs: Run[]): Promise<Blob> {
	const zip = new JSZip();

	for (const run of runs) {
		const runFolder = zip.folder(`runs/${run.id}`);
		if (!runFolder) continue;

		runFolder.file(
			'run_manifest.json',
			JSON.stringify(
				{
					run_id: run.id,
					description: run.description,
					created_at: run.created_at,
					session_ids: run.session_ids
				},
				null,
				2
			)
		);

		const sessions = await getSessionsForRun(run.id);
		for (const session of sessions) {
			const sessionFolder = runFolder.folder(`sessions/${session.id}`);
			if (!sessionFolder) continue;

			sessionFolder.file(
				'session_manifest.json',
				JSON.stringify({ meta: session.meta, source_sha256: session.source_sha256 }, null, 2)
			);

			const signals = await getSignalsForSession(session.id);
			const signalMap: Record<string, string> = {};
			for (const s of signals) signalMap[s.column_name] = s.data;
			sessionFolder.file('signals/signals.json', JSON.stringify(signalMap, null, 2));

			const events = await getEventsForSession(session.id);
			for (const e of events) {
				sessionFolder.file(`events/${e.schema_id}.json`, JSON.stringify(e.rows, null, 2));
			}

			const metrics = await getMetricsForSession(session.id);
			for (const m of metrics) {
				sessionFolder.file(`metrics/${m.schema_id}.json`, JSON.stringify(m.rows, null, 2));
			}
		}
	}

	return zip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
}
