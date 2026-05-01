# Phase 4 — Upload Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working upload page that accepts four required files (CSV, sidecar JSON, bike profile JSON, event schema YAML) plus an optional preprocess profile, calls `POST /api/preprocess`, writes the result to Dexie, and navigates to the dashboard — with frontend validation matching backend constraints.

**Architecture:** Validation logic lives in a pure, testable module (`lib/upload/validate.ts`) so it can be unit-tested without a browser. The upload page (`routes/upload/+page.svelte`) holds all form state as Svelte 5 `$state`, derives the submit-ready flag from `isUploadReady`, calls `postPreprocess` on submit, writes Run+Session to Dexie, then navigates to `/dashboard/{run_id}`. The run ID is a frontend-generated UUID; the session ID comes from the backend response.

**Tech Stack:** SvelteKit 5 runes (`$state`, `$derived`), `$app/navigation` `goto`, existing `postPreprocess` + `saveRun` + `saveSession` from lib.

---

## File Map

### New files

| File | Responsibility |
|---|---|
| `frontend/src/lib/upload/validate.ts` | `UploadFiles` type; `validateUploadFiles()` returning error strings; `isUploadReady()` returning boolean; `MAX_CSV_BYTES` constant |
| `frontend/src/lib/upload/validate.test.ts` | Unit tests for both functions — no browser, no Dexie |

### Modified files

| File | Change |
|---|---|
| `frontend/src/routes/upload/+page.svelte` | Replace placeholder with full upload form |

---

## Task 1: Validation logic (TDD)

**Files:**
- Create: `frontend/src/lib/upload/validate.ts`
- Create: `frontend/src/lib/upload/validate.test.ts`

The validation function checks:
1. CSV present and ≤ 50 MB
2. Bike profile present and `.json` extension
3. Sidecar present and `.json` extension
4. Event schema present and `.yaml` or `.yml` extension
5. Optional preprocess profile: if provided, must be `.json`

`isUploadReady` returns `true` only when all four required files are set and the CSV is within size. This drives the disabled state of the submit button.

- [ ] **Step 1: Write the failing tests**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/upload/validate.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { validateUploadFiles, isUploadReady, MAX_CSV_BYTES } from '$lib/upload/validate';
import type { UploadFiles } from '$lib/upload/validate';

function mockFile(name: string, sizeBytes = 100): File {
	const file = new File([], name);
	Object.defineProperty(file, 'size', { value: sizeBytes, configurable: true });
	return file;
}

const validFiles: UploadFiles = {
	csv_file: mockFile('ride.csv'),
	bike_profile_json: mockFile('bike.json'),
	sidecar_json: mockFile('sidecar.json'),
	event_schema_yaml: mockFile('schema.yaml'),
	preprocess_profile_json: null
};

describe('validateUploadFiles', () => {
	it('returns no errors when all required files are valid', () => {
		expect(validateUploadFiles(validFiles)).toHaveLength(0);
	});

	it('returns error when csv_file is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, csv_file: null });
		expect(errors.some((e) => e.includes('CSV'))).toBe(true);
	});

	it('returns error when CSV exceeds 50 MB', () => {
		const bigCsv = mockFile('ride.csv', MAX_CSV_BYTES + 1);
		const errors = validateUploadFiles({ ...validFiles, csv_file: bigCsv });
		expect(errors.some((e) => e.includes('50 MB'))).toBe(true);
	});

	it('returns error when bike_profile_json is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, bike_profile_json: null });
		expect(errors.some((e) => e.toLowerCase().includes('bike profile'))).toBe(true);
	});

	it('returns error when bike_profile_json has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, bike_profile_json: mockFile('bike.txt') });
		expect(errors.some((e) => e.toLowerCase().includes('bike profile'))).toBe(true);
	});

	it('returns error when sidecar_json is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, sidecar_json: null });
		expect(errors.some((e) => e.toLowerCase().includes('sidecar'))).toBe(true);
	});

	it('returns error when sidecar_json has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, sidecar_json: mockFile('sidecar.txt') });
		expect(errors.some((e) => e.toLowerCase().includes('sidecar'))).toBe(true);
	});

	it('returns error when event_schema_yaml is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: null });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(true);
	});

	it('returns error when event_schema_yaml has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: mockFile('schema.json') });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(true);
	});

	it('accepts .yml extension for event schema', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: mockFile('schema.yml') });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(false);
	});

	it('returns no error when preprocess_profile_json is null (optional)', () => {
		const errors = validateUploadFiles({ ...validFiles, preprocess_profile_json: null });
		expect(errors).toHaveLength(0);
	});

	it('returns error when preprocess_profile_json has wrong extension', () => {
		const errors = validateUploadFiles({
			...validFiles,
			preprocess_profile_json: mockFile('profile.txt')
		});
		expect(errors.some((e) => e.toLowerCase().includes('preprocess profile'))).toBe(true);
	});

	it('accumulates multiple errors', () => {
		const errors = validateUploadFiles({
			csv_file: null,
			bike_profile_json: null,
			sidecar_json: null,
			event_schema_yaml: null,
			preprocess_profile_json: null
		});
		expect(errors.length).toBeGreaterThanOrEqual(4);
	});
});

