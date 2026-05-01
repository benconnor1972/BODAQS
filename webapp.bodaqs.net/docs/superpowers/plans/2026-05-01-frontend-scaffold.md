# Frontend Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a working SvelteKit 5 project in `webapp.bodaqs.net/frontend/` with adapter-vercel, correct vercel.json routing, all route stubs, and lib skeleton files — passing `npm run build` and `npm run check`.

**Architecture:** Use `npx sv create` to scaffold the project so package versions, ESLint flat config, and runes-mode config are authoritative from the CLI (not guessed by hand). Then add runtime deps (Dexie, JSZip, Plotly), write route stubs and typed lib skeletons, and add vercel.json at the monorepo root to route `/api/*` to Python functions and `/*` to SvelteKit.

**Tech Stack:** SvelteKit 5, Svelte 5 (runes mode), TypeScript strict, adapter-vercel, Dexie 4, JSZip 3, plotly.js-dist-min, Vite 8, Vitest 4, svelte-check, ESLint 10 (flat config), prettier.

---

## File Map

### Scaffolded by `sv create` (do not hand-write)

| File | Responsibility |
|---|---|
| `frontend/package.json` | Deps + scripts — versions resolved by CLI |
| `frontend/svelte.config.js` | adapter-vercel + runes mode forced globally |
| `frontend/vite.config.ts` | Vite + vitest config |
| `frontend/tsconfig.json` | Strict TS, extends .svelte-kit/tsconfig.json |
| `frontend/eslint.config.js` | ESLint 10 flat config |
| `frontend/.prettierrc` | Prettier + prettier-plugin-svelte |
| `frontend/src/app.html` | HTML shell |
| `frontend/src/app.d.ts` | SvelteKit ambient type extensions |

### New files — routes (stubs)

| File | Responsibility |
|---|---|
| `frontend/src/routes/+layout.svelte` | Top-level nav; links to /, /upload, /transfer |
| `frontend/src/routes/+page.svelte` | Run library landing (replace sv create demo) |
| `frontend/src/routes/upload/+page.svelte` | Upload flow placeholder |
| `frontend/src/routes/dashboard/[run_id]/+page.svelte` | Dashboard placeholder |
| `frontend/src/routes/dashboard/[run_id]/+page.ts` | `export const prerender = false` |
| `frontend/src/routes/transfer/+page.svelte` | Transfer / ZIP placeholder |

### New files — lib skeletons

| File | Responsibility |
|---|---|
| `frontend/src/lib/api/preprocess.ts` | TypeScript types for `PreprocessResponse`; `postPreprocess()` + `decodeSignalColumn()` |
| `frontend/src/lib/db/dexie.ts` | Dexie 4 schema: `runs / sessions / signals / events / metrics` |
| `frontend/src/lib/db/artifacts.ts` | Typed read/write helpers wrapping dexie.ts |
| `frontend/src/lib/stores/library.svelte.ts` | Svelte 5 rune-based library store; reads from Dexie |
| `frontend/src/lib/zip/export.ts` | `exportRuns()` returning a `Blob` |
| `frontend/src/lib/zip/import.ts` | `importZip()` accepting a `File` |

### Root-level

| File | Responsibility |
|---|---|
| `webapp.bodaqs.net/vercel.json` | Route `/api/*` to Python, `/*` to SvelteKit |

---

## Task 1: Clean up stale artefacts

**Files:**
- Delete: `frontend/node_modules/`, `frontend/.svelte-kit/`

- [ ] **Step 1: Remove stale generated and installed artefacts**

```bash
rm -rf /Volumes/www/BODAQS/webapp.bodaqs.net/frontend/node_modules
rm -rf /Volumes/www/BODAQS/webapp.bodaqs.net/frontend/.svelte-kit
```

- [ ] **Step 2: Confirm directory is clean**

```bash
ls /Volumes/www/BODAQS/webapp.bodaqs.net/frontend/
```

Expected: only `.vscode` (and `.DS_Store`). No `node_modules`, no `.svelte-kit`.

---

## Task 2: Scaffold with `sv create`

**Files:** All config files listed in "Scaffolded by sv create" above.

