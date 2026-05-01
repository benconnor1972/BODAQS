<script lang="ts">
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import { computeHistogram } from './prepare';

	interface Props {
		title: string;
		data: Float32Array | null;
	}
	const { title, data }: Props = $props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.length === 0) return;
		const el = container;

		const ABS_LIMIT = 2000;
		const { binEdges, counts } = computeHistogram(data, 100, [-ABS_LIMIT, ABS_LIMIT]);

		Plotly.newPlot(
			el,
			[
				{
					x: binEdges.slice(0, -1),
					y: counts,
					type: 'bar',
					name: title,
					marker: { color: '#ff7f0e' }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: 'Velocity (mm/s)' } },
				yaxis: { title: { text: 'Count' } },
				margin: { t: 40, r: 20, b: 50, l: 55 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			Plotly.purge(el);
		};
	});
</script>

{#if data && data.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
