<script lang="ts">
  import { preprocessCsv, type PreprocessConfig } from '$lib/api/preprocess';
  import { storePreprocessResult } from '$lib/db/artifacts';
  import { libraryStore } from '$lib/stores/library.svelte';
  import { makeRunId } from '$lib/utils/run-id';

  type FileStatus = 'pending' | 'duplicate' | 'uploading' | 'done' | 'error';
  interface FileEntry {
    file: File;
    status: FileStatus;
    sha?: string;
    error?: string;
  }

  let files: FileEntry[] = $state([]);
  let runId = $state(makeRunId());
  let schemaYaml = $state('');
  let normalizeRangesRaw = $state('{"front_shock_dom_suspension [mm]": 170, "rear_shock_dom_suspension [mm]": 150}');
  let zeroingEnabled = $state(false);
  let running = $state(false);

  async function hashFile(file: File): Promise<string> {
    const buf = await file.arrayBuffer();
    const hashBuf = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hashBuf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }

  async function onFilePick(e: Event) {
    const input = e.target as HTMLInputElement;
    const picked = Array.from(input.files ?? []);
    files = await Promise.all(
      picked.map(async (f) => {
        const sha = await hashFile(f);
        const isDup = libraryStore.runs.some((r) => r.sha_set.includes(sha));
        const status: FileStatus = isDup ? 'duplicate' : 'pending';
        return { file: f, status, sha };
      })
    );
  }

  async function processAll() {
    let normalizeRanges: Record<string, number>;
    try {
      normalizeRanges = JSON.parse(normalizeRangesRaw);
    } catch {
      alert('Normalize ranges is not valid JSON');
      return;
    }
    if (!schemaYaml.trim()) {
      alert('Paste the event schema YAML before processing');
      return;
    }

    const config: PreprocessConfig = {
      schema_yaml: schemaYaml,
      normalize_ranges: normalizeRanges,
      zeroing_enabled: zeroingEnabled,
      strict: false,
    };

    running = true;
    for (const entry of files) {
      if (entry.status === 'duplicate') continue;
      entry.status = 'uploading';
      try {
        const result = await preprocessCsv(entry.file, config);
        await storePreprocessResult(runId, result);
        libraryStore.addSessionToRun(runId, result.session_id, result.source_sha256);
        entry.status = 'done';
      } catch (err) {
        entry.status = 'error';
        entry.error = String(err);
      }
    }
    running = false;
  }

  const statusLabel: Record<FileStatus, string> = {
    pending: 'Pending',
    duplicate: 'Already processed',
    uploading: 'Processing…',
    done: 'Done',
    error: 'Error',
  };
</script>

<h1>Preprocess CSV Files</h1>

<div>
  <label>
    <span>Event Schema YAML</span>
    <textarea bind:value={schemaYaml} rows="8" placeholder="Paste event_schema.yaml contents here…"></textarea>
  </label>
</div>

<div>
  <label>
    <span>Normalize ranges (JSON)</span>
    <textarea bind:value={normalizeRangesRaw}></textarea>
  </label>
</div>

<div>
  <label>
    <input type="checkbox" bind:checked={zeroingEnabled} />
    Zeroing enabled
  </label>
</div>

<hr />
<form>
<input type="file" accept=".CSV,.csv" multiple onchange={onFilePick} />
</form>

{#if files.length > 0}
  <table>
    <thead>
      <tr>
        <th>File</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {#each files as entry(entry.sha)}
        <tr>
          <td>{entry.file.name}</td>
          <td>
            {statusLabel[entry.status]}
            {#if entry.error} — {entry.error}{/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <button onclick={processAll} disabled={running}>
    {running ? 'Processing…' : `Process ${files.filter((f) => f.status === 'pending').length} file(s)`}
  </button>
{/if}
