# Phase 3 — Core Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate the Phase 2 data layer skeletons with a full vitest test suite (Dexie round-trips, ZIP export/import fidelity, API type shape), make the library landing page functional, and fix the inaccurate SESSION.md Phase 2 file listing.

**Architecture:** Three test files targeting the three lib modules that do real work (api, db, zip). Tests use `fake-indexeddb@^6` to give Dexie a real in-memory IndexedDB implementation inside Vitest's jsdom environment. Each test file imports `fake-indexeddb/auto` as its first line so the global is patched before any Dexie code runs. The landing page calls `libraryStore.load()` on mount via `onMount` (browser-only guard), then renders a list or empty state.

**Tech Stack:** Vitest 4, fake-indexeddb 6, Dexie 4, JSZip 3, SvelteKit 5 runes mode.

---

## File Map

### New files

| File | Responsibility |
|---|---|
| `frontend/src/lib/api/preprocess.test.ts` | `decodeSignalColumn` correctness + `PreprocessResponse` type shape |
| `frontend/src/lib/db/artifacts.test.ts` | `saveRun`, `saveSession`, `getAllRuns`, query helpers — Dexie round-trip |
| `frontend/src/lib/zip/export.test.ts` | `exportRuns` + `importZip` round-trip including signal float32 fidelity, duplicate-skip |

### Modified files

| File | Change |
|---|---|
| `frontend/package.json` | Add `fake-indexeddb@^6.0.0` to devDependencies |
| `frontend/src/routes/+page.svelte` | Replace placeholder with functional run library list |
| `webapp.bodaqs.net/SESSION.md` | Fix Phase 2 file structure (subagent hallucinated wrong paths) |

---

## Task 1: Install `fake-indexeddb` + write `preprocess.test.ts`

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/src/lib/api/preprocess.test.ts`

### Why fake-indexeddb?

Dexie uses IndexedDB, which is not available in Node.js (Vitest runs in Node). `fake-indexeddb` provides a full in-memory IndexedDB implementation. Importing `fake-indexeddb/auto` at the top of a test file patches `globalThis.indexedDB` and `globalThis.IDBKeyRange` before any other code runs, which is all Dexie needs.

- [ ] **Step 1: Add `fake-indexeddb` to devDependencies**

Edit `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/package.json`. In `devDependencies`, add:

```json
"fake-indexeddb": "^6.0.0"
```

Then install:

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm install
```

Expected: exits 0, `fake-indexeddb` appears in `node_modules/`.

- [ ] **Step 2: Write `preprocess.test.ts`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/api/preprocess.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { PreprocessResponse } from '$lib/api/preprocess';
import { decodeSignalColumn } from '$lib/api/preprocess';

function encodeFloat32LE(values: number[]): string {
	const bytes = new Uint8Array(new Float32Array(values).buffer);
	let binary = '';
	for (const b of bytes) binary += String.fromCharCode(b);
	return btoa(binary);
}

describe('decodeSignalColumn', () => {
	it('returns a Float32Array', () => {
		const result = decodeSignalColumn(encodeFloat32LE([1.0]));
		expect(result).toBeInstanceOf(Float32Array);
	});

	it('decodes a single float32 value', () => {
		const result = decodeSignalColumn(encodeFloat32LE([1.0]));
		expect(result).toHaveLength(1);
		expect(result[0]).toBeCloseTo(1.0, 6);
	});

	it('decodes multiple values including negative and fractional', () => {
		const values = [0.0, -1.5, 100.25];
		const result = decodeSignalColumn(encodeFloat32LE(values));
		expect(result).toHaveLength(3);
		expect(result[0]).toBeCloseTo(0.0, 6);
		expect(result[1]).toBeCloseTo(-1.5, 5);
		expect(result[2]).toBeCloseTo(100.25, 4);
	});

	it('round-trips through the backend encoding contract (LE byte order)', () => {
		// Float32 1.0 is bytes: 00 00 80 3F (little-endian)
		const base64 = btoa(String.fromCharCode(0x00, 0x00, 0x80, 0x3f));
		const result = decodeSignalColumn(base64);
		expect(result[0]).toBeCloseTo(1.0, 6);
	});
});

