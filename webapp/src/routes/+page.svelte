<script lang="ts">
	import { libraryStore } from '$lib/stores/library';
</script>

<h1>Library</h1>

{#if $libraryStore.length === 0}
	<p>No runs yet. <a href="/preprocess">Preprocess some CSV files</a> to get started.</p>
{:else}
	{#each $libraryStore as run}
		<section>
			<h2>{run.run_id}</h2>
			<p>{run.description || 'No description'}</p>
			<p>{run.session_ids.length} session(s)</p>
		</section>
	{/each}
{/if}
