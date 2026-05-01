export const MAX_CSV_BYTES = 50 * 1024 * 1024; // 50 MB

export interface UploadFiles {
	csv_file: File | null;
	bike_profile_json: File | null;
	sidecar_json: File | null;
	event_schema_yaml: File | null;
	preprocess_profile_json: File | null;
}

export function validateUploadFiles(files: UploadFiles): string[] {
	const errors: string[] = [];

	if (!files.csv_file) {
		errors.push('Logger CSV is required.');
	} else if (files.csv_file.size > MAX_CSV_BYTES) {
		errors.push(
			`CSV file exceeds 50 MB limit (${(files.csv_file.size / 1024 / 1024).toFixed(1)} MB).`
		);
	}

	if (!files.bike_profile_json) {
		errors.push('Bike profile JSON is required.');
	} else if (!files.bike_profile_json.name.toLowerCase().endsWith('.json')) {
		errors.push('Bike profile must be a .json file.');
	}

	if (!files.sidecar_json) {
		errors.push('Sidecar JSON is required.');
	} else if (!files.sidecar_json.name.toLowerCase().endsWith('.json')) {
		errors.push('Sidecar must be a .json file.');
	}

	if (!files.event_schema_yaml) {
		errors.push('Event schema YAML is required.');
	} else if (
		!files.event_schema_yaml.name.toLowerCase().endsWith('.yaml') &&
		!files.event_schema_yaml.name.toLowerCase().endsWith('.yml')
	) {
		errors.push('Event schema must be a .yaml or .yml file.');
	}

	if (
		files.preprocess_profile_json &&
		!files.preprocess_profile_json.name.toLowerCase().endsWith('.json')
	) {
		errors.push('Preprocess profile must be a .json file.');
	}

	return errors;
}

export function isUploadReady(files: UploadFiles): boolean {
	return (
		files.csv_file !== null &&
		files.csv_file.size <= MAX_CSV_BYTES &&
		files.bike_profile_json !== null &&
		files.sidecar_json !== null &&
		files.event_schema_yaml !== null
	);
}