describe('PreprocessResponse type shape', () => {
	it('accepts a well-formed response object', () => {
		const response: PreprocessResponse = {
			session_id: '2026-04-29_11-16-50',
			meta: { filename: 'ride.csv', duration_s: 600 },
			source_sha256: 'abc123def456',
			signals: {
				column_names: ['front_wheel_disp_dom_wheel [mm]'],
				n_rows: 12345,
				columns: { 'front_wheel_disp_dom_wheel [mm]': 'AAAA' }
			},
			events: [{ type: 'bottom_out', t: 1.5, end_t: 2.0 }],
			metrics: [{ name: 'max_travel', value: 150.0 }],
			warnings: ['rear signal missing']
		};
		expect(response.session_id).toBe('2026-04-29_11-16-50');
		expect(response.signals.column_names).toHaveLength(1);
		expect(response.signals.n_rows).toBe(12345);
		expect(response.events).toHaveLength(1);
		expect(response.warnings).toHaveLength(1);
	});

	it('accepts an empty signals/events/metrics response (partial result)', () => {
		const response: PreprocessResponse = {
			session_id: 'partial',
			meta: {},
			source_sha256: '',
			signals: { column_names: [], n_rows: 0, columns: {} },
			events: [],
			metrics: [],
			warnings: ['no signals found']
		};
		expect(response.signals.column_names).toHaveLength(0);
		expect(response.warnings).toHaveLength(1);
	});
});
```

- [ ] **Step 3: Run the tests to verify they pass**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/api/preprocess.test.ts
```

Expected output: `7 tests passed`.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/package.json webapp.bodaqs.net/frontend/package-lock.json webapp.bodaqs.net/frontend/src/lib/api/preprocess.test.ts
git commit -m "test(frontend): add preprocess API type and decoding tests"
```

---

## Task 2: `db/artifacts.test.ts`

**Files:**
- Create: `frontend/src/lib/db/artifacts.test.ts`

### Key Dexie testing pattern

`fake-indexeddb/auto` must be the first import. Between tests, call `db.delete()` then `db.open()` to start with an empty schema — this avoids data leaking between tests. The `db` singleton from `dexie.ts` is reused; Dexie handles reopen after delete.

- [ ] **Step 1: Write `artifacts.test.ts`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/db/artifacts.test.ts`:

```ts
import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '$lib/db/dexie';
import type { Run } from '$lib/db/dexie';
import {
	getAllRuns,
	getEventsForSession,
	getMetricsForSession,
	getSessionsForRun,
	getSignalsForSession,
	saveRun,
	saveSession
} from '$lib/db/artifacts';
import type { PreprocessResponse } from '$lib/api/preprocess';

function makeRun(id: string, created_at: string): Run {
	return { id, description: `Run ${id}`, created_at, session_ids: [] };
}

function makeResponse(session_id: string, withData = false): PreprocessResponse {
	return {
		session_id,
		meta: { source: 'test' },
		source_sha256: 'abc',
		signals: {
			column_names: withData ? ['disp'] : [],
			n_rows: withData ? 1 : 0,
			columns: withData ? { disp: btoa('\x00\x00\x80\x3f') } : {}
		},
		events: withData ? [{ type: 'bottom_out', t: 1.0 }] : [],
		metrics: withData ? [{ name: 'travel', value: 0.5 }] : [],
		warnings: []
	};
}

beforeEach(async () => {
	await db.delete();
	await db.open();
});

describe('saveRun / getAllRuns', () => {
	it('stores a run and retrieves it', async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
		const runs = await getAllRuns();
		expect(runs).toHaveLength(1);
		expect(runs[0].id).toBe('run-1');
	});

	it('returns runs newest-first by created_at', async () => {
		await saveRun(makeRun('run-a', '2026-01-01T00:00:00Z'));
		await saveRun(makeRun('run-b', '2026-02-01T00:00:00Z'));
		const runs = await getAllRuns();
		expect(runs[0].id).toBe('run-b');
		expect(runs[1].id).toBe('run-a');
	});

	it('upserts on repeated saveRun with same id', async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
		await saveRun({ id: 'run-1', description: 'Updated', created_at: '2026-01-01T00:00:00Z', session_ids: [] });
		const runs = await getAllRuns();
		expect(runs).toHaveLength(1);
		expect(runs[0].description).toBe('Updated');
	});
});

describe('saveSession', () => {
	beforeEach(async () => {
		await saveRun(makeRun('run-1', '2026-01-01T00:00:00Z'));
	});

	it('persists session with meta and sha256', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		const sessions = await getSessionsForRun('run-1');
		expect(sessions).toHaveLength(1);
		expect(sessions[0].id).toBe('sess-1');
		expect(sessions[0].meta).toEqual({ source: 'test' });
		expect(sessions[0].source_sha256).toBe('abc');
	});

	it('persists signals', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const signals = await getSignalsForSession('sess-1');
		expect(signals).toHaveLength(1);
		expect(signals[0].column_name).toBe('disp');
	});

	it('persists events', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const events = await getEventsForSession('sess-1');
		expect(events).toHaveLength(1);
		expect(events[0].schema_id).toBe('default');
		expect(events[0].rows).toHaveLength(1);
	});

	it('persists metrics', async () => {
		await saveSession('run-1', makeResponse('sess-1', true));
		const metrics = await getMetricsForSession('sess-1');
		expect(metrics).toHaveLength(1);
		expect(metrics[0].schema_id).toBe('default');
	});

	it('skips events and metrics rows when arrays are empty', async () => {
		await saveSession('run-1', makeResponse('sess-1', false));
		const events = await getEventsForSession('sess-1');
		const metrics = await getMetricsForSession('sess-1');
		expect(events).toHaveLength(0);
		expect(metrics).toHaveLength(0);
	});

	it('updates Run.session_ids to include the new session', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		const runs = await getAllRuns();
		expect(runs[0].session_ids).toContain('sess-1');
	});

	it('does not duplicate session_ids on repeated saveSession', async () => {
		await saveSession('run-1', makeResponse('sess-1'));
		await saveSession('run-1', makeResponse('sess-1'));
		const runs = await getAllRuns();
		expect(runs[0].session_ids.filter((id) => id === 'sess-1')).toHaveLength(1);
	});
});

describe('getSessionsForRun', () => {
	it('returns empty array for unknown run', async () => {
		const sessions = await getSessionsForRun('nonexistent');
		expect(sessions).toHaveLength(0);
	});

	it('returns only sessions belonging to the requested run', async () => {
		await saveRun(makeRun('run-2', '2026-02-01T00:00:00Z'));
		await saveSession('run-1', makeResponse('sess-a'));
		await saveSession('run-2', makeResponse('sess-b'));
		const sessionsForRun1 = await getSessionsForRun('run-1');
		expect(sessionsForRun1.every((s) => s.run_id === 'run-1')).toBe(true);
	});
});
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/db/artifacts.test.ts
```

