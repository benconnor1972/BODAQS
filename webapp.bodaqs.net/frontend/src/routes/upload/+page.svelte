<script lang="ts">
	import { goto } from '$app/navigation';
	import { postPreprocess } from '$lib/api/preprocess';
	import { saveRun, saveSession } from '$lib/db/artifacts';
	import { validateUploadFiles, isUploadReady } from '$lib/upload/validate';
	import type { UploadFiles } from '$lib/upload/validate';

	let files = $state<UploadFiles>({
		csv_file: null,
		bike_profile_json: null,
		sidecar_json: null,
		event_schema_yaml: null,
		preprocess_profile_json: null
	});

	let submitting = $state(false);
	let validationErrors = $state<string[]>([]);
	let apiError = $state<string | null>(null);

	let ready = $derived(isUploadReady(files));

	function onFileChange(field: keyof UploadFiles, event: Event): void {
		const input = event.target as HTMLInputElement;
		files = { ...files, [field]: input.files?.[0] ?? null };
	}

	async function handleSubmit(event: Event): Promise<void> {
		event.preventDefault();
		validationErrors = validateUploadFiles(files);
		if (validationErrors.length > 0) return;

		submitting = true;
		apiError = null;

		try {
			const response = await postPreprocess({
				csv_file: files.csv_file!,
				bike_profile_json: files.bike_profile_json!,
				sidecar_json: files.sidecar_json!,
				event_schema_yaml: files.event_schema_yaml!,
				preprocess_profile_json: files.preprocess_profile_json ?? undefined
			});

			const run_id = crypto.randomUUID();
			const run = {
				id: run_id,
				description: files.csv_file!.name.replace(/\.[^.]+$/, ''),
				created_at: new Date().toISOString(),
				session_ids: []
			};

			await saveRun(run);
			await saveSession(run_id, response);

			goto(`/dashboard/${run_id}`);
		} catch (err) {
			apiError = err instanceof Error ? err.message : 'Upload failed. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>BODAQS — Upload</title>
</svelte:head>

<h1>Upload Ride</h1>

<form onsubmit={handleSubmit}>
	<fieldset>
		<legend>Required files</legend>

		<label>
			Logger CSV *
			<input type="file" accept=".csv,.CSV" onchange={(e) => onFileChange('csv_file', e)} />
		</label>

		<label>
			Bike Profile JSON *
			<input
				type="file"
				accept=".json"
				onchange={(e) => onFileChange('bike_profile_json', e)}
			/>
		</label>

		<label>
			Sidecar JSON *
			<input type="file" accept=".json" onchange={(e) => onFileChange('sidecar_json', e)} />
		</label>

		<label>
			Event Schema YAML *
			<input
				type="file"
				accept=".yaml,.yml"
				onchange={(e) => onFileChange('event_schema_yaml', e)}
			/>
		</label>
	</fieldset>

	<fieldset>
		<legend>Optional files</legend>

		<label>
			Preprocess Profile JSON
			<input
				type="file"
				accept=".json"
				onchange={(e) => onFileChange('preprocess_profile_json', e)}
			/>
		</label>
	</fieldset>

	{#if validationErrors.length > 0}
		<ul role="alert">
			{#each validationErrors as error}
				<li>{error}</li>
			{/each}
		</ul>
	{/if}

	{#if apiError}
		<p role="alert">{apiError}</p>
	{/if}

	<button type="submit" disabled={!ready || submitting}>
		{submitting ? 'Processing…' : 'Process Ride'}
	</button>
</form>
