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
			setTimeout(() => URL.revokeObjectURL(url), 60_000);
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