Expected: `10 tests passed`.

- [ ] **Step 3: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/db/artifacts.test.ts
git commit -m "test(frontend): add Dexie artifacts round-trip tests"
```

---

## Task 3: `zip/export.test.ts`

**Files:**
- Create: `frontend/src/lib/zip/export.test.ts`

### What this covers

- A run with one session and one signal column is exported to a ZIP Blob
- The Blob is re-imported into a freshly cleared Dexie — signal values survive with float32 precision
- Re-importing the same export into a non-empty db skips the duplicate

### Signal round-trip helper

The test encodes `number[]` → `Float32Array` → base64 (LE), calls `exportRuns`, clears db, calls `importZip`, then reads back via `getSignalsForSession` + `decodeSignalColumn` and checks `toBeCloseTo` (float32 has ~7 sig figs of precision).

- [ ] **Step 1: Write `export.test.ts`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/zip/export.test.ts`:

```ts
import 'fake-indexeddb/auto';
import { beforeEach, describe, expect, it } from 'vitest';
import { db } from '$lib/db/dexie';
import type { Run } from '$lib/db/dexie';
import { getAllRuns, getSignalsForSession, saveRun, saveSession } from '$lib/db/artifacts';
import { exportRuns } from '$lib/zip/export';
import { importZip } from '$lib/zip/import';
import { decodeSignalColumn } from '$lib/api/preprocess';
import type { PreprocessResponse } from '$lib/api/preprocess';

function encodeFloat32LE(values: number[]): string {
	const bytes = new Uint8Array(new Float32Array(values).buffer);
	let binary = '';
	for (const b of bytes) binary += String.fromCharCode(b);
	return btoa(binary);
}

function makeRun(id: string): Run {
	return { id, description: `Run ${id}`, created_at: '2026-01-01T00:00:00Z', session_ids: [] };
}

function makeResponse(session_id: string, signalValues: number[]): PreprocessResponse {
	return {
		session_id,
		meta: { source: 'test' },
		source_sha256: 'sha-test',
		signals: {
			column_names: ['disp [mm]'],
			n_rows: signalValues.length,
			columns: { 'disp [mm]': encodeFloat32LE(signalValues) }
		},
		events: [],
		metrics: [],
		warnings: []
	};
}

beforeEach(async () => {
	await db.delete();
	await db.open();
});

describe('exportRuns / importZip round-trip', () => {
	it('produces a non-empty Blob', async () => {
		await saveRun(makeRun('run-1'));
		const runs = await getAllRuns();
		const blob = await exportRuns(runs);
		expect(blob.size).toBeGreaterThan(0);
	});

	it('preserves signal values through float32 precision', async () => {
		const originalValues = [1.0, 2.5, -3.125, 0.0, 100.25];
		await saveRun(makeRun('run-1'));
		await saveSession('run-1', makeResponse('sess-1', originalValues));

		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		// clear db and re-import
		await db.delete();
		await db.open();

		const file = new File([blob], 'export.bodaqs.zip', { type: 'application/zip' });
		const result = await importZip(file);
		expect(result.imported).toBe(1);
		expect(result.skipped).toBe(0);

		const signals = await getSignalsForSession('sess-1');
		expect(signals).toHaveLength(1);
		const decoded = decodeSignalColumn(signals[0].data);
		expect(decoded).toHaveLength(originalValues.length);
		for (let i = 0; i < originalValues.length; i++) {
			expect(decoded[i]).toBeCloseTo(originalValues[i], 4);
		}
	});

	it('restores run metadata and session_ids', async () => {
		await saveRun(makeRun('run-1'));
		await saveSession('run-1', makeResponse('sess-1', [1.0]));

		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		await db.delete();
		await db.open();

		const file = new File([blob], 'export.bodaqs.zip');
		await importZip(file);

		const importedRuns = await getAllRuns();
		expect(importedRuns[0].id).toBe('run-1');
		expect(importedRuns[0].description).toBe('Run run-1');
		expect(importedRuns[0].session_ids).toContain('sess-1');
	});

	it('skips a run that already exists in the db (matched by run_id)', async () => {
		await saveRun(makeRun('run-1'));
		const runs = await getAllRuns();
		const blob = await exportRuns(runs);

		// run-1 is still in db — re-import should skip it
		const file = new File([blob], 'export.bodaqs.zip');
		const result = await importZip(file);
		expect(result.skipped).toBe(1);
		expect(result.imported).toBe(0);
	});

	it('exports an empty run list as a valid ZIP with no run entries', async () => {
		const blob = await exportRuns([]);
		expect(blob.size).toBeGreaterThan(0); // valid ZIP even with no content
		const file = new File([blob], 'empty.bodaqs.zip');
		const result = await importZip(file);
		expect(result.imported).toBe(0);
		expect(result.skipped).toBe(0);
	});
});
```