- [ ] **Step 1: Run `sv create` non-interactively**

Run from the `webapp.bodaqs.net/` directory so the scaffold lands in `frontend/`:

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net && npx sv create frontend \
  --template minimal \
  --types ts \
  --add prettier eslint "vitest=usages:unit" "sveltekit-adapter=adapter:vercel" \
  --no-install \
  --no-dir-check
```

Expected output: `◆  Successfully setup add-ons: prettier, eslint, vitest, sveltekit-adapter` and `You're all set!`. No errors.

- [ ] **Step 2: Remove demo files added by sv create**

```bash
rm -rf /Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/vitest-examples
rm /Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/index.ts
```

- [ ] **Step 3: Add runtime dependencies to `package.json`**

Edit `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/package.json` — add to the `"dependencies"` key (create it if absent; it won't exist yet since sv create puts everything in devDependencies):

```json
"dependencies": {
  "dexie": "^4.0.11",
  "jszip": "^3.10.1",
  "plotly.js-dist-min": "^2.35.3"
}
```

- [ ] **Step 4: Install all packages**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm install
```

Expected: exits 0, creates `node_modules/` and `package-lock.json`.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/
git commit -m "feat(frontend): scaffold SvelteKit 5 project via sv create + add runtime deps"
```

---

## Task 3: `vercel.json` routing

**Files:**
- Create: `webapp.bodaqs.net/vercel.json`

- [ ] **Step 1: Write `vercel.json`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/vercel.json`:

```json
{
  "buildCommand": "cd frontend && npm run build",
  "outputDirectory": "frontend/.vercel/output",
  "functions": {
    "api/index.py": {
      "runtime": "python3.12"
    }
  },
  "rewrites": [
    { "source": "/api/(.*)", "destination": "/api/index.py" },
    { "source": "/(.*)", "destination": "/" }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/vercel.json
git commit -m "feat(webapp): add vercel.json — api/* → Python, /* → SvelteKit"
```

---

## Task 4: Route stubs

**Files:**
- Modify: `frontend/src/routes/+layout.svelte` (replace sv create default)
- Modify: `frontend/src/routes/+page.svelte` (replace sv create demo)
- Create: `frontend/src/routes/upload/+page.svelte`
- Create: `frontend/src/routes/dashboard/[run_id]/+page.svelte`
- Create: `frontend/src/routes/dashboard/[run_id]/+page.ts`
- Create: `frontend/src/routes/transfer/+page.svelte`

- [ ] **Step 1: Replace `+layout.svelte`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/+layout.svelte`:

```svelte
<script lang="ts">
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();
</script>

<nav>
	<a href="/">Library</a>
	<a href="/upload">Upload</a>
	<a href="/transfer">Transfer</a>
</nav>

<main>
	{@render children()}
</main>

<style>
	nav {
		display: flex;
		gap: 1rem;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid #e5e7eb;
	}
	main {
		padding: 1rem;
	}
</style>
```

- [ ] **Step 2: Replace `+page.svelte` (library landing)**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/+page.svelte`:

```svelte
<svelte:head>
	<title>BODAQS — Run Library</title>
</svelte:head>

<h1>Run Library</h1>
<p>No runs yet. <a href="/upload">Upload a ride</a> to get started.</p>
```

- [ ] **Step 3: Create `upload/+page.svelte`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/upload/+page.svelte`:

```svelte
<svelte:head>
	<title>BODAQS — Upload</title>
</svelte:head>

<h1>Upload</h1>
<p>Upload form coming in Phase 4.</p>
```

- [ ] **Step 4: Create `dashboard/[run_id]/+page.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/dashboard/[run_id]/+page.ts`:

```ts
export const prerender = false;
```

- [ ] **Step 5: Create `dashboard/[run_id]/+page.svelte`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/dashboard/[run_id]/+page.svelte`:

```svelte
<script lang="ts">
	import { page } from '$app/state';
</script>

<svelte:head>
	<title>BODAQS — Dashboard</title>
</svelte:head>

<h1>Dashboard</h1>
<p>Run: {page.params.run_id}</p>
<p>10-tile suspension dashboard coming in Phase 5.</p>
```

- [ ] **Step 6: Create `transfer/+page.svelte`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/transfer/+page.svelte`:

```svelte
<svelte:head>
	<title>BODAQS — Transfer</title>
</svelte:head>

<h1>Transfer</h1>
<p>ZIP export/import coming in Phase 6.</p>
```

- [ ] **Step 7: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: `svelte-check found 0 errors and 0 warnings`.

- [ ] **Step 8: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/routes/
git commit -m "feat(frontend): add route stubs for all five pages"
```

---

## Task 5: Lib skeleton files

**Files:**
- Create: `frontend/src/lib/api/preprocess.ts`
- Create: `frontend/src/lib/db/dexie.ts`
- Create: `frontend/src/lib/db/artifacts.ts`
- Create: `frontend/src/lib/stores/library.svelte.ts`
- Create: `frontend/src/lib/zip/export.ts`
- Create: `frontend/src/lib/zip/import.ts`

- [ ] **Step 1: Write `lib/api/preprocess.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/api/preprocess.ts`:

```ts
export interface SignalsPayload {
	column_names: string[];
	n_rows: number;
	columns: Record<string, string>; // column name → base64 float32 LE
}

export interface PreprocessResponse {
	session_id: string;
	meta: Record<string, unknown>;
	source_sha256: string;
	signals: SignalsPayload;
	events: Record<string, unknown>[];
	metrics: Record<string, unknown>[];
	warnings: string[];
}

export interface PreprocessFormData {
	csv_file: File;
	bike_profile_json: File;
	sidecar_json: File;
	event_schema_yaml: File;
	preprocess_profile_json?: File;
}

export async function postPreprocess(data: PreprocessFormData): Promise<PreprocessResponse> {
	const form = new FormData();
	form.append('csv_file', data.csv_file);
	form.append('bike_profile_json', data.bike_profile_json);
	form.append('sidecar_json', data.sidecar_json);
	form.append('event_schema_yaml', data.event_schema_yaml);
	if (data.preprocess_profile_json) {
		form.append('preprocess_profile_json', data.preprocess_profile_json);
	}

	const response = await fetch('/api/preprocess', { method: 'POST', body: form });
	if (!response.ok) {
		const text = await response.text();
		throw new Error(`Preprocess failed (${response.status}): ${text}`);
	}
	return response.json() as Promise<PreprocessResponse>;
}

export function decodeSignalColumn(base64: string): Float32Array {
	const binary = atob(base64);
	const bytes = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) {
		bytes[i] = binary.charCodeAt(i);
	}
	return new Float32Array(bytes.buffer);
}
```

- [ ] **Step 2: Write `lib/db/dexie.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/db/dexie.ts`:

```ts
import Dexie, { type EntityTable } from 'dexie';

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
	runs!: EntityTable<Run, 'id'>;
	sessions!: EntityTable<Session, 'id'>;
	signals!: EntityTable<SignalRow, 'id'>;
	events!: EntityTable<EventRow, 'id'>;
	metrics!: EntityTable<MetricRow, 'id'>;

	constructor() {
		super('bodaqs');
		this.version(1).stores({
			runs: 'id, created_at',
			sessions: 'id, run_id',
			signals: '++id, session_id, column_name',
			events: '++id, session_id, schema_id',
			metrics: '++id, session_id, schema_id'
		});
	}
}

export const db = new BodaqsDB();
```

- [ ] **Step 3: Write `lib/db/artifacts.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/db/artifacts.ts`:

```ts
import type { PreprocessResponse } from '$lib/api/preprocess';
import { db, type EventRow, type MetricRow, type Run, type Session, type SignalRow } from './dexie';

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

	for (const [column_name, data] of Object.entries(response.signals.columns)) {
		const row: SignalRow = { session_id: response.session_id, column_name, data };
		await db.signals.put(row);
	}

	if (response.events.length > 0) {
		const eventRow: EventRow = {
			session_id: response.session_id,
			schema_id: 'default',
			rows: response.events
		};
		await db.events.put(eventRow);
	}

	if (response.metrics.length > 0) {
		const metricRow: MetricRow = {
			session_id: response.session_id,
			schema_id: 'default',
			rows: response.metrics
		};
		await db.metrics.put(metricRow);
	}
}

