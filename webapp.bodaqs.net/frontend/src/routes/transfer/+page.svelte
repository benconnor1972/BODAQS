<script lang="ts">
  import { libraryStore } from '$lib/stores/library';
  import { exportRunsToZip, downloadBlob } from '$lib/zip/export';
  import { previewZip, importSelectedRuns, type ZipRunPreview } from '$lib/zip/import';

  // --- Export ---
  let exportSelected = $state(new Set<string>());

  function toggleExport(runId: string) {
    if (exportSelected.has(runId)) {
      exportSelected.delete(runId);
    } else {
      exportSelected.add(runId);
    }
    exportSelected = new Set(exportSelected);
  }

  async function doExport() {
    const runs = $libraryStore.filter((r) => exportSelected.has(r.run_id));
    const blob = await exportRunsToZip(runs);
    downloadBlob(blob, `bodaqs-export-${new Date().toISOString().slice(0, 10)}.zip`);
  }

  // --- Import ---
  let importPreviews: ZipRunPreview[] = $state([]);
  let importFile: File | null = $state(null);
  let importSelected = $state(new Set<string>());
  let importResult: { imported: number; skipped: number } | null = $state(null);

  async function onImportFilePick(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    importFile = file;
    importPreviews = await previewZip(file);
    importSelected = new Set(importPreviews.map((p) => p.run_id));
  }

  function toggleImport(runId: string) {
    if (importSelected.has(runId)) {
      importSelected.delete(runId);
    } else {
      importSelected.add(runId);
    }
    importSelected = new Set(importSelected);
  }

  async function doImport() {
    if (!importFile) return;
    importResult = await importSelectedRuns(importFile, [...importSelected]);
  }
</script>

<h1>Export / Import</h1>

<section>
  <h2>Export</h2>
  {#if $libraryStore.length === 0}
    <p>No runs to export.</p>
  {:else}
    {#each $libraryStore as run}
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
    {#each importPreviews as preview}
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
