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
