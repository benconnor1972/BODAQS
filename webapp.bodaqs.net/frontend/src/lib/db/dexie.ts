import Dexie, { type EntityTable } from "dexie";

export interface Run {
  id: string; // run_id: user-supplied or auto UUID
  description: string;
  created_at: string; // ISO 8601
  session_ids: string[];
}

export interface Session {
  id: string; // session_id from backend (e.g. "2026-04-29_11-16-50")
  run_id: string;
  meta: Record<string, unknown>;
  source_sha256: string;
  warnings: string[];
}

export interface SignalRow {
  id?: number; // auto-increment PK
  session_id: string;
  column_name: string;
  data: string; // base64 float32 LE
}

export interface EventRow {
  id?: number;
  session_id: string;
  schema_id: string;
  rows: Record<string, unknown>[];
}

export interface MetricRow {
  id?: number;
  session_id: string;
  schema_id: string;
  rows: Record<string, unknown>[];
}

export class BodaqsDB extends Dexie {
  runs!: EntityTable<Run, "id">;
  sessions!: EntityTable<Session, "id">;
  signals!: EntityTable<SignalRow, "id">;
  events!: EntityTable<EventRow, "id">;
  metrics!: EntityTable<MetricRow, "id">;

  constructor() {
    super("bodaqs");
    this.version(1).stores({
      runs: "id, created_at",
      sessions: "id, run_id",
      signals: "++id, session_id, column_name",
      events: "++id, session_id, schema_id",
      metrics: "++id, session_id, schema_id"
    });
  }
}

export const db = new BodaqsDB();
