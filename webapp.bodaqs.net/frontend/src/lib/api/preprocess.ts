export interface PreprocessConfig {
  schema_yaml: string;
  normalize_ranges: Record<string, number>;
  strict?: boolean;
  zeroing_enabled?: boolean;
  zero_window_s?: number;
  zero_min_samples?: number;
  clip_0_1?: boolean;
  butterworth_smoothing?: Array<{ cutoff_hz: number; order?: number }>;
  butterworth_generate_residuals?: boolean;
  active_signal_disp_col?: string | null;
  active_signal_vel_col?: string | null;
  active_disp_thresh?: number;
  active_vel_thresh?: number;
  active_window?: string;
  active_padding?: string;
  active_min_seg?: string;
  sample_rate_hz?: number | null;
}

export interface PreprocessResponse {
  session_id: string;
  meta: Record<string, unknown>;
  signals: {
    column_names: string[];
    n_rows: number;
    columns: Record<string, string>; // base64-encoded float32 per column
  };
  events: Record<string, unknown>[];
  metrics: Record<string, unknown>[];
  source_sha256: string;
}

async function compressGzip(data: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer>> {
  const stream = new CompressionStream("gzip");
  // Must start consuming readable before writing — TransformStream backpressure
  // will deadlock write() if the readable side isn't already being drained.
  const outputPromise = new Response(stream.readable).arrayBuffer();
  const writer = stream.writable.getWriter();
  await writer.write(data);
  await writer.close();
  return new Uint8Array(await outputPromise);
}

export async function preprocessCsv(
  file: File,
  config: PreprocessConfig
): Promise<PreprocessResponse> {
  console.log(`Preprocessing file ${file.name} `);

  const rawBytes = new Uint8Array(await file.arrayBuffer());

  console.log(`Read ${rawBytes.length} bytes from file`);
  const compressed = await compressGzip(rawBytes);

  console.log(`Compressed ${rawBytes.length} bytes to ${compressed.length} bytes`);

  const form = new FormData();
  form.append("csv_file", new Blob([compressed], { type: "application/gzip" }), file.name + ".gz");
  form.append("config_json", JSON.stringify(config));

  const apiBase = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
  const resp = await fetch(`${apiBase}/api/preprocess`, { method: "POST", body: form });

  if (!resp.ok) {
    const err = (await resp.json().catch(() => ({}))) as Record<string, unknown>;
    throw new Error(String(err.detail ?? `Server error ${resp.status}`));
  }
  return (await resp.json()) as PreprocessResponse;
}
