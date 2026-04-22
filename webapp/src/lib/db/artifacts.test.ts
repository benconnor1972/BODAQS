import 'fake-indexeddb/auto';
import { describe, it, expect, beforeEach } from 'vitest';
import { BodaqsDB } from './dexie';

let db: BodaqsDB;

beforeEach(async () => {
  db = new BodaqsDB();
  await db.open();
});

describe('BodaqsDB schema', () => {
  it('opens without error', async () => {
    expect(db.isOpen()).toBe(true);
  });

  it('can store and retrieve a session', async () => {
    await db.sessions.put({
      session_key: 'run_001::session_001',
      run_id: 'run_001',
      session_id: 'session_001',
      manifest: { source_sha256: 'abc' },
      signals_meta: { column_names: ['time_s'], n_rows: 100 },
    });
    const s = await db.sessions.get('run_001::session_001');
    expect(s?.session_id).toBe('session_001');
  });

  it('can store and retrieve events by session_key', async () => {
    await db.events.put({
      session_key: 'run_001::session_001',
      schema_id: 'schema_v1',
      rows: [{ event_name: 'bump', start_time_s: 1.0 }],
    });
    const evs = await db.events.where('session_key').equals('run_001::session_001').toArray();
    expect(evs).toHaveLength(1);
    expect(evs[0].rows[0].event_name).toBe('bump');
  });
});
