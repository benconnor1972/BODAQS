<script lang="ts">
	import { onDestroy } from 'svelte';
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import type { EventsBarData } from './prepare';

	interface Props {
		title: string;
		data: EventsBarData | null;
	}
	const { title, data }: Props = $props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.labels.length === 0) return;

		Plotly.newPlot(
			container,
			[
				{
					x: data.labels,
					y: data.counts,
					type: 'bar',
					marker: { color: '#2ca02c' }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: 'Event type' }, tickangle: -20 },
				yaxis: { title: { text: 'Count' } },
				margin: { t: 40, r: 20, b: 80, l: 55 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			if (container) Plotly.purge(container);
		};
	});

	onDestroy(() => {
		if (container) Plotly.purge(container);
	});
</script>

{#if data && data.labels.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
