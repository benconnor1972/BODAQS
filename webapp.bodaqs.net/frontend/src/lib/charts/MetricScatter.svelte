<script lang="ts">
	import Plotly from 'plotly.js-dist-min';
	import EmptyTile from './EmptyTile.svelte';
	import type { ScatterData } from './prepare';

	interface Props {
		title: string;
		data: ScatterData | null;
		xLabel?: string;
		yLabel?: string;
	}
	const { title, data, xLabel = 'Peak displacement (mm)', yLabel = 'Velocity (mm/s)' }: Props =
		$props();

	let container = $state<HTMLDivElement | undefined>();

	$effect(() => {
		if (!container || !data || data.x.length === 0) return;
		const el = container;

		Plotly.newPlot(
			el,
			[
				{
					x: data.x,
					y: data.y,
					mode: 'markers',
					type: 'scatter',
					marker: { color: '#9467bd', size: 6, opacity: 0.7 }
				}
			],
			{
				title: { text: title, font: { size: 13 } },
				xaxis: { title: { text: xLabel } },
				yaxis: { title: { text: yLabel } },
				margin: { t: 40, r: 20, b: 50, l: 65 },
				height: 300
			},
			{ responsive: true, displayModeBar: false }
		);

		return () => {
			Plotly.purge(el);
		};
	});
</script>

{#if data && data.x.length > 0}
	<div bind:this={container}></div>
{:else}
	<EmptyTile {title} />
{/if}
