import { describe, expect, it } from "vitest";
import type { PreprocessResponse } from "$lib/api/preprocess";
import { decodeSignalColumn } from "$lib/api/preprocess";

function encodeFloat32LE(values: number[]): string {
  const bytes = new Uint8Array(new Float32Array(values).buffer);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary);
}

describe("decodeSignalColumn", () => {
  it("returns a Float32Array", () => {
    const result = decodeSignalColumn(encodeFloat32LE([1.0]));
    expect(result).toBeInstanceOf(Float32Array);
  });

  it("decodes a single float32 value", () => {
    const result = decodeSignalColumn(encodeFloat32LE([1.0]));
    expect(result).toHaveLength(1);
    expect(result[0]).toBeCloseTo(1.0, 6);
  });

  it("decodes multiple values including negative and fractional", () => {
    const values = [0.0, -1.5, 100.25];
    const result = decodeSignalColumn(encodeFloat32LE(values));
    expect(result).toHaveLength(3);
    expect(result[0]).toBeCloseTo(0.0, 6);
    expect(result[1]).toBeCloseTo(-1.5, 5);
    expect(result[2]).toBeCloseTo(100.25, 4);
  });

  it("round-trips through the backend encoding contract (LE byte order)", () => {
    // Float32 1.0 is bytes: 00 00 80 3F (little-endian)
    const base64 = btoa(String.fromCharCode(0x00, 0x00, 0x80, 0x3f));
    const result = decodeSignalColumn(base64);
    expect(result[0]).toBeCloseTo(1.0, 6);
  });
});

describe("PreprocessResponse type shape", () => {
  it("accepts a well-formed response object", () => {
    const response: PreprocessResponse = {
      session_id: "2026-04-29_11-16-50",
      meta: { filename: "ride.csv", duration_s: 600 },
      source_sha256: "abc123def456",
      signals: {
        column_names: ["front_wheel_disp_dom_wheel [mm]"],
        n_rows: 12345,
        columns: { "front_wheel_disp_dom_wheel [mm]": "AAAA" }
      },
      events: [{ type: "bottom_out", t: 1.5, end_t: 2.0 }],
      metrics: [{ name: "max_travel", value: 150.0 }],
      warnings: ["rear signal missing"]
    };
    expect(response.session_id).toBe("2026-04-29_11-16-50");
    expect(response.signals.column_names).toHaveLength(1);
    expect(response.signals.n_rows).toBe(12345);
    expect(response.events).toHaveLength(1);
    expect(response.warnings).toHaveLength(1);
  });

  it("accepts an empty signals/events/metrics response (partial result)", () => {
    const response: PreprocessResponse = {
      session_id: "partial",
      meta: {},
      source_sha256: "",
      signals: { column_names: [], n_rows: 0, columns: {} },
      events: [],
      metrics: [],
      warnings: ["no signals found"]
    };
    expect(response.signals.column_names).toHaveLength(0);
    expect(response.warnings).toHaveLength(1);
  });
});