export async function getAllRuns(): Promise<Run[]> {
	return db.runs.orderBy('created_at').reverse().toArray();
}

export async function getSessionsForRun(run_id: string): Promise<Session[]> {
	return db.sessions.where('run_id').equals(run_id).toArray();
}

export async function getSignalsForSession(session_id: string): Promise<SignalRow[]> {
	return db.signals.where('session_id').equals(session_id).toArray();
}

export async function getEventsForSession(session_id: string): Promise<EventRow[]> {
	return db.events.where('session_id').equals(session_id).toArray();
}

export async function getMetricsForSession(session_id: string): Promise<MetricRow[]> {
	return db.metrics.where('session_id').equals(session_id).toArray();
}
```

- [ ] **Step 4: Write `lib/stores/library.svelte.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/stores/library.svelte.ts`:

```ts
import { getAllRuns, saveRun } from '$lib/db/artifacts';
import type { Run } from '$lib/db/dexie';

function createLibraryStore() {
	let runs = $state<Run[]>([]);
	let loading = $state(false);

	async function load(): Promise<void> {
		loading = true;
		runs = await getAllRuns();
		loading = false;
	}

	async function addRun(run: Run): Promise<void> {
		await saveRun(run);
		runs = await getAllRuns();
	}

	return {
		get runs() {
			return runs;
		},
		get loading() {
			return loading;
		},
		load,
		addRun
	};
}

