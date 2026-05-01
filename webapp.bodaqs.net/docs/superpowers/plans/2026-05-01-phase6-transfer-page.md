# Phase 6 (partial) — Transfer Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the transfer page placeholder with a working ZIP export/import UI — allowing users to export selected runs as `.bodaqs.zip` and import a ZIP back into the library.

**Architecture:** The ZIP export and import logic (`lib/zip/export.ts`, `lib/zip/import.ts`) are already fully implemented and tested from Phase 3. The transfer page is pure UI: it loads runs from Dexie, lets the user select which to export, calls `exportRuns` → triggers a browser download, and calls `importZip` on a file-picker input → reports imported/skipped counts. No new lib files are needed.

**Tech Stack:** SvelteKit 5 runes (`$state`, `$derived`), `onMount`, existing `exportRuns` + `importZip` + `getAllRuns` from lib.

---

## File Map

| File | Change |
|---|---|
| `frontend/src/routes/transfer/+page.svelte` | Replace placeholder with full transfer UI |

---

## Task 1: Transfer page

**Files:**
- Modify: `frontend/src/routes/transfer/+page.svelte`

### Export flow
1. Load all runs from Dexie on mount via `getAllRuns()`
2. Checkbox list — one per run, labelled with `run.description || run.id`
3. "Export selected" button — disabled when nothing selected or while exporting
4. On submit: call `exportRuns(selectedRuns)` → get Blob → trigger browser download as `bodaqs-export-{YYYY-MM-DD}.bodaqs.zip`
5. Status message: shows "Exporting…" during work, "Exported N run(s)" on success, error text on failure

### Import flow
1. File input `accept=".bodaqs.zip,.zip"`
2. "Import" button — disabled when no file selected or while importing
3. On import: call `importZip(file)` → show "Imported N, skipped M (already in library)"
4. On success: reload runs from Dexie so the checkboxes reflect any newly imported runs
5. Error displayed on failure

- [ ] **Step 1: Read the current placeholder**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/transfer/+page.svelte` to confirm it's a placeholder before overwriting.

- [ ] **Step 2: Write the transfer page**

Write `/Volumes/www/BODAQS/webapp.bodaqs.net/frontend/src/routes/transfer/+page.svelte`:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { getAllRuns } from '$lib/db/artifacts';
	import { exportRuns } from '$lib/zip/export';
	import { importZip } from '$lib/zip/import';
	import type { Run } from '$lib/db/dexie';

	let runs = $state<Run[]>([]);
	let selected = $state<Set<string>>(new Set());
	let loadError = $state<string | null>(null);

	let exporting = $state(false);
	let exportStatus = $state<string | null>(null);
	let exportError = $state<string | null>(null);

	let importFile = $state<File | null>(null);
	let importing = $state(false);
	let importStatus = $state<string | null>(null);
	let importError = $state<string | null>(null);

	let canExport = $derived(selected.size > 0 && !exporting);
	let canImport = $derived(importFile !== null && !importing);

	onMount(async () => {
		try {
			runs = await getAllRuns();
		} catch (e) {
			loadError = e instanceof Error ? e.message : 'Failed to load runs.';
		}
	});

	function toggleRun(id: string): void {
		const next = new Set(selected);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		selected = next;
	}

	function selectAll(): void {
		selected = new Set(runs.map((r) => r.id));
	}

	function selectNone(): void {
		selected = new Set();
	}

	async function handleExport(event: Event): Promise<void> {
		event.preventDefault();
		const toExport = runs.filter((r) => selected.has(r.id));
		if (toExport.length === 0) return;

		exporting = true;
		exportStatus = null;
		exportError = null;

		try {
			const blob = await exportRuns(toExport);
			const date = new Date().toISOString().slice(0, 10);
			const filename = `bodaqs-export-${date}.bodaqs.zip`;
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = filename;
			a.click();
			URL.revokeObjectURL(url);
			exportStatus = `Exported ${toExport.length} run${toExport.length === 1 ? '' : 's'}.`;
		} catch (e) {
			exportError = e instanceof Error ? e.message : 'Export failed.';
		} finally {
			exporting = false;
		}
	}

	async function handleImport(event: Event): Promise<void> {
		event.preventDefault();
		if (!importFile) return;

		importing = true;
		importStatus = null;
		importError = null;

		try {
			const { imported, skipped } = await importZip(importFile);
			importStatus = `Imported ${imported} run${imported === 1 ? '' : 's'}${skipped > 0 ? `, skipped ${skipped} already in library` : ''}.`;
			runs = await getAllRuns();
		} catch (e) {
			importError = e instanceof Error ? e.message : 'Import failed.';
		} finally {
			importing = false;
		}
	}
</script>

<svelte:head>
	<title>BODAQS — Transfer</title>
</svelte:head>

<h1>Transfer</h1>

{#if loadError}
	<p role="alert">{loadError}</p>
{/if}

<section>
	<h2>Export</h2>

	{#if runs.length === 0}
		<p>No runs in library yet.</p>
	{:else}
		<form onsubmit={handleExport}>
			<div class="run-list">
				{#each runs as run (run.id)}
					<label>
						<input
							type="checkbox"
							checked={selected.has(run.id)}
							onchange={() => toggleRun(run.id)}
						/>
						{run.description || run.id}
					</label>
				{/each}
			</div>

			<div class="row">
				<button type="button" onclick={selectAll}>All</button>
				<button type="button" onclick={selectNone}>None</button>
				<button type="submit" disabled={!canExport}>
					{exporting ? 'Exporting…' : `Export ${selected.size > 0 ? selected.size + ' ' : ''}selected`}
				</button>
			</div>

			{#if exportStatus}
				<p>{exportStatus}</p>
			{/if}
			{#if exportError}
				<p role="alert">{exportError}</p>
			{/if}
		</form>
	{/if}
</section>

<section>
	<h2>Import</h2>

	<form onsubmit={handleImport}>
		<label>
			.bodaqs.zip file
			<input
				type="file"
				accept=".bodaqs.zip,.zip"
				onchange={(e) => {
					importFile = (e.target as HTMLInputElement).files?.[0] ?? null;
					importStatus = null;
					importError = null;
				}}
			/>
		</label>

		<button type="submit" disabled={!canImport}>
			{importing ? 'Importing…' : 'Import'}
		</button>

		{#if importStatus}
			<p>{importStatus}</p>
		{/if}
		{#if importError}
			<p role="alert">{importError}</p>
		{/if}
	</form>
</section>

<style>
	section {
		margin-bottom: 2rem;
	}
	.run-list {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		margin-bottom: 0.75rem;
	}
	.row {
		display: flex;
		gap: 0.5rem;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 0.5rem;
	}
</style>
```

