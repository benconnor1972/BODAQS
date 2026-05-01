import { describe, expect, it } from 'vitest';
import { validateUploadFiles, isUploadReady, MAX_CSV_BYTES } from '$lib/upload/validate';
import type { UploadFiles } from '$lib/upload/validate';

function mockFile(name: string, sizeBytes = 100): File {
	const file = new File([], name);
	Object.defineProperty(file, 'size', { value: sizeBytes, configurable: true });
	return file;
}

const validFiles: UploadFiles = {
	csv_file: mockFile('ride.csv'),
	bike_profile_json: mockFile('bike.json'),
	sidecar_json: mockFile('sidecar.json'),
	event_schema_yaml: mockFile('schema.yaml'),
	preprocess_profile_json: null
};

describe('validateUploadFiles', () => {
	it('returns no errors when all required files are valid', () => {
		expect(validateUploadFiles(validFiles)).toHaveLength(0);
	});

	it('returns error when csv_file is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, csv_file: null });
		expect(errors.some((e) => e.includes('CSV'))).toBe(true);
	});

	it('returns error when CSV exceeds 50 MB', () => {
		const bigCsv = mockFile('ride.csv', MAX_CSV_BYTES + 1);
		const errors = validateUploadFiles({ ...validFiles, csv_file: bigCsv });
		expect(errors.some((e) => e.includes('50 MB'))).toBe(true);
	});

	it('returns error when bike_profile_json is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, bike_profile_json: null });
		expect(errors.some((e) => e.toLowerCase().includes('bike profile'))).toBe(true);
	});

	it('returns error when bike_profile_json has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, bike_profile_json: mockFile('bike.txt') });
		expect(errors.some((e) => e.toLowerCase().includes('bike profile'))).toBe(true);
	});

	it('returns error when sidecar_json is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, sidecar_json: null });
		expect(errors.some((e) => e.toLowerCase().includes('sidecar'))).toBe(true);
	});

	it('returns error when sidecar_json has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, sidecar_json: mockFile('sidecar.txt') });
		expect(errors.some((e) => e.toLowerCase().includes('sidecar'))).toBe(true);
	});

	it('returns error when event_schema_yaml is missing', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: null });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(true);
	});

	it('returns error when event_schema_yaml has wrong extension', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: mockFile('schema.json') });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(true);
	});

	it('accepts .yml extension for event schema', () => {
		const errors = validateUploadFiles({ ...validFiles, event_schema_yaml: mockFile('schema.yml') });
		expect(errors.some((e) => e.toLowerCase().includes('event schema'))).toBe(false);
	});

	it('returns no error when preprocess_profile_json is null (optional)', () => {
		const errors = validateUploadFiles({ ...validFiles, preprocess_profile_json: null });
		expect(errors).toHaveLength(0);
	});

	it('returns error when preprocess_profile_json has wrong extension', () => {
		const errors = validateUploadFiles({
			...validFiles,
			preprocess_profile_json: mockFile('profile.txt')
		});
		expect(errors.some((e) => e.toLowerCase().includes('preprocess profile'))).toBe(true);
	});

	it('accumulates multiple errors', () => {
		const errors = validateUploadFiles({
			csv_file: null,
			bike_profile_json: null,
			sidecar_json: null,
			event_schema_yaml: null,
			preprocess_profile_json: null
		});
		expect(errors.length).toBeGreaterThanOrEqual(4);
	});
});

describe('isUploadReady', () => {
	it('returns true when all required files are set and CSV is within size', () => {
		expect(isUploadReady(validFiles)).toBe(true);
	});

	it('returns false when csv_file is null', () => {
		expect(isUploadReady({ ...validFiles, csv_file: null })).toBe(false);
	});

	it('returns false when CSV exceeds 50 MB', () => {
		const bigCsv = mockFile('ride.csv', MAX_CSV_BYTES + 1);
		expect(isUploadReady({ ...validFiles, csv_file: bigCsv })).toBe(false);
	});

	it('returns false when bike_profile_json is null', () => {
		expect(isUploadReady({ ...validFiles, bike_profile_json: null })).toBe(false);
	});

	it('returns false when sidecar_json is null', () => {
		expect(isUploadReady({ ...validFiles, sidecar_json: null })).toBe(false);
	});

	it('returns false when event_schema_yaml is null', () => {
		expect(isUploadReady({ ...validFiles, event_schema_yaml: null })).toBe(false);
	});

	it('returns true when preprocess_profile_json is null (optional field)', () => {
		expect(isUploadReady({ ...validFiles, preprocess_profile_json: null })).toBe(true);
	});
});