export const libraryStore = createLibraryStore();
```

- [ ] **Step 5: Write `lib/zip/export.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/zip/export.ts`:

```ts
import JSZip from 'jszip';
import {
	getEventsForSession,
	getMetricsForSession,
	getSessionsForRun,
	getSignalsForSession
} from '$lib/db/artifacts';
import type { Run } from '$lib/db/dexie';

export async function exportRuns(runs: Run[]): Promise<Blob> {
	const zip = new JSZip();

	for (const run of runs) {
		const runFolder = zip.folder(`runs/${run.id}`);
		if (!runFolder) continue;

		runFolder.file(
			'run_manifest.json',
			JSON.stringify(
				{
					run_id: run.id,
					description: run.description,
					created_at: run.created_at,
					session_ids: run.session_ids
				},
				null,
				2
			)
		);

		const sessions = await getSessionsForRun(run.id);
		for (const session of sessions) {
			const sessionFolder = runFolder.folder(`sessions/${session.id}`);
			if (!sessionFolder) continue;

			sessionFolder.file(
				'session_manifest.json',
				JSON.stringify({ meta: session.meta, source_sha256: session.source_sha256 }, null, 2)
			);

			const signals = await getSignalsForSession(session.id);
			const signalMap: Record<string, string> = {};
			for (const s of signals) signalMap[s.column_name] = s.data;
			sessionFolder.file('signals/signals.json', JSON.stringify(signalMap, null, 2));

			const events = await getEventsForSession(session.id);
			for (const e of events) {
				sessionFolder.file(`events/${e.schema_id}.json`, JSON.stringify(e.rows, null, 2));
			}

			const metrics = await getMetricsForSession(session.id);
			for (const m of metrics) {
				sessionFolder.file(`metrics/${m.schema_id}.json`, JSON.stringify(m.rows, null, 2));
			}
		}
	}

	return zip.generateAsync({ type: 'blob', compression: 'DEFLATE' });
}
```

- [ ] **Step 6: Write `lib/zip/import.ts`**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/zip/import.ts`:

