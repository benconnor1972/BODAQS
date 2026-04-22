import { db } from './dexie';
import type { PreprocessResponse } from '../api/preprocess';

export function decodeSignalColumns(
  response: PreprocessResponse
): Record<string, Float32Array> {
  const result: Record<string, Float32Array> = {};
  for (const [col, b64] of Object.entries(response.signals.columns)) {
    const binary = atob(b64);
    const buf = new ArrayBuffer(binary.length);
    const view = new Uint8Array(buf);
    for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
    result[col] = new Float32Array(buf);
  }
  return result;
}

export async function storePreprocessResult(
  runId: string,
  response: PreprocessResponse
): Promise<void> {
  const sessionKey = `${runId}::${response.session_id}`;

  await db.transaction('rw', [db.sessions, db.signals, db.events, db.metrics], async () => {
    await db.sessions.put({
      session_key: sessionKey,
      run_id: runId,
      session_id: response.session_id,
      manifest: { meta: response.meta, source_sha256: response.source_sha256 },
      signals_meta: {
        column_names: response.signals.column_names,
        n_rows: response.signals.n_rows,
      },
    });

    await db.signals.put({
      session_key: sessionKey,
      columns: decodeSignalColumns(response),
    });

    const schemaIds = [...new Set(response.events.map((e) => String(e.schema_id)))];
    for (const schemaId of schemaIds) {
      await db.events.put({
        session_key: sessionKey,
        schema_id: schemaId,
        rows: response.events.filter((e) => String(e.schema_id) === schemaId),
      });
      await db.metrics.put({
        session_key: sessionKey,
        schema_id: schemaId,
        rows: response.metrics.filter((m) => String(m.schema_id) === schemaId),
      });
    }
  });
}
