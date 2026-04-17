# String Pot Analysis Methodology

This document summarizes the analysis workflow implemented in [string_pot_analysis.ipynb](./string_pot_analysis.ipynb).

## Purpose

The notebook is intended to compare measured string-pot output against an ideal displacement profile generated from the known crank-drive geometry. It supports:

- loading a logger CSV file
- correcting raw ADC counts with a user-supplied polynomial
- unwrapping the periodic count signal
- estimating drive period and phase alignment
- fitting the measured series to the ideal displacement profile
- computing residuals and summarizing phase-dependent error

## Inputs

The analysis is parameterized in the notebook. Key user inputs are:

- `csv_path`: path to the source CSV file
- `time_column`: name of the timestamp column
- `raw_adc_column`: name of the raw string-pot ADC column
- `time_format`: format string for human-readable timestamps
- `analysis_start_time_s`, `analysis_end_time_s`: analysis window in seconds
- `wrap_span_counts`: modulo span of the sensor output
- `c0..c3`: polynomial correction coefficients
- `crank_pin_offset_r_mm`, `entry_offset_l_mm`: crank geometry parameters
- `sample_rate_hz_override`: optional manual sample-rate override
- `driving_speed_rpm_override`: optional manual drive-speed override
- `period_search_min_rpm`, `period_search_max_rpm`: search limits for coarse period estimation
- `fit_shift_search_fraction_of_period`: shift search width for alignment
- `phase_bin_count`, `phase_harmonic_order`: controls for phase-residual analysis

## Processing Pipeline

### 1. Load and window the data

The notebook reads the CSV with `pandas`, extracts the configured time and raw-count columns, converts time to a relative seconds vector, and applies the requested start/end window.

If timestamps are numeric they are used directly. If they are human-readable strings they are parsed using `time_format`.

### 2. Apply polynomial correction

Raw counts are converted to corrected counts using a cubic polynomial:

```text
corrected = c0 + c1*x + c2*x^2 + c3*x^3
```

At present, the polynomial output remains in corrected-count units.

### 3. Unwrap the corrected periodic signal

The corrected counts are unwrapped with a strict nearest-neighbour method.

For each sample, the algorithm considers the current reading and its neighbouring aliases separated by `+- wrap_span_counts`, then chooses the alias nearest to the previous unwrapped sample. This produces a continuous unwrapped count series.

The unwrapped signal is also zeroed to its minimum within the analysis window for fitting and display.

### 4. Estimate sample rate

The sample rate is inferred from the median positive time step unless `sample_rate_hz_override` is provided.

### 5. Estimate a coarse drive period

If `driving_speed_rpm_override` is not provided, the notebook estimates a coarse period from the wrapped corrected counts using circular autocorrelation:

- convert wrapped counts to phase on the unit circle
- correlate the cosine and sine components
- search for the strongest repeating lag within the configured RPM bounds

A Welch spectral cross-check is also reported, but not used directly for fitting.

If `driving_speed_rpm_override` is provided, that speed is used instead of the data-derived estimate.

### 6. Generate the ideal displacement profile

The ideal string displacement is calculated from the crank geometry using:

```text
s(theta) = sqrt(l^2 + r^2 - 2lr cos(theta)) - (l - r)
```

where:

- `r` is the crank-pin offset
- `l` is the entry offset
- `theta = 2*pi*t / period`

This yields the ideal displacement in millimetres for a given period.

### 7. Refine period and time shift from waveform extrema

The notebook does not rely on the coarse period alone for final alignment.

It first detects principal peaks and troughs in the measured unwrapped waveform:

- smooth the signal with a Savitzky-Golay filter
- detect prominent extrema with `scipy.signal.find_peaks`
- refine each extremum time with a local quadratic interpolation for sub-sample timing

From those extrema:

- the mean cycle period is estimated from peak-to-peak and trough-to-trough intervals
- a global grid search is performed over period and time shift around that cycle-timing estimate
- a local refinement is then performed only inside the best basin found by the global search

The alignment objective is based on matching measured extrema times to the ideal extrema grid:

- troughs at phase `0`
- peaks at phase `0.5 * period`

This approach was chosen because it is more robust than residual-minimization alone when the measured waveform contains secondary-vibration effects not represented in the ideal model.

### 8. Scale the measured signal

After period and shift are fitted, the measured series is scaled to match the ideal peak displacement exactly:

```text
scale = ideal_peak_mm / measured_peak_counts
```

This guarantees peak displacement agreement over the valid fit window.

### 9. Compute residuals

Residuals are then calculated as:

```text
residual_mm = scaled_measured_mm - ideal_displacement_mm
```

The notebook reports overall metrics such as:

- RMSE
- MAE
- maximum absolute residual
- fitted period, speed, scale, and shift

## Phase-Based Residual Analysis

Residuals are also analyzed as a function of phase using the fitted period.

### Phase folding

Each valid residual sample is assigned a phase:

```text
phase = (time / fitted_period) mod 1
```

This is converted to degrees from `0` to `360`.

### Phase-bin statistics

Residuals are grouped into `phase_bin_count` bins and summarized per bin with:

- mean residual
- standard deviation
- RMS residual
- sample count

This shows both systematic phase-locked error and phase-dependent spread.

### Harmonic summary

A harmonic fit is also computed on the phase-folded residual using cosine/sine terms up to `phase_harmonic_order`.

This provides compact amplitudes and phase offsets for:

- DC component
- `1x`
- `2x`
- `3x`
- and higher orders if requested

This is useful for quantifying repeatable effects such as secondary vibration.

## Main Outputs

The notebook produces:

- an overview plot of raw, corrected, unwrapped, and wrap-count signals
- a period-estimation diagnostic
- a cycle peak-to-peak timing diagnostic
- an ideal-vs-measured displacement plot with residuals
- a phase-folded residual diagnostic
- a summary table of fit and residual metrics

## Current Assumptions and Limitations

- The unwrapping method is strict nearest-neighbour and assumes sampling is high enough to preserve local continuity.
- The correction polynomial is user-supplied; the notebook does not identify polynomial coefficients automatically.
- The ideal displacement model assumes the configured crank geometry is correct and does not include string inertial effects, compliance, or other secondary dynamics.
- Period fitting assumes a single representative period over the selected analysis window, even though the cycle timing is estimated from measured extrema.
- Residual structure that remains after fitting may reflect sensor nonlinearity, geometry mismatch, dynamic effects, or unwrap error.

## Practical Notes

- For stable results, choose an analysis window that excludes startup, shutdown, or obvious drive deceleration unless those behaviors are the subject of the analysis.
- If the coarse data-derived period is close but not exact, the extrema-based refinement should normally correct it.
- If alignment fails badly, inspect the cycle timing plot and unwrapped signal first; these usually reveal whether the problem is timing, unwrapping, or calibration.
