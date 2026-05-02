export interface SignalsPayload {
  column_names: string[];
  n_rows: number;
  columns: Record<string, string>; // column name → base64 float32 LE
}

export interface PreprocessResponse {
  session_id: string;
  meta: Record<string, unknown>;
  source_sha256: string;
  signals: SignalsPayload;
  events: Record<string, unknown>[];
  metrics: Record<string, unknown>[];
  warnings: string[];
}

export interface PreprocessFormData {
  csv_file: File;
  bike_profile_json: File;
  sidecar_json: File;
  event_schema_yaml: File;
  preprocess_profile_json?: File;
}

export async function postPreprocess(data: PreprocessFormData): Promise<PreprocessResponse> {
  const form = new FormData();
  form.append("csv_file", data.csv_file);
  form.append("bike_profile_json", data.bike_profile_json);
  form.append("sidecar_json", data.sidecar_json);
  form.append("event_schema_yaml", data.event_schema_yaml);
  if (data.preprocess_profile_json) {
    form.append("preprocess_profile_json", data.preprocess_profile_json);
  }

  const response = await fetch("/api/preprocess", { method: "POST", body: form });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Preprocess failed (${response.status}): ${text}`);
  }
  return response.json() as Promise<PreprocessResponse>;
}

export function decodeSignalColumn(base64: string): Float32Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Float32Array(bytes.buffer);
}
