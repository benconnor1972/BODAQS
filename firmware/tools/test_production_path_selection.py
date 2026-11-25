"""Validate resolved release flags and operational features without devices."""
import argparse
import configparser
from pathlib import Path
import re
import subprocess
import tempfile


def flags_for(config, environment):
    def expand(text):
        return re.sub(r"\$\{([^}]+)\}", lambda match: expand(config.get(*match[1].rsplit(".", 1))), text)
    def inherited(section, key):
        if key in config[section]:
            return expand(config[section][key])
        parent = config[section].get("extends")
        return inherited(parent, key) if parent else ""
    section = "env:" + environment
    removed = inherited(section, "build_unflags").split()
    return [flag for flag in inherited(section, "build_flags").split() if flag not in removed]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = configparser.ConfigParser(interpolation=None)
    config.read(root / "platformio.ini")
    expected = {"BODAQS_SPI_BULK_BYTES": "512", "BODAQS_MEASUREMENT_START_SPACING_US": "1200",
                "BODAQS_MEASUREMENT_CS_SETUP_US": "5", "BODAQS_ORDINARY_FETCH_INTERVAL_MS": "20",
                "BODAQS_ACQ_HEALTH_INTERVAL_MS": "4000", "BODAQS_ADC_TASK_PRIORITY": "4",
                "BODAQS_STORAGE_TASK_PRIORITY": "2", "BODAQS_ADC_SCAN_SPI_HZ": "2000000",
                "BODAQS_LOGGER_SAMPLE_QUEUE_CAPACITY": "512"}
    fixture = r'''
#include "RecordingFeatures.h"
#include "AdcConcentratedScan.h"
#include "RawAdcRecording.h"
#include "BacklogBalance.h"
#include "../can-fd/common/protocol/bodaqs_measurement.h"
#include <cassert>
#if BODAQS_PRODUCTION_RECORDING
static_assert(BODAQS_MEASUREMENT_VERSION==5 && BODAQS_MEASUREMENT_BYTES==512);
static_assert(BODAQS_SCANNED_ADC_ACQUISITION && BODAQS_VARIABLE_ADC_SCAN && BODAQS_MULTI_ADC_SCAN);
static_assert(BODAQS_RAW_COUNT_RECORDING && BODAQS_ADAPTIVE_DRAIN_OWNER);
static_assert(!AdcConcentratedScan::usesTickCadence(1000,1));
static_assert(RawAdcRecording::kColumns==LocalAnalogRecordingPlan::kMaximumColumns);
#endif
int main() {
  BacklogBalance::Policy policy;
  auto d=policy.decide(true,{0,0,0,true,true});
  assert(d.priority==3 && d.calls==8 && d.budgetUs==6000 && d.sleepTicks==1);
  d=policy.decide(true,{125,0,0,true,true});
  assert(d.priority==2 && d.calls==1 && d.budgetUs==0 && d.sleepTicks==1);
  d=policy.decide(true,{62,125,125,true,true});assert(d.priority==3);
}
'''
    with tempfile.TemporaryDirectory(prefix="bodaqs-path-selection-") as temporary:
        cpp, exe = Path(temporary)/"path.cpp", Path(temporary)/"path.exe"
        cpp.write_text(fixture)
        for environment in ("bodaqs_a8_production", "bodaqs_a8_integration_candidate",
                            "bodaqs_a8_production_usb", "bodaqs_a8_integration_candidate_usb",
                            "bodaqs_s3_mini_n4r2_imu_adc_raw"):
            flags = flags_for(config, environment)
            macros = dict(flag[2:].split("=", 1) for flag in flags if flag.startswith("-DBODAQS_") and "=" in flag)
            if environment.endswith('_usb'):
                original=set(flags_for(config, environment[:-4]))
                assert set(flags)-original=={'-DARDUINO_USB_MODE=0','-DBODAQS_A8_USB_DRIVE=1'}
                assert not original-set(flags)
            if "production" in environment or "integration_candidate" in environment:
                assert all(macros.get(name)==value for name,value in expected.items()), macros
                assert not any(("BENCH" in name or "SMOKE" in name) and value!="0" for name,value in macros.items())
                assert [flag for flag in flags if "--wrap" in flag]==["-Wl,--wrap=sdmmc_write_sectors"]
                assert "-fstack-usage" not in flags
                assert macros.get("BODAQS_UNQUALIFIED_INTEGRATION_CANDIDATE", "0")==str(int("candidate" in environment))
                for name in ("BODAQS_CPU_OCCUPANCY", "BODAQS_SPARSE_COST_PROBE", "BODAQS_STORAGE_PATH_PROBE",
                             "BODAQS_IMU_FLOW_DIAGNOSTICS", "BODAQS_RECORDING_PRESSURE_DIAGNOSTICS", "BODAQS_STORAGE_TIMELINE",
                             "BODAQS_CONTROL_POLL_DIAGNOSTICS", "BODAQS_ACQUISITION_PROFILE", "BODAQS_TRANSPORT_PROFILE"):
                    assert macros.get(name,"0")=="0", name
            definitions = [flag for flag in flags if flag.startswith("-DBODAQS_") and "FW_" not in flag]
            subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror",*definitions,
                            "-I",str(root/"src"),str(cpp),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
            print(environment + ": resolved flags, selected custody/ADC/drain policy PASS")


if __name__ == "__main__":
    main()
