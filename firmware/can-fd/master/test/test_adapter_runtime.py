"""Compile the production ISR adapter functions against deterministic hardware.

Only TI peripherals/time/interrupt delivery are simulated; function bodies are
read directly from main.c so the raw MCAN and CS/DMA paths are exercised.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[4]
parser = argparse.ArgumentParser()
parser.add_argument("--cc", required=True)
args = parser.parse_args()
source = (ROOT / "firmware/can-fd/master/src/main.c").read_text()
assert "volatile MasterDrainInfo gMasterDrainInfo;" in source, "missing START-scoped drain diagnostics"
def function(name, text=source):
    import re
    match = re.search(r"static [^;{}]+\b" + name + r"\([^;{}]*\)\s*\{", text)
    assert match, name
    start = match.start()
    end = match.end()
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]
functions = "\n".join(function(n) for n in (
    "drain_clock", "drain_cost", "drain_check", "drain_transfer", "can_standard_identifier", "capture_can_receive_fifo", "take_record", "service_can_receive", "retire_measurement_slot", "service_spi_retirement", "retire_spi_boundary", "service_spi_receive"))
# Deliver a real capture IRQ just before take_record masks interrupts.
take = function("take_record")
functions = functions.replace(take, take.replace("__disable_irq();", "inject_can_arrival(queue); __disable_irq();"))
spi_receive = function("service_spi_receive")
functions = functions.replace(spi_receive, spi_receive.replace("gSpiTransmitReady=true;",
    "gSpiTransmitReady=true; injected_reply_retirement();"))
drain_types = source[source.index("/* Active drain diagnostic state. */"):source.index("/* End drain diagnostic state. */")]
# Interrupt exactly after pending publication, before the owner's next store.
common = (ROOT / "firmware/can-fd/common/protocol/bodaqs_master_service.c").read_text()
result = function("acquisition_result", common)
assert result.count("s->acquisition_retirement_pending=true;") == 1
functions += "\n" + result.replace("s->acquisition_retirement_pending=true;",
    "s->acquisition_retirement_pending=true; injected_cs_preemption();")
fixture = Path(__file__).with_name("adapter_fixture.c").read_text().replace("/* DRAIN_TYPES */", drain_types)
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / "adapter.c"
    exe = Path(temp) / "adapter.exe"
    c.write_text(fixture.replace("/* PRODUCTION_FUNCTIONS */", functions))
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
        "-I" + str(ROOT / "firmware/can-fd/common/protocol"),
        "-I" + str(ROOT / "firmware/can-fd/common/network"),
        "-I" + str(ROOT / "firmware/can-fd/common/transport"),
        "-ffunction-sections", "-Wl,--gc-sections",
        *[str(ROOT / "firmware/can-fd/common/protocol" / n) for n in ("bodaqs_master_service.c", "bodaqs_control.c", "bodaqs_control_exchange.c", "bodaqs_master_protocol.c")],
        str(c), str(ROOT / "firmware/can-fd/common/network/bodaqs_can_network.c"),
        "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
