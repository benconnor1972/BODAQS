<script lang="ts">
  import Plotly from "plotly.js-dist-min";
  import EmptyTile from "./EmptyTile.svelte";
  import { computeHistogram, computePercentileRange } from "./prepare";

  interface Props {
    title: string;
    data: Float32Array | null;
    normalised: boolean;
  }
  const { title, data, normalised }: Props = $props();

  let container = $state<HTMLDivElement | undefined>();

  $effect(() => {
    if (!container || !data || data.length === 0) return;
    const el = container;

    const range = computePercentileRange(data, 5, 95);
    const { binEdges, counts } = computeHistogram(data, 50, range);
    const xLabel = normalised ? "Displacement (normalised)" : "Displacement (mm)";

    Plotly.newPlot(
      el,
      [
        {
          x: binEdges.slice(0, -1),
          y: counts,
          type: "bar",
          name: title,
          marker: { color: "#1f77b4" }
        }
      ],
      {
        title: { text: title, font: { size: 13 } },
        xaxis: { title: { text: xLabel } },
        yaxis: { title: { text: "Count" } },
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