- [ ] **Step 3: Run svelte-check**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm run check
```

Expected: 0 errors, 0 warnings.

- [ ] **Step 4: Run full test suite**

```bash
cd /Volumes/www/BODAQS/webapp.bodaqs.net/frontend && npm test
```

Expected: 65 tests pass (no regressions — transfer page has no unit tests, existing tests unchanged).

- [ ] **Step 5: Update SESSION.md**

Read `/Volumes/www/BODAQS/webapp.bodaqs.net/SESSION.md`.

In the Phase status table:
- Change Phase 6 from `🔜 Next` to `✅ Complete (partial — transfer page only), 65/65 tests passing`

Add a "Phase 6 — What was built" section immediately BEFORE the existing "Phase 5 — What was built" section:

```markdown
## Phase 6 — What was built (partial — transfer page only)

### Files modified
```
frontend/src/routes/transfer/
└── +page.svelte  — ZIP export (run selector, download trigger) + ZIP import (file picker, imported/skipped report)
```

### Key decisions made

**Export:** User selects runs via checkboxes, "Export selected" calls existing `exportRuns()` → browser download as `bodaqs-export-{YYYY-MM-DD}.bodaqs.zip`. Select All / None shortcuts included.

**Import:** File picker + "Import" calls existing `importZip()` → reports "Imported N, skipped M". On success, the run list reloads from Dexie so newly imported runs appear in the export list immediately.

**No new lib code:** `lib/zip/export.ts` and `lib/zip/import.ts` were already complete and tested in Phase 3. The transfer page is pure UI wiring.

**Deployment not included:** Vercel deploy setup is out of scope for this session.
```

- [ ] **Step 6: Commit**

```bash
cd /Volumes/www/BODAQS && git add webapp.bodaqs.net/frontend/src/routes/transfer/+page.svelte webapp.bodaqs.net/SESSION.md
git commit -m "feat(frontend): transfer page — ZIP export with run selector and import with status"
```

---

## Self-review against spec

| Spec requirement | Status |
|---|---|
| Export selected runs as `.bodaqs.zip` | ✅ Task 1 (`exportRuns`, download trigger) |
| Import a ZIP and merge into library | ✅ Task 1 (`importZip`, result message) |
| Skip duplicate runs on import (by run_id) | ✅ Already in `importZip` — skipped count surfaced in UI |
| Show imported/skipped counts | ✅ Task 1 (import status message) |
| Never silently fail | ✅ Both forms show `role="alert"` error paragraphs |
| Disabled states while in-flight | ✅ `canExport` / `canImport` derived flags |

### Placeholder scan

No TBD, no "implement later", complete code in every step. ✅

### Type consistency

- `exportRuns(runs: Run[]): Promise<Blob>` — called with `runs.filter(r => selected.has(r.id))` which is `Run[]` ✅
- `importZip(file: File): Promise<{imported: number; skipped: number}>` — called with `importFile` which is `File | null`, guarded by `if (!importFile) return` ✅
- `getAllRuns(): Promise<Run[]>` — used in `onMount` and after import, returns `Run[]` ✅
