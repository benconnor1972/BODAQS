<script lang="ts">
	import favicon from '$lib/assets/favicon.svg';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<nav>
	<a href="/">Library</a>
	<a href="/preprocess">Preprocess</a>
	<a href="/transfer">Export / Import</a>
</nav>

<main>
	{@render children()}
</main>
