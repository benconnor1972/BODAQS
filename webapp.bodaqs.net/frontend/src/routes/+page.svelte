<script lang="ts">
  import { libraryStore } from "$lib/stores/library.svelte";
  import { resolve } from '$app/paths';

  const doClearLibrary = () => {
    if (confirm('Are you sure you want to clear the entire library? This action cannot be undone.')) {
      libraryStore.clear();
    }
  };

</script>

<h1>Library</h1>

{#if libraryStore.runs.length === 0}
  <p>
    No runs yet. <a
      href={resolve("/preprocess")}>Preprocess some CSV files</a
    > to get started.
  </p>
{:else}
  {#each libraryStore.runs as run(run.run_id)}
    <section >
      <h2>{run.run_id}</h2>
      <p>{run.description || "No description"}</p>
      <p>{run.session_ids.length} session(s)</p>
    </section>
    <section>
      <h2>Clear Library</h2>
      <button onclick={doClearLibrary}>Clear Data</button>
    </section>
  {/each}
{/if}
