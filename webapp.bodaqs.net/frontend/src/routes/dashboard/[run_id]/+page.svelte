<script lang="ts">
  import { page } from "$app/state";
  import { decodeSignalColumn } from "$lib/api/preprocess";
  import {
    getSessionsForRun,
    getSignalsForSession,
    getEventsForSession,
    getMetricsForSession
  } from "$lib/db/artifacts";
  import type { Session } from "$lib/db/dexie";
  import {
    findDisplacementColumn,
    findVelocityColumn,
    prepareEventsBar,
    prepareMetricScatter
  } from "$lib/charts/prepare";
  import DisplacementHistogram from "$lib/charts/DisplacementHistogram.svelte";
  import VelocityHistogram from "$lib/charts/VelocityHistogram.svelte";
  import EventsBar from "$lib/charts/EventsBar.svelte";
  import MetricScatter from "$lib/charts/MetricScatter.svelte";

  const run_id = $derived(page.params.run_id);

  let sessions = $state<Session[]>([]);
  let selectedSessionId = $state<string | null>(null);
  let normalised = $state(true);
  let loading = $state(false);
  let error = $state<string | null>(null);

  let signals = $state<Record<string, Float32Array>>({});
  let events = $state<Record<string, unknown>[]>([]);
  let metrics = $state<Record<string, unknown>[]>([]);
  let columnNames = $state<string[]>([]);

  $effect(() => {
    const id = run_id;
    if (!id) return;
    sessions = [];
    selectedSessionId = null;
    error = null;
    getSessionsForRun(id)
      .then((list) => {
        sessions = list;
        if (list.length > 0) selectedSessionId = list[0].id;
      })
      .catch((e) => {
        error = e instanceof Error ? e.message : "Failed to load sessions.";
      });
  });

  $effect(() => {
    if (!selectedSessionId) return;
    loadSession(selectedSessionId);
  });

  let loadGeneration = 0;

  async function loadSession(session_id: string): Promise<void> {
    const gen = ++loadGeneration;
    loading = true;
    error = null;
    signals = {};
    columnNames = [];
    events = [];
    metrics = [];
    try {
      const [signalRows, eventRows, metricRows] = await Promise.all([
        getSignalsForSession(session_id),
        getEventsForSession(session_id),
        getMetricsForSession(session_id)
      ]);

      if (gen !== loadGeneration) return;

      const decoded: Record<string, Float32Array> = {};
      for (const row of signalRows) {
        decoded[row.column_name] = decodeSignalColumn(row.data);
      }

      signals = decoded;
      columnNames = Object.keys(decoded);
      events = eventRows.flatMap((r) => r.rows);
      metrics = metricRows.flatMap((r) => r.rows);
    } catch (e) {
      if (gen === loadGeneration) {
        error = e instanceof Error ? e.message : "Failed to load session data.";
      }
    } finally {
      if (gen === loadGeneration) loading = false;
    }
  }

  let frontDispCol = $derived(findDisplacementColumn(columnNames, "front", normalised));
  let rearDispCol = $derived(findDisplacementColumn(columnNames, "rear", normalised));
  let frontVelCol = $derived(findVelocityColumn(columnNames, "front"));
  let rearVelCol = $derived(findVelocityColumn(columnNames, "rear"));

  let frontDispData = $derived(frontDispCol ? (signals[frontDispCol] ?? null) : null);
  let rearDispData = $derived(rearDispCol ? (signals[rearDispCol] ?? null) : null);
  let frontVelData = $derived(frontVelCol ? (signals[frontVelCol] ?? null) : null);
  let rearVelData = $derived(rearVelCol ? (signals[rearVelCol] ?? null) : null);

  let frontEventsBar = $derived(prepareEventsBar(events, "front"));
  let rearEventsBar = $derived(prepareEventsBar(events, "rear"));

  let frontCompScatter = $derived(
    prepareMetricScatter(metrics, "compression", "front", "m_peak_disp_max", "m_interval_vel_max")
  );
  let rearCompScatter = $derived(
    prepareMetricScatter(metrics, "compression", "rear", "m_peak_disp_max", "m_interval_vel_max")
  );
  let frontReboundScatter = $derived(
    prepareMetricScatter(metrics, "rebound", "front", "m_peak_disp_max", "m_interval_vel_min")
  );
  let rearReboundScatter = $derived(
    prepareMetricScatter(metrics, "rebound", "rear", "m_peak_disp_max", "m_interval_vel_min")
  );

  let frontEventsBarData = $derived(frontEventsBar.labels.length > 0 ? frontEventsBar : null);
  let rearEventsBarData = $derived(rearEventsBar.labels.length > 0 ? rearEventsBar : null);
  let frontCompData = $derived(frontCompScatter.x.length > 0 ? frontCompScatter : null);
  let rearCompData = $derived(rearCompScatter.x.length > 0 ? rearCompScatter : null);
  let frontReboundData = $derived(frontReboundScatter.x.length > 0 ? frontReboundScatter : null);
  let rearReboundData = $derived(rearReboundScatter.x.length > 0 ? rearReboundScatter : null);
</script>

<svelte:head>
  <title>BODAQS — Dashboard</title>
</svelte:head>

<h1>Dashboard</h1>

{#if error}
  <p role="alert">{error}</p>
{/if}

<div class="controls">
  {#if sessions.length > 1}
    <label>
      Session
      <select bind:value={selectedSessionId}>
        {#each sessions as s (s.id)}
          <option value={s.id}>{s.id}</option>
        {/each}
      </select>
    </label>
  {/if}

  <label>
    <input type="checkbox" bind:checked={normalised} />
    Normalised (0–1)
  </label>
</div>

{#if loading}
  <p>Loading…</p>
{:else}
  <div class="grid">
    <DisplacementHistogram
      title="Front Suspension: Displacement"
      data={frontDispData}
      {normalised}
    />
    <DisplacementHistogram title="Rear Suspension: Displacement" data={rearDispData} {normalised} />

    <VelocityHistogram title="Front Suspension: Velocity" data={frontVelData} />
    <VelocityHistogram title="Rear Suspension: Velocity" data={rearVelData} />

    <EventsBar title="Front Suspension: Events" data={frontEventsBarData} />
    <EventsBar title="Rear Suspension: Events" data={rearEventsBarData} />

    <MetricScatter
      title="Front Suspension: Compressions >25%"
      data={frontCompData}
      yLabel="Max velocity (mm/s)"
    />
    <MetricScatter
      title="Rear Suspension: Compressions >25%"
      data={rearCompData}
      yLabel="Max velocity (mm/s)"
    />

    <MetricScatter
      title="Front Suspension: Rebounds >25%"
      data={frontReboundData}
      yLabel="Min velocity (mm/s)"
    />
    <MetricScatter
      title="Rear Suspension: Rebounds >25%"
      data={rearReboundData}
      yLabel="Min velocity (mm/s)"
    />
  </div>
{/if}

<style>
  .controls {
    display: flex;
    gap: 1.5rem;
    align-items: center;
    margin-bottom: 1rem;
    flex-wrap: wrap;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  @media (max-width: 700px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
