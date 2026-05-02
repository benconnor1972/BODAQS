import JSZip from "jszip";
import { db } from "$lib/db/dexie";
import type { EventRow, MetricRow, Run, Session, SignalRow } from "$lib/db/dexie";

export async function importZip(file: File): Promise<{ imported: number; skipped: number }> {
  const arrayBuffer = await file.arrayBuffer();
  const zip = await JSZip.loadAsync(arrayBuffer);
  let imported = 0;
  let skipped = 0;

  const runManifestFiles = Object.keys(zip.files).filter((path) =>
    path.match(/^runs\/[^/]+\/run_manifest\.json$/)
  );

  for (const manifestPath of runManifestFiles) {
    const manifestText = await zip.files[manifestPath].async("string");
    const manifest = JSON.parse(manifestText) as {
      run_id: string;
      description: string;
      created_at: string;
      session_ids: string[];
    };

    const existing = await db.runs.get(manifest.run_id);
    if (existing) {
      skipped++;
      continue;
    }

    const run: Run = {
      id: manifest.run_id,
      description: manifest.description,
      created_at: manifest.created_at,
      session_ids: manifest.session_ids
    };
    await db.runs.put(run);

    const runPrefix = `runs/${manifest.run_id}/sessions/`;
    const sessionFolders = new Set(
      Object.keys(zip.files)
        .filter((p) => p.startsWith(runPrefix))
        .map((p) => p.slice(runPrefix.length).split("/")[0])
        .filter(Boolean)
    );

    for (const sessionId of sessionFolders) {
      const sessionBase = `${runPrefix}${sessionId}/`;
      const sessionManifestFile = zip.files[`${sessionBase}session_manifest.json`];
      if (!sessionManifestFile) continue;

      const sessionManifestText = await sessionManifestFile.async("string");
      const sessionManifest = JSON.parse(sessionManifestText) as {
        meta: Record<string, unknown>;
        source_sha256: string;
      };

      const session: Session = {
        id: sessionId,
        run_id: manifest.run_id,
        meta: sessionManifest.meta,
        source_sha256: sessionManifest.source_sha256,
        warnings: []
      };
      await db.sessions.put(session);

      const signalsFile = zip.files[`${sessionBase}signals/signals.json`];
      if (signalsFile) {
        const signalsText = await signalsFile.async("string");
        const signalMap = JSON.parse(signalsText) as Record<string, string>;
        for (const [column_name, data] of Object.entries(signalMap)) {
          const row: SignalRow = { session_id: sessionId, column_name, data };
          await db.signals.put(row);
        }
      }

      const eventsPrefix = `${sessionBase}events/`;
      for (const [path, zipFile] of Object.entries(zip.files)) {
        if (!path.startsWith(eventsPrefix) || zipFile.dir) continue;
        const schema_id = path.slice(eventsPrefix.length).replace(/\.json$/, "");
        const rowsText = await zipFile.async("string");
        const row: EventRow = { session_id: sessionId, schema_id, rows: JSON.parse(rowsText) };
        await db.events.put(row);
      }

      const metricsPrefix = `${sessionBase}metrics/`;
      for (const [path, zipFile] of Object.entries(zip.files)) {
        if (!path.startsWith(metricsPrefix) || zipFile.dir) continue;
        const schema_id = path.slice(metricsPrefix.length).replace(/\.json$/, "");
        const rowsText = await zipFile.async("string");
        const row: MetricRow = { session_id: sessionId, schema_id, rows: JSON.parse(rowsText) };
        await db.metrics.put(row);
      }
    }

    imported++;
  }

  return { imported, skipped };
}
