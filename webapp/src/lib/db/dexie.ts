import Dexie, { type Table } from 'dexie';

export interface StoredRun {
  run_id: string;
  created_at: string;
  description: string;
  session_ids: string[];
}

export interface StoredSession {
  session_key: string;
  run_id: string;
  session_id: string;
  manifest: Record<string, unknown>;
  signals_meta: { column_names: string[]; n_rows: number };
}

export interface StoredSignals {
  session_key: string;
  columns: Record<string, Float32Array>;
}

export interface StoredEvents {
  session_key: string;
  schema_id: string;
  rows: Record<string, unknown>[];
}

export interface StoredMetrics {
  session_key: string;
  schema_id: string;
  rows: Record<string, unknown>[];
}

export class BodaqsDB extends Dexie {
  runs!: Table<StoredRun>;
  sessions!: Table<StoredSession>;
  signals!: Table<StoredSignals>;
  events!: Table<StoredEvents>;
  metrics!: Table<StoredMetrics>;

  constructor() {
    super('bodaqs');
    this.version(1).stores({
      runs: 'run_id',
      sessions: 'session_key, run_id',
      signals: 'session_key',
      events: '[session_key+schema_id], session_key',
      metrics: '[session_key+schema_id], session_key',
    });
  }
}

export const db = new BodaqsDB();
