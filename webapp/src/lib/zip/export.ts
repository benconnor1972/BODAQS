import JSZip from 'jszip';
import { db } from '../db/dexie';
import type { LibraryRun } from '../stores/library';

function float32ToBase64(arr: Float32Array): string {
  const bytes = new Uint8Array(arr.buffer);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

export async function exportRunsToZip(runs: LibraryRun[]): Promise<Blob> {
  const zip = new JSZip();

  for (const run of runs) {
    const runDir = zip.folder(`runs/${run.run_id}`)!;
    runDir.file(
      'run_manifest.json',
      JSON.stringify(
        {
          run_id: run.run_id,
          description: run.description,
          created_at: run.created_at,
          session_ids: run.session_ids,
        },
        null,
        2
      )
    );

    for (const sessionId of run.session_ids) {
      const sessionKey = `${run.run_id}::${sessionId}`;
      const sessionDir = runDir.folder(`sessions/${sessionId}`)!;

      const session = await db.sessions.get(sessionKey);
      if (session) {
        sessionDir.file('session_manifest.json', JSON.stringify(session.manifest, null, 2));
      }

      const eventsRows = await db.events.where('session_key').equals(sessionKey).toArray();
      for (const e of eventsRows) {
        sessionDir.file(`events/${e.schema_id}.json`, JSON.stringify(e.rows, null, 2));
      }

      const metricsRows = await db.metrics.where('session_key').equals(sessionKey).toArray();
      for (const m of metricsRows) {
        sessionDir.file(`metrics/${m.schema_id}.json`, JSON.stringify(m.rows, null, 2));
      }

      const signals = await db.signals.get(sessionKey);
      if (signals) {
        const sigObj: Record<string, string> = {};
        for (const [col, arr] of Object.entries(signals.columns)) {
          sigObj[col] = float32ToBase64(arr);
        }
        sessionDir.file('signals/signals.json', JSON.stringify(sigObj, null, 2));
      }
    }
  }

  return zip.generateAsync({
    type: 'blob',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  });
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
