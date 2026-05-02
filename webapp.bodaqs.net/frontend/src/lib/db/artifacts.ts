import type { PreprocessResponse } from "$lib/api/preprocess";
import { db, type EventRow, type MetricRow, type Run, type Session, type SignalRow } from "./dexie";

export async function saveRun(run: Run): Promise<void> {
  await db.runs.put(run);
}

export async function saveSession(run_id: string, response: PreprocessResponse): Promise<void> {
  const session: Session = {
    id: response.session_id,
    run_id,
    meta: response.meta,
    source_sha256: response.source_sha256,
    warnings: response.warnings
  };
  await db.sessions.put(session);

  const run = await db.runs.get(run_id);
  if (run && !run.session_ids.includes(response.session_id)) {
    await db.runs.update(run_id, { session_ids: [...run.session_ids, response.session_id] });
  }

  for (const [column_name, data] of Object.entries(response.signals.columns)) {
    const row: SignalRow = { session_id: response.session_id, column_name, data };
    await db.signals.put(row);
  }

  if (response.events.length > 0) {
    const eventRow: EventRow = {
      session_id: response.session_id,
      schema_id: "default",
      rows: response.events
    };
    await db.events.put(eventRow);
  }

  if (response.metrics.length > 0) {
    const metricRow: MetricRow = {
      session_id: response.session_id,
      schema_id: "default",
      rows: response.metrics
    };
    await db.metrics.put(metricRow);
  }
}

export async function getAllRuns(): Promise<Run[]> {
  return db.runs.orderBy("created_at").reverse().toArray();
}

export async function getSessionsForRun(run_id: string): Promise<Session[]> {
  return db.sessions.where("run_id").equals(run_id).toArray();
}

export async function getSignalsForSession(session_id: string): Promise<SignalRow[]> {
  return db.signals.where("session_id").equals(session_id).toArray();
}

export async function getEventsForSession(session_id: string): Promise<EventRow[]> {
  return db.events.where("session_id").equals(session_id).toArray();
}

export async function getMetricsForSession(session_id: string): Promise<MetricRow[]> {
  return db.metrics.where("session_id").equals(session_id).toArray();
}