- [ ] **Step 2: Run the tests**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/zip/export.test.ts
```

Expected: `5 tests passed`.

- [ ] **Step 3: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/zip/export.test.ts
git commit -m "test(frontend): add ZIP export/import round-trip and signal fidelity tests"
```

---

## Task 4: Library landing page

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

Replace the static placeholder with a functional page that loads runs from Dexie and renders either a run list or an empty state.

### Svelte 5 notes

- `onMount` (from `svelte`) runs only in the browser — correct for Dexie (IndexedDB is browser-only)
- `libraryStore.runs` is a `$state` getter — reference it directly in the template (no `.subscribe()`)
- `libraryStore.loading` is a `$state` boolean — use it to show a loading indicator

- [ ] **Step 1: Read the current `+page.svelte`**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/+page.svelte` to confirm it's still the placeholder.

- [ ] **Step 2: Write the functional library page**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/+page.svelte`:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { libraryStore } from '$lib/stores/library.svelte';

	onMount(() => {
		libraryStore.load();
	});
</script>

<svelte:head>
	<title>BODAQS — Run Library</title>
</svelte:head>

<h1>Run Library</h1>

{#if libraryStore.loading}
	<p>Loading…</p>
{:else if libraryStore.runs.length === 0}
	<p>No runs yet. <a href="/upload">Upload a ride</a> to get started.</p>
{:else}
	<ul>
		{#each libraryStore.runs as run (run.id)}
			<li>
				<a href="/dashboard/{run.id}">{run.description || run.id}</a>
				<span>{run.created_at}</span>
				<span>{run.session_ids.length} session{run.session_ids.length === 1 ? '' : 's'}</span>
			</li>
		{/each}
	</ul>
{/if}
```

- [ ] **Step 3: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 4: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/routes/+page.svelte
git commit -m "feat(frontend): make library landing page load and display runs from Dexie"
```

---

## Task 5: Fix SESSION.md + run full test suite

**Files:**
- Modify: `webapp.bodaqs.net/SESSION.md`

The Phase 2 "What was built" file structure section was generated incorrectly — it shows invented paths that don't exist. Replace it with the actual file tree.

- [ ] **Step 1: Run the full test suite**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test
```

Expected: all tests pass (should be ≥12 tests across 3 files). Note the exact count for SESSION.md.

- [ ] **Step 2: Fix SESSION.md Phase 2 file structure**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/SESSION.md`. In the "Phase 2 — What was built" section, replace the incorrect `### File structure created` block with:

```markdown
### File structure created
```
webapp.bodaqs.net/
├── vercel.json                     — routes /api/* → Python, /* → SvelteKit
└── frontend/
    ├── svelte.config.js            — adapter-vercel + runes mode forced globally
    ├── vite.config.ts              — Vite + vitest/config (flat test project)
    ├── tsconfig.json               — strict TypeScript, extends .svelte-kit/tsconfig.json
    ├── package.json                — SvelteKit ^2.57, adapter-vercel ^6, Svelte ^5.55, TS ^6, Vite ^8, Vitest ^4
    ├── eslint.config.js            — ESLint 10 flat config
    ├── .prettierrc                 — tabs, prettier-plugin-svelte
    ├── src/
    │   ├── app.html
    │   ├── app.d.ts
    │   ├── lib/
    │   │   ├── api/
    │   │   │   └── preprocess.ts  — SignalsPayload, PreprocessResponse, PreprocessFormData; postPreprocess(); decodeSignalColumn()
    │   │   ├── db/
    │   │   │   ├── dexie.ts       — BodaqsDB (Dexie 4), schema v1: runs/sessions/signals/events/metrics
    │   │   │   └── artifacts.ts   — saveRun, saveSession (keeps session_ids in sync), getAllRuns, query helpers
    │   │   ├── stores/
    │   │   │   └── library.svelte.ts  — libraryStore ($state, try/finally on load)
    │   │   └── zip/
    │   │       ├── export.ts      — exportRuns() → Blob (JSZip)
    │   │       └── import.ts      — importZip() → {imported, skipped}; skips by run_id
    │   └── routes/
    │       ├── +layout.svelte     — nav: Library / Upload / Transfer
    │       ├── +page.svelte       — run library list (loads from Dexie)
    │       ├── upload/
    │       │   └── +page.svelte   — placeholder (Phase 4)
    │       ├── dashboard/
    │       │   └── [run_id]/
    │       │       ├── +page.ts   — export const prerender = false
    │       │       └── +page.svelte — placeholder (Phase 5)
    │       └── transfer/
    │           └── +page.svelte   — placeholder (Phase 6)
```
```

Also update the Phase status table Phase 3 row to `✅ Complete, N/N tests passing` (use the actual test count from Step 1).

- [ ] **Step 3: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/SESSION.md
git commit -m "docs: fix Phase 2 file listing, mark Phase 3 complete in SESSION.md"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| `db/artifacts.test.ts` — Dexie store/retrieve round-trip using `fake-indexeddb` | Task 2 |
| `zip/export.test.ts` — export then import round-trip; signal round-trip fidelity | Task 3 |
| `api/preprocess.test.ts` — response shape validation against TypeScript types | Task 1 |
| Library landing page shows runs list / empty state | Task 4 |
| All tests run with `npm test` | Task 5, Step 1 |

Phase 3 does not include the upload form, dashboard visualisations, or transfer UI — those are Phases 4–6.

### Placeholder scan

No TBD, no "implement later", no "handle edge cases" without code — all steps contain complete code. ✅

### Type consistency

- `makeRun()` helper returns `Run` (matches `db/dexie.ts` interface: `id, description, created_at, session_ids`)
- `makeResponse()` helper returns `PreprocessResponse` (matches `api/preprocess.ts`)
- `saveSession('run-1', response)` signature matches `artifacts.ts`: `(run_id: string, response: PreprocessResponse) => Promise<void>`
- `decodeSignalColumn(base64: string): Float32Array` — used in export.test.ts with `signals[0].data` (string) ✅
- `libraryStore.runs` — `$state` getter returns `Run[]` — iterated with `#each` in Task 4 ✅