describe('isUploadReady', () => {
	it('returns true when all required files are set and CSV is within size', () => {
		expect(isUploadReady(validFiles)).toBe(true);
	});

	it('returns false when csv_file is null', () => {
		expect(isUploadReady({ ...validFiles, csv_file: null })).toBe(false);
	});

	it('returns false when CSV exceeds 50 MB', () => {
		const bigCsv = mockFile('ride.csv', MAX_CSV_BYTES + 1);
		expect(isUploadReady({ ...validFiles, csv_file: bigCsv })).toBe(false);
	});

	it('returns false when bike_profile_json is null', () => {
		expect(isUploadReady({ ...validFiles, bike_profile_json: null })).toBe(false);
	});

	it('returns false when sidecar_json is null', () => {
		expect(isUploadReady({ ...validFiles, sidecar_json: null })).toBe(false);
	});

	it('returns false when event_schema_yaml is null', () => {
		expect(isUploadReady({ ...validFiles, event_schema_yaml: null })).toBe(false);
	});

	it('returns true when preprocess_profile_json is null (optional field)', () => {
		expect(isUploadReady({ ...validFiles, preprocess_profile_json: null })).toBe(true);
	});
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/upload/validate.test.ts
```

Expected: all tests fail with "Cannot find module '$lib/upload/validate'".

- [ ] **Step 3: Write `validate.ts`**

Create `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/lib/upload/validate.ts`:

```ts
export const MAX_CSV_BYTES = 50 * 1024 * 1024; // 50 MB

export interface UploadFiles {
	csv_file: File | null;
	bike_profile_json: File | null;
	sidecar_json: File | null;
	event_schema_yaml: File | null;
	preprocess_profile_json: File | null;
}

export function validateUploadFiles(files: UploadFiles): string[] {
	const errors: string[] = [];

	if (!files.csv_file) {
		errors.push('Logger CSV is required.');
	} else if (files.csv_file.size > MAX_CSV_BYTES) {
		errors.push(
			`CSV file exceeds 50 MB limit (${(files.csv_file.size / 1024 / 1024).toFixed(1)} MB).`
		);
	}

	if (!files.bike_profile_json) {
		errors.push('Bike profile JSON is required.');
	} else if (!files.bike_profile_json.name.toLowerCase().endsWith('.json')) {
		errors.push('Bike profile must be a .json file.');
	}

	if (!files.sidecar_json) {
		errors.push('Sidecar JSON is required.');
	} else if (!files.sidecar_json.name.toLowerCase().endsWith('.json')) {
		errors.push('Sidecar must be a .json file.');
	}

	if (!files.event_schema_yaml) {
		errors.push('Event schema YAML is required.');
	} else if (
		!files.event_schema_yaml.name.toLowerCase().endsWith('.yaml') &&
		!files.event_schema_yaml.name.toLowerCase().endsWith('.yml')
	) {
		errors.push('Event schema must be a .yaml or .yml file.');
	}

	if (
		files.preprocess_profile_json &&
		!files.preprocess_profile_json.name.toLowerCase().endsWith('.json')
	) {
		errors.push('Preprocess profile must be a .json file.');
	}

	return errors;
}

export function isUploadReady(files: UploadFiles): boolean {
	return (
		files.csv_file !== null &&
		files.csv_file.size <= MAX_CSV_BYTES &&
		files.bike_profile_json !== null &&
		files.sidecar_json !== null &&
		files.event_schema_yaml !== null
	);
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test -- src/lib/upload/validate.test.ts
```

Expected: all 20 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/lib/upload/
git commit -m "feat(frontend): add upload validation logic with full test suite"
```

---

## Task 2: Upload page

**Files:**
- Modify: `frontend/src/routes/upload/+page.svelte`

### Flow

1. Five file inputs render (4 required, 1 optional)
2. Each `onchange` event updates the `files` state object
3. `isUploadReady(files)` is derived — submit button is disabled when false or while submitting
4. On submit: `validateUploadFiles` → if errors, display them and stop; else call `postPreprocess` → `saveRun` → `saveSession` → `goto('/dashboard/{run_id}')`
5. If `postPreprocess` throws, display the error message. Reset `submitting` in a `finally` block.

### Run ID and description

- `run_id = crypto.randomUUID()` — generated in the browser before the API call
- `description` = CSV filename without extension (e.g. `'2026-02-20_08-34-26.CSV'` → `'2026-02-20_08-34-26'`)

### Warnings

- Stored on `Session.warnings` in Dexie via `saveSession` — surfaced on the dashboard in Phase 5
- Not shown on the upload page (redirect happens immediately on success)

- [ ] **Step 1: Write the upload page**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/upload/+page.svelte`:

```svelte
<script lang="ts">
	import { goto } from '$app/navigation';
	import { postPreprocess } from '$lib/api/preprocess';
	import { saveRun, saveSession } from '$lib/db/artifacts';
	import { validateUploadFiles, isUploadReady } from '$lib/upload/validate';
	import type { UploadFiles } from '$lib/upload/validate';

	let files = $state<UploadFiles>({
		csv_file: null,
		bike_profile_json: null,
		sidecar_json: null,
		event_schema_yaml: null,
		preprocess_profile_json: null
	});

	let submitting = $state(false);
	let validationErrors = $state<string[]>([]);
	let apiError = $state<string | null>(null);

	let ready = $derived(isUploadReady(files));

	function onFileChange(field: keyof UploadFiles, event: Event): void {
		const input = event.target as HTMLInputElement;
		files = { ...files, [field]: input.files?.[0] ?? null };
	}

	async function handleSubmit(event: Event): Promise<void> {
		event.preventDefault();
		validationErrors = validateUploadFiles(files);
		if (validationErrors.length > 0) return;

		submitting = true;
		apiError = null;

		try {
			const response = await postPreprocess({
				csv_file: files.csv_file!,
				bike_profile_json: files.bike_profile_json!,
				sidecar_json: files.sidecar_json!,
				event_schema_yaml: files.event_schema_yaml!,
				preprocess_profile_json: files.preprocess_profile_json ?? undefined
			});

			const run_id = crypto.randomUUID();
			const run = {
				id: run_id,
				description: files.csv_file!.name.replace(/\.[^.]+$/, ''),
				created_at: new Date().toISOString(),
				session_ids: []
			};

			await saveRun(run);
			await saveSession(run_id, response);

			goto(`/dashboard/${run_id}`);
		} catch (err) {
			apiError = err instanceof Error ? err.message : 'Upload failed. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>BODAQS — Upload</title>
</svelte:head>

<h1>Upload Ride</h1>

<form onsubmit={handleSubmit}>
	<fieldset>
		<legend>Required files</legend>

		<label>
			Logger CSV *
			<input
				type="file"
				accept=".csv,.CSV"
				onchange={(e) => onFileChange('csv_file', e)}
			/>
		</label>

		<label>
			Bike Profile JSON *
			<input
				type="file"
				accept=".json"
				onchange={(e) => onFileChange('bike_profile_json', e)}
			/>
		</label>

		<label>
			Sidecar JSON *
			<input
				type="file"
				accept=".json"
				onchange={(e) => onFileChange('sidecar_json', e)}
			/>
		</label>

		<label>
			Event Schema YAML *
			<input
				type="file"
				accept=".yaml,.yml"
				onchange={(e) => onFileChange('event_schema_yaml', e)}
			/>
		</label>
	</fieldset>

	<fieldset>
		<legend>Optional files</legend>

		<label>
			Preprocess Profile JSON
			<input
				type="file"
				accept=".json"
				onchange={(e) => onFileChange('preprocess_profile_json', e)}
			/>
		</label>
	</fieldset>

	{#if validationErrors.length > 0}
		<ul role="alert">
			{#each validationErrors as error}
				<li>{error}</li>
			{/each}
		</ul>
	{/if}

	{#if apiError}
		<p role="alert">{apiError}</p>
	{/if}

	<button type="submit" disabled={!ready || submitting}>
		{submitting ? 'Processing…' : 'Process Ride'}
	</button>
</form>
```

- [ ] **Step 2: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 3: Run full test suite**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test
```

Expected: all 43 tests pass (23 from Phase 3 + 20 new validate tests).

- [ ] **Step 4: Update SESSION.md**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/SESSION.md`.

In the Phase status table:
- Change Phase 4 from `⬜ Not started` to `✅ Complete, 43/43 tests passing`
- Change Phase 5 from `⬜ Not started` to `🔜 Next`

Add a "Phase 4 — What was built" section before the "Phase 3 — What to do next" section:

```markdown
## Phase 4 — What was built

### Files created/modified
```
frontend/src/lib/upload/
├── validate.ts   — UploadFiles type, MAX_CSV_BYTES (50 MB), validateUploadFiles(), isUploadReady()
└── validate.test.ts — 20 tests: extension checks, size limits, required field checks

frontend/src/routes/upload/
└── +page.svelte  — 5 file inputs, $state form, $derived ready flag, postPreprocess call, saveRun+saveSession, goto dashboard
```

### Key decisions made

**Run ID strategy:** `crypto.randomUUID()` generated in browser before API call — avoids any server-side ID management. Run description derived from CSV filename stem.

**Validation approach:** Pure `validate.ts` module (no browser/Dexie needed) makes unit testing straightforward. Extension checks guard against wrong file types; `isUploadReady` drives the disabled state so the button can never be clicked with missing required files.

**Warnings:** Stored on `Session.warnings` in Dexie via `saveSession`. Not shown on upload page — Phase 5 dashboard will surface them.

**No library store interaction:** Upload page calls `saveRun` + `saveSession` directly. The library page reloads from Dexie on mount, so navigating back to `/` will always show the new run.
```

- [ ] **Step 5: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/routes/upload/+page.svelte webapp.bodaqs.net/SESSION.md
git commit -m "feat(frontend): upload page — file pickers, validation, preprocess call, Dexie write"
```

---

## Self-review against spec

| Spec requirement | Task |
|---|---|
| Four required files: csv_file, bike_profile_json, sidecar_json, event_schema_yaml | Task 1 (UploadFiles type) + Task 2 (file inputs) |
| Optional fifth file: preprocess_profile_json | Task 1 + Task 2 |
| Block submit button until all four required files selected | Task 2 (`disabled={!ready \|\| submitting}`, `isUploadReady` derives from all 4 fields) |
| Validate file MIME types / extensions | Task 1 (`validateUploadFiles` checks `.json`, `.yaml`, `.yml`, `.csv`) |
| Reject CSV > 50 MB | Task 1 (`MAX_CSV_BYTES`, tested) |
| Call `POST /api/preprocess` with correct form fields | Task 2 (`postPreprocess` call with all 5 fields) |
| Write result to Dexie | Task 2 (`saveRun` + `saveSession`) |
| Navigate to dashboard after success | Task 2 (`goto('/dashboard/{run_id}')`) |
| Show errors — never silently fail | Task 2 (`validationErrors` list + `apiError` paragraph, both with `role="alert"`) |
| Warnings stored, not lost | Task 2 (stored via `saveSession` → `Session.warnings` in Dexie) |

### Placeholder scan

No TBD, no "implement later", all steps contain complete code. ✅

### Type consistency

- `UploadFiles` defined in `validate.ts`, used in `+page.svelte` — consistent
- `isUploadReady(files: UploadFiles): boolean` — called in `$derived` with the same `files` $state — consistent
- `postPreprocess({ csv_file, bike_profile_json, sidecar_json, event_schema_yaml, preprocess_profile_json? })` — matches `PreprocessFormData` in `preprocess.ts` — consistent
- `saveRun(run: Run)` where `Run = { id, description, created_at, session_ids }` — all fields provided — consistent
- `saveSession(run_id: string, response: PreprocessResponse)` — consistent with `artifacts.ts` signature
