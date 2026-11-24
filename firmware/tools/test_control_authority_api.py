"""Exercise production CAN authority JSON with real ArduinoJson and portable state."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    json_include = root / ".pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src"
    if not (json_include / "ArduinoJson.h").exists():
        parser.error("Install A8 dependencies first: pio pkg install -d firmware -e bodaqs_s3_mini_n4r2")
    source = (root / "src/Routes_Api.cpp").read_text(encoding="utf-8")
    fixture = r'''#include <ArduinoJson.h>
#include <cassert>
#include <cstdio>
#include <cstring>
#include "bodaqs_control_observer.h"
#include "bodaqs_control_authority_client.h"
// API_FUNCTION
int main() {
    JsonDocument document;
    BodaqsControlObservation observation = {};
    BodaqsControlAuthorityPeer authority = {};
    observation.available = true; observation.valid = true; observation.node_boot_id = 55; authority.boot = 55;
    observation.active_session = 18446744073709551615ULL;
    observation.observed_ms = 100;
    authority.bound = true; authority.confirmed_ms = 90;
    auto node = document.to<JsonObject>();
    addControlAuthorityJson_(node, observation, authority, 18446744073709551615ULL);
    assert(!strcmp(node["logger_session_id"].as<const char*>(), "18446744073709551615"));
    assert(node["authority_bound"].as<bool>() && node["authority_observed_current"].as<bool>());
    assert(!node["configuration_reconciled"].as<bool>());
    // A prior-session observation must never grant current authority.
    observation.active_session = 10;
    addControlAuthorityJson_(node, observation, authority, 18446744073709551615ULL);
    assert(!node["authority_observed_current"].as<bool>());
    observation.active_session = 18446744073709551615ULL;
    observation.observed_ms = 80;
    addControlAuthorityJson_(node, observation, authority, 18446744073709551615ULL);
    assert(!node["authority_observed_current"].as<bool>());
    // Reset invalidation and explicit release both clear live authority.
    observation.available = false; authority.bound = false; authority.reason = 5;
    addControlAuthorityJson_(node, observation, authority, 18446744073709551615ULL);
    assert(!node["authority_bound"].as<bool>() && !node["authority_observed_current"].as<bool>());
    assert(!strcmp(node["authority_reason_key"].as<const char*>(), "stale_control_session"));
    puts("production authority API projection passed");
}
'''
    fixture = fixture.replace("// API_FUNCTION", definition(source, "static void addControlAuthorityJson_("))
    with tempfile.TemporaryDirectory(prefix="bodaqs-control-api-") as temp:
        cpp, exe = Path(temp) / "runtime.cpp", Path(temp) / "runtime.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(json_include), "-I", str(root / "can-fd/common/protocol"), str(cpp), str(root / "can-fd/common/protocol/bodaqs_control.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
