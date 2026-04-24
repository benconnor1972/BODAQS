<script lang="ts">
import favicon from "$lib/assets/favicon.svg";
import { resolve } from '$app/paths';

let { children } = $props();
</script>

<svelte:head>
<link rel="icon" href={favicon} />
</svelte:head>

<nav>
  <a href={resolve("/")}>Library</a> |
  <a href={resolve("/preprocess")}>Preprocess</a> |
  <a href={resolve("/transfer")}>Export / Import</a>
</nav>

<main>
  {@render children()}
</main>
