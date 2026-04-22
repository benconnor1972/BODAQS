import 'fake-indexeddb/auto';
import { describe, it, expect, beforeEach } from 'vitest';
import { BodaqsDB, db as sharedDb } from './dexie';
import { decodeSignalColumns, storePreprocessResult } from './artifacts';
import type { PreprocessResponse } from '../api/preprocess';

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

describe('decodeSignalColumns', () => {
  it('decodes base64 float32 to Float32Array', () => {
    const arr = new Float32Array([1.0, 2.5, 3.14]);
    const bytes = new Uint8Array(arr.buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const b64 = btoa(binary);

    const result = decodeSignalColumns({
      session_id: 's',
      meta: {},
      source_sha256: '',
      signals: { column_names: ['x'], n_rows: 3, columns: { x: b64 } },
      events: [],
      metrics: [],
    });
    expect(result['x'][0]).toBeCloseTo(1.0);
    expect(result['x'][1]).toBeCloseTo(2.5);
    expect(result['x'].length).toBe(3);
  });
});

describe('storePreprocessResult', () => {
  it('writes session and events to IndexedDB', async () => {
    const arr = new Float32Array([0.0, 0.1]);
    const bytes = new Uint8Array(arr.buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const b64 = btoa(binary);

    const response: PreprocessResponse = {
      session_id: 'sess_abc',
      meta: { sample_rate_hz: 200 },
      source_sha256: 'sha123',
      signals: { column_names: ['time_s'], n_rows: 2, columns: { time_s: b64 } },
      events: [{ schema_id: 'schema_v1', event_name: 'bump', event_id: 1 }],
      metrics: [{ schema_id: 'schema_v1', event_id: 1, m_travel: 0.5 }],
    };

    await storePreprocessResult('run_001', response);

    const session = await sharedDb.sessions.get('run_001::sess_abc');
    expect(session?.session_id).toBe('sess_abc');

    const events = await sharedDb.events.where('session_key').equals('run_001::sess_abc').toArray();
    expect(events).toHaveLength(1);
    expect(events[0].rows[0].event_name).toBe('bump');
  });
});
