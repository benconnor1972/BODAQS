import JSZip from 'jszip';
import { db } from '../db/dexie';
import { libraryStore } from '../stores/library';

export interface ZipRunPreview {
  run_id: string;
  description: string;
  created_at: string;
  session_ids: string[];
  estimated_size_mb: number;
}

export async function previewZip(file: File): Promise<ZipRunPreview[]> {
  const zip = await JSZip.loadAsync(file);
  const previews: ZipRunPreview[] = [];

  for (const [path, zipEntry] of Object.entries(zip.files)) {
    if (!path.match(/^runs\/[^/]+\/run_manifest\.json$/)) continue;

    const raw = await zipEntry.async('string');
    const manifest = JSON.parse(raw) as {
      run_id: string;
      description?: string;
      created_at?: string;
      session_ids?: string[];
    };

    const runPrefix = path.replace('run_manifest.json', '');
    const signalFiles = Object.keys(zip.files).filter(
      (p) => p.startsWith(runPrefix) && p.includes('/signals/')
    );
    const sizes = await Promise.all(
      signalFiles.map((p) => zip.files[p].async('uint8array').then((b) => b.length))
    );
    const mb = sizes.reduce((a, b) => a + b, 0) / 1_000_000;

    previews.push({
      run_id: manifest.run_id,
      description: manifest.description ?? '',
      created_at: manifest.created_at ?? '',
      session_ids: manifest.session_ids ?? [],
      estimated_size_mb: Math.round(mb * 10) / 10,
    });
  }

  return previews;
}

export async function importSelectedRuns(
  file: File,
  selectedRunIds: string[]
): Promise<{ imported: number; skipped: number }> {
  const zip = await JSZip.loadAsync(file);
  let imported = 0;
  let skipped = 0;

  for (const runId of selectedRunIds) {
    const existing = await db.runs.get(runId);
    if (existing) {
      skipped++;
      continue;
    }

    const manifestEntry = zip.files[`runs/${runId}/run_manifest.json`];
    if (!manifestEntry) continue;

    const runManifest = JSON.parse(await manifestEntry.async('string')) as {
      run_id: string;
      description: string;
      created_at: string;
      session_ids: string[];
    };

    await db.runs.put({
      run_id: runManifest.run_id,
      description: runManifest.description,
      created_at: runManifest.created_at,
      session_ids: runManifest.session_ids,
    });

    for (const sessionId of runManifest.session_ids) {
      const prefix = `runs/${runId}/sessions/${sessionId}`;
      const sessionKey = `${runId}::${sessionId}`;

      const sessionManifestEntry = zip.files[`${prefix}/session_manifest.json`];
      if (sessionManifestEntry) {
        const manifest = JSON.parse(await sessionManifestEntry.async('string')) as Record<string, unknown>;
        await db.sessions.put({
          session_key: sessionKey,
          run_id: runId,
          session_id: sessionId,
          manifest,
          signals_meta: { column_names: [], n_rows: 0 },
        });
      }

      for (const [path, zipEntry] of Object.entries(zip.files)) {
        if (!path.startsWith(`${prefix}/events/`) || !path.endsWith('.json')) continue;
        const schemaId = path.split('/').pop()!.replace('.json', '');
        const rows = JSON.parse(await zipEntry.async('string')) as Record<string, unknown>[];
        await db.events.put({ session_key: sessionKey, schema_id: schemaId, rows });
      }

      for (const [path, zipEntry] of Object.entries(zip.files)) {
        if (!path.startsWith(`${prefix}/metrics/`) || !path.endsWith('.json')) continue;
        const schemaId = path.split('/').pop()!.replace('.json', '');
        const rows = JSON.parse(await zipEntry.async('string')) as Record<string, unknown>[];
        await db.metrics.put({ session_key: sessionKey, schema_id: schemaId, rows });
      }

      const sigEntry = zip.files[`${prefix}/signals/signals.json`];
      if (sigEntry) {
        const sigMap = JSON.parse(await sigEntry.async('string')) as Record<string, string>;
        const columns: Record<string, Float32Array> = {};
        for (const [col, b64] of Object.entries(sigMap)) {
          const binary = atob(b64);
          const buf = new ArrayBuffer(binary.length);
          const view = new Uint8Array(buf);
          for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
          columns[col] = new Float32Array(buf);
        }
        await db.signals.put({ session_key: sessionKey, columns });
      }

      libraryStore.addSessionToRun(runId, sessionId, '');
    }

    imported++;
  }

  return { imported, skipped };
}
