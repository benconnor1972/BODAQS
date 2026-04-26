<script lang="ts">
  import { preprocessCsv, type PreprocessConfig } from '$lib/api/preprocess';
  import { storePreprocessResult } from '$lib/db/artifacts';
  import { libraryStore } from '$lib/stores/library.svelte';
  import { makeRunId } from '$lib/utils/run-id';

  type FileStatus = 'pending' | 'duplicate' | 'uploading' | 'done' | 'error';
  interface FileEntry {
    file: File;
    status: FileStatus;
    sha?: string;
    error?: string;
  }

  let files: FileEntry[] = $state([]);
  let runId = $state(makeRunId());
  let schemaYaml = $state(`specification: 0.1.1
version: '5'
naming:
  suffixes:
    disp: ' [mm]'
    vel: ' _vel [mm/s]'
    acc: ' _acc [mm/s^2]'
defaults:
  window:
    pre_s: 2.0
    post_s: 1.0
    align: trigger
  debounce:
    gap_s: 0.2
    prefer_key: t0_index
    prefer_abs: false
    prefer_max: false
series:
- id: mark
  kind: trigger
  source: system:mark
  column: mark
  edge: rising
events:
- id: rebounds_75_100
  label: rebound events with max normalized displacement >0.75
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    any_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>='
      value: 0.75
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: &id001
          quantity: disp
          unit: mm
          op_chain: []
      - role: vel
        prefer: &id002
          quantity: vel
          unit: mm/s
          op_chain: []
      - role: acc
        prefer: &id003
          quantity: acc
          unit: mm/s^2
          op_chain: []
      - role: disp_norm
        prefer: &id004
          quantity: disp_norm
          unit: "1"
          op_chain: [norm]
- id: rebounds_50_75
  label: rebound events with max normalized displacement >0.5 and <=0.75
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.5
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.75
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: rebounds_25_50
  label: rebound events with max normalized displacement >0.25 and <=0.5
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.25
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.5
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: rebounds_0_25
  label: rebound events with max normalized displacement <=0.25
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:

    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.25
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: rebounds_all>25
  label: rebound events with max normalized displacement >0.25
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.25
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: rebounds_all
  label: all rebound events
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_start
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: forward
    dir: rising
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  window:
    pre_s: 0.2
    post_s: 0.8
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_start
      end_trigger: rebound_end
      ops:
      - mean
      - max
      - min
      polarity: neg_to_pos
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.2
      post_s: 0.8
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_0_25
  label: compression events with max normalized displacement <=0.25
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.25
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_25_50
  label: compression events with max normalized displacement >0.25 and <=0.5
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.25
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.5
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_50_75
  label: compression events with max normalized displacement >0.50 and <=0.75
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.5
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '<='
      value: 0.75
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_75_100
  label: compression events with max normalized displacement >0.75
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.75
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_all>25
  label: all compression events >25% normalised displacement
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.25
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: compressions_all
  label: all compression events
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: bottom_out
  label: compression events with max normalized displacement >0.98
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: compression_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: falling
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.3
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: compression_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: compression_end
    search:
      min_delay_s: 0.05
      max_delay_s: 0.8
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: false
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: max
      cmp: '>'
      value: 0.98
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: compression_start
      end_trigger: compression_end
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - compression
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: top_out
  label: rebound events with min normalized displacement <= 0.02
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_end
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    dir: rising
    hysteresis: 0
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.1
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_end
    search:
      min_delay_s: -0.8
      max_delay_s: -0.05
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: true
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: min
      cmp: '<='
      value: 0.02
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_end
      end_trigger: rebound_start
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
- id: top_out2
  label: rebound events with min normalized displacement <= 0.02
  sensors:
    - rear_shock
    - front_shock
  trigger:
    id: rebound_end
    type: local_extrema
    signal: disp
    kind: min
    prominence: 0.1
    distance_s: 0.015
    edge_ignore_s: 1
    debounce:
      gap_s: 0.1
      prefer_key: disp
      prefer_abs: false
      prefer_max: true
  secondary_triggers:
  - id: rebound_start
    type: simple_threshold_crossing
    signal: vel
    value: 0.0
    base_trigger: rebound_end
    search:
      min_delay_s: -0.8
      max_delay_s: -0.05
      direction: backward
    dir: falling
    debounce:
      gap_s: 0.8
      prefer_key: t0_index
      prefer_abs: false
      prefer_max: true
  preconditions:
  - within_s:
    - -0.01
    - 0.01
    all_of:
    - type: peak
      signal: disp_norm
      kind: min
      cmp: '<='
      value: 0.02
  window:
    pre_s: 0.8
    post_s: 0.2
    align: trigger
  metrics:
    - type: interval_stats
      signal: vel
      start_trigger: rebound_end
      end_trigger: rebound_start
      ops:
      - mean
      - max
      - min
      polarity: pos_to_neg
      smooth_ms: 20
      min_delay_s: 0.02
      return_debug: true
    - type: peak
      signal: disp
      kind: max
    - type: peak
      signal: disp
      kind: min
    - type: peak
      signal: acc
      kind: max
    - type: peak
      signal: acc
      kind: min
  tags:
    - kinematics
    - rebound
  segment_defaults:
    anchor: trigger_time_s
    window:
      pre_s: 0.8
      post_s: 0.2
    roles:
      - role: disp
        prefer: *id001
      - role: vel
        prefer: *id002
      - role: acc
        prefer: *id003
      - role: disp_norm
        prefer: *id004
`);
  let normalizeRangesRaw = $state('{"front_shock_dom_suspension [mm]": 170, "rear_shock_dom_suspension [mm]": 150}');
  let zeroingEnabled = $state(false);
  let running = $state(false);

  async function hashFile(file: File): Promise<string> {
    const buf = await file.arrayBuffer();
    const hashBuf = await crypto.subtle.digest('SHA-256', buf);
    return Array.from(new Uint8Array(hashBuf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }

  async function onFilePick(e: Event) {
    const input = e.target as HTMLInputElement;
    const picked = Array.from(input.files ?? []);
    files = await Promise.all(
      picked.map(async (f) => {
        const sha = await hashFile(f);
        const isDup = libraryStore.runs.some((r) => r.sha_set.includes(sha));
        const status: FileStatus = isDup ? 'duplicate' : 'pending';
        return { file: f, status, sha };
      })
    );
  }

  async function processAll() {
    let normalizeRanges: Record<string, number>;
    try {
      normalizeRanges = JSON.parse(normalizeRangesRaw);
    } catch {
      alert('Normalize ranges is not valid JSON');
      return;
    }
    if (!schemaYaml.trim()) {
      alert('Paste the event schema YAML before processing');
      return;
    }

    const config: PreprocessConfig = {
      schema_yaml: schemaYaml,
      normalize_ranges: normalizeRanges,
      zeroing_enabled: zeroingEnabled,
      strict: false,
    };

    running = true;
    for (const entry of files) {
      if (entry.status === 'duplicate') continue;
      entry.status = 'uploading';
      try {
        console.log(`Preprocessing ${entry.file.name}…`);
        const result = await preprocessCsv(entry.file, config);
        console.log(`Preprocessed ${entry.file.name}…`);

        await storePreprocessResult(runId, result);
        libraryStore.addSessionToRun(runId, result.session_id, result.source_sha256);
        entry.status = 'done';
      } catch (err) {
        entry.status = 'error';
        entry.error = String(err);
      }
    }
    running = false;
  }

  const statusLabel: Record<FileStatus, string> = {
    pending: 'Pending',
    duplicate: 'Already processed',
    uploading: 'Processing…',
    done: 'Done',
    error: 'Error',
  };
</script>

<h1>Preprocess CSV Files</h1>

<div>
  <label>
    <span>Event Schema YAML</span>
    <textarea bind:value={schemaYaml} rows="8" placeholder="Paste event_schema.yaml contents here…"></textarea>
  </label>
</div>

<div>
  <label>
    <span>Normalize ranges (JSON)</span>
    <textarea bind:value={normalizeRangesRaw}></textarea>
  </label>
</div>

<div>
  <label>
    <input type="checkbox" bind:checked={zeroingEnabled} />
    Zeroing enabled
  </label>
</div>

<hr />
<form>
<input type="file" accept=".CSV,.csv" multiple onchange={onFilePick} />
</form>

{#if files.length > 0}
  <table>
    <thead>
      <tr>
        <th>File</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {#each files as entry(entry.sha)}
        <tr>
          <td>{entry.file.name}</td>
          <td>
            {statusLabel[entry.status]}
            {#if entry.error} — {entry.error}{/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <button onclick={processAll} disabled={running}>
    {running ? 'Processing…' : `Process ${files.filter((f) => f.status === 'pending').length} file(s)`}
  </button>
{/if}
