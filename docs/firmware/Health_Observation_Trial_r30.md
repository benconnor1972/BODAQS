# r30: ordinary-control headroom trial

Starting from r29, change only optional global health-observation cadence from
2000 to 4000 ms. The selected environment is
`bodaqs_s3_mini_n4r2_imu_health4000`; existing environments retain 2000 ms.
Both initial delay and subsequent intervals use `BODAQS_ACQ_HEALTH_INTERVAL_MS`.

Each snapshot uses eight ordinary CAN requests. Nominal demand falls from 4 to
2 requests/s against the retained master's 4 requests/s allowance. Four healthy
nodes are observed approximately every 16 seconds rather than 8 seconds, plus
completion delays. This is a causal experiment, not a qualified new default.

Retain r29's control/heap and storage timelines, 20 ms pending-result polling,
512-entry logger sample queues, four-node ADC-off configuration, P3 storage,
512-byte/16 MHz SPI with 1200 us spacing, and the exact installed r27 master.
Protected lease renewals, STOP, custody, CRC/identity validation, retirement,
master ingress and loss-report cadence do not change. No ownership, allocation,
protocol, file-format or identifier-capacity boundary changes are introduced.

Record 6–7 minutes after START, then normal STOP/file closure and the existing
300–330 s late master snapshot. Compare the whole-run ordinary request age and
pending-due fetch trend, quiet-bin sample admissions, exact sample delivery and
all four source terminal boundaries against r29. Improvement with a bounded
polling trend supports the ordinary-control congestion hypothesis; absence of
improvement calls for direct token-wait/dispatch instrumentation. Do not combine
this test with slower result polling, a larger master allowance or config changes.

Host integration under the selected interval checks recording integrity and
lifecycle regressions, not real throughput or token-wait causation. Physical
validation remains the purpose of the trial.
