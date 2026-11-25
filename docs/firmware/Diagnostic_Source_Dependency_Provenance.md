# Retained diagnostic dependencies

The source seed `e1c63523` retained the firmware bench CLI and host tests but
omitted five analysis files they require. These files originate verbatim
from commit `07aac3619d7416d179ca62f35a8749da7f7a58c3`, the `source_commit`
recorded by the sealed r133 `BUILD_MANIFEST.json`. No importer or assessment
behavior is changed by this restoration.

The restored first-recording test fixture subsequently gains the explicit
native-3333 profile ID/version required by the integrated multi-profile validator.
Its old all-zero profile bytes no longer constituted a valid effective
configuration. Production validation is not relaxed to satisfy the old fixture.
The table below identifies the original LF bytes before this fixture amendment.

The two package modules also match r133's `assessor-source/bodaqs_analysis/`
copies after normalizing CRLF to LF. Its `SHA256SUMS.txt` records the sealed
hashes `d0a4c873094c8225087f1acb48fda46bfc1a6bb03c60369a230688fb2d8e2575`
and `1b7ea59c722e48da76f8d240e3fd4fb2b929d80dafa04dccf987137d444b1a8f`
respectively. The sealed bundle is
`BODAQS-worktrees/adc-timer-1x1000-3333-r133`; its `SOURCE.zip` hash is
`e36bc97680b1b189ac23d49bcfe1c5f9ca6ad7faa775ec0aafbe0ed8c8f4b067`.

| Restored file | SHA-256 of committed LF bytes |
| --- | --- |
| `analysis/bodaqs_analysis/bench_evidence.py` | `6df5d59f4962303f2b0c8beea90e9ea3013a408c3bceccf05f5f960dbd123000` |
| `analysis/bodaqs_analysis/bench_snapshot.py` | `5b2406ce4f5e2f3eee3e9ad670d2b38771f9c59ec46ff5a771f3a4fcb6aa64fd` |
| `analysis/tests/test_multi_imu_recording.py` | `9928e750ea790333955f6fb83e19d1731d924dcb2de70263922ec7f61e9a6d88` |
| `analysis/tests/test_first_imu_recording.py` | `34141e783fa5b88e87ca2e40d82782cbe0d4fd9561c47af29961dea1635f2d75` |
| `analysis/tests/test_io_bdq_can_imu.py` | `d9d3c6738760aeeca7dea645f42f0c66aa10e6439764e75f7c8596dd415d909a` |

`firmware/tools/bench.py` needs the two modules. The optimization-tool test
needs the independent `multi_recording` file fixture, whose imports require
the other two restored test files. Existing canonical readers and envelope
helpers remain the dependencies for this small closure. This restores
software diagnostic checks; it does not establish physical qualification.
