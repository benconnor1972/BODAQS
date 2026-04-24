<script lang="ts">
import { libraryStore } from "$lib/stores/library.svelte";
import { downloadBlob, exportRunsToZip } from "$lib/zip/export";
import {
  importSelectedRuns,
  previewZip,
  type ZipRunPreview,
} from "$lib/zip/import";
import { SvelteSet } from 'svelte/reactivity';
/** Holds the set of run IDs selected for export. */
let exportSelected = new SvelteSet<string>();

/** Adds/remones a runID from the exportSelected set */
const toggleExport = (runId: string) => {
  if (exportSelected.has(runId)) {
    exportSelected.delete(runId);
  } else {
    exportSelected.add(runId);
  }
};

/** Collect the selected runs and call the zipper */
const doExport = async () => {
  const runs = libraryStore.runs.filter((r) => exportSelected.has(r.run_id));
  const blob = await exportRunsToZip(runs);
  downloadBlob(
    blob,
    `bodaqs-export-${new Date().toISOString().slice(0, 10)}.zip`,
  );
};

// --- Import ---
let importPreviews: ZipRunPreview[] = $state([]);
let importFile: File | undefined = $state();
let importSelected = new SvelteSet<string>();
let importResult: { imported: number; skipped: number } | null = $state(null);

// TODO, make this a more proactive user decision (click up upload button)
const onImportFilePick = async (e: Event) => {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  importFile = file;

  importPreviews = await previewZip(file);

  for (const preview of importPreviews) {
    importSelected.add(preview.run_id);
  }
};

const toggleImport = (runId: string) => {
  if (importSelected.has(runId)) {
    importSelected.delete(runId);
  } else {
    importSelected.add(runId);
  }
};


// todo, make this part of importSelectedRuns directly
const doImport = async () => {
  if (!importFile) return;
  importResult = await importSelectedRuns(importFile, [...importSelected]);
};
</script>

<h1>Export / Import</h1>

<section>
  <h2>Export</h2>
  {#if libraryStore.runs.length === 0}
    <p>No runs to export.</p>
  {:else}
    {#each libraryStore.runs as run(run.run_id)}
      <label>
        <input
          type="checkbox"
          checked={exportSelected.has(run.run_id)}
          onchange={() => toggleExport(run.run_id)}
        />
        {run.run_id} — {run.description || 'No description'} ({run.session_ids.length} session(s))
      </label>
    {/each}
    <br />
    <button onclick={doExport} disabled={exportSelected.size === 0}>
      Export {exportSelected.size} run(s)
    </button>
  {/if}
</section>

<section>
  <h2>Import</h2>
  <input type="file" accept=".zip" onchange={onImportFilePick} />

  {#if importPreviews.length > 0}

    <p>Select runs to import:</p>
    {#each importPreviews as preview(preview.run_id)}
      <label>
        <input
          type="checkbox"
          checked={importSelected.has(preview.run_id)}
          onchange={() => toggleImport(preview.run_id)}
        />
        {preview.run_id} — {preview.description || 'No description'}
        ({preview.session_ids.length} session(s), ~{preview.estimated_size_mb} MB)
      </label>
    {/each}
    <br />
    <button onclick={doImport} disabled={importSelected.size === 0}>
      Import {importSelected.size} run(s)
    </button>
  {/if}

  {#if importResult}
    <p>Done — {importResult.imported} imported, {importResult.skipped} skipped (already present).</p>
  {/if}
</section>
