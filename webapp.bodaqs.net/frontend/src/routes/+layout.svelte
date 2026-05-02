<script lang="ts">
  import type { Snippet } from "svelte";
  import { resolve } from "$app/paths";

  let { children }: { children: Snippet } = $props();
</script>

<nav>
  <a href={resolve("/")}>Library</a>
  <a href={resolve("/upload")}>Upload</a>
  <a href={resolve("/transfer")}>Transfer</a>
</nav>

<main>
  {@render children()}
</main>

<style>
  nav {
    display: flex;
    gap: 1rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid #e5e7eb;
  }
  main {
    padding: 1rem;
  }
</style>