```ts
import JSZip from 'jszip';
import { db } from '$lib/db/dexie';
import type { EventRow, MetricRow, Run, Session, SignalRow } from '$lib/db/dexie';

export async function importZip(file: File): Promise<{ imported: number; skipped: number }> {
	const zip = await JSZip.loadAsync(file);
	let imported = 0;
	let skipped = 0;

	const runManifestFiles = Object.keys(zip.files).filter((path) =>
		path.match(/^runs\/[^/]+\/run_manifest\.json$/)
	);

	for (const manifestPath of runManifestFiles) {
		const manifestText = await zip.files[manifestPath].async('string');
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
				.map((p) => p.slice(runPrefix.length).split('/')[0])
				.filter(Boolean)
		);

		for (const sessionId of sessionFolders) {
			const sessionBase = `${runPrefix}${sessionId}/`;
			const sessionManifestFile = zip.files[`${sessionBase}session_manifest.json`];
			if (!sessionManifestFile) continue;

			const sessionManifestText = await sessionManifestFile.async('string');
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
				const signalsText = await signalsFile.async('string');
				const signalMap = JSON.parse(signalsText) as Record<string, string>;
				for (const [column_name, data] of Object.entries(signalMap)) {
					const row: SignalRow = { session_id: sessionId, column_name, data };
					await db.signals.put(row);
				}
			}

			const eventsPrefix = `${sessionBase}events/`;
			for (const [path, zipFile] of Object.entries(zip.files)) {
				if (!path.startsWith(eventsPrefix) || zipFile.dir) continue;
				const schema_id = path.slice(eventsPrefix.length).replace(/\.json$/, '');
				const rowsText = await zipFile.async('string');
				const row: EventRow = { session_id: sessionId, schema_id, rows: JSON.parse(rowsText) };
				await db.events.put(row);
			}

			const metricsPrefix = `${sessionBase}metrics/`;
			for (const [path, zipFile] of Object.entries(zip.files)) {
				if (!path.startsWith(metricsPrefix) || zipFile.dir) continue;
				const schema_id = path.slice(metricsPrefix.length).replace(/\.json$/, '');
				const rowsText = await zipFile.async('string');
				const row: MetricRow = { session_id: sessionId, schema_id, rows: JSON.parse(rowsText) };
				await db.metrics.put(row);
			}
		}

		imported++;
	}

	return { imported, skipped };
}
```

- [ ] **Step 7: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: `svelte-check found 0 errors and 0 warnings`.

- [ ] **Step 8: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/
git commit -m "feat(frontend): add lib skeleton — api types, Dexie schema, zip export/import"
```

---

## Task 6: Build verification checkpoint

- [ ] **Step 1: Run production build**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run build
```

Expected: exits 0; output ends with `✓ built in …`. No TypeScript errors.

- [ ] **Step 2: Run `npm run check`**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: `svelte-check found 0 errors and 0 warnings`.

- [ ] **Step 3: Update SESSION.md**

Edit `/Volumes/www/BODAQS/webapp.bodaqs.net/SESSION.md`:
- Change Phase 2 row from `🔜 Next` to `✅ Complete, npm run build passes`
- Change Phase 3 row from `⬜ Not started` to `🔜 Next`
- Add a "Phase 2 — What was built" section below the Phase 1 section listing the files created, the `sv create` command used, and the key decisions (adapter-vercel, runes mode forced globally, Dexie schema version 1).

- [ ] **Step 4: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/SESSION.md
git commit -m "docs: mark Phase 2 complete in SESSION.md"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| SvelteKit 5, runes mode, TypeScript strict | Task 2 (`sv create` + svelte.config.js forces runes) |
| adapter-vercel | Task 2 (`sv create --add sveltekit-adapter=adapter:vercel`) |
| vercel.json routing api/* → Python, /* → SvelteKit | Task 3 |
| `export const prerender = false` on dashboard route | Task 4, Step 4 |
| Dexie 4 schema: runs/sessions/signals/events/metrics | Task 5, Step 2 |
| Signal encoding: base64 float32 LE | Task 5, Steps 1 & 5 |
| JSZip export: runs/{run_id}/sessions/{session_id}/… structure | Task 5, Step 5 |
| ZIP import: duplicates skipped by run_id | Task 5, Step 6 |
| Route stubs for /, /upload, /dashboard/[run_id], /transfer | Task 4 |
| `npm run build` succeeds as Phase 2 checkpoint | Task 6 |

Phase 2 does not include the upload form UI, dashboard viz, or transfer UI — those are Phases 4–6.
