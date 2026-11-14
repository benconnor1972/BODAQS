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
parser.add_argument("--v2", action="store_true")
parser.add_argument("--phase-timing", action="store_true")
parser.add_argument("--queue-timing", action="store_true")
parser.add_argument("--rx-capacity", type=int, choices=(2,4))
parser.add_argument("--boundary-trace",action="store_true")
parser.add_argument("--block-crc",action="store_true")
parser.add_argument("--can-first",action="store_true")
parser.add_argument("--bulk",action="store_true",help="Selected512 physical extent with compact128 commands")
args = parser.parse_args()
if args.bulk:
    args.v2=True
if args.rx_capacity:
    assert args.v2
source = (ROOT / "firmware/can-fd/master/src/main.c").read_text()
assert "volatile MasterDrainInfo gMasterDrainInfo" in source, "missing START-scoped drain diagnostics"
def function(name, text=source):
    import re
    match = re.search(r"^(?:static )?[\w *]+\b" + name + r"\([^;{}]*\)\s*\{", text, re.MULTILINE)
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
if args.v2:
    functions += "\n" + function("service_receive_queues")
if args.phase_timing:
    assert args.v2
    functions += "\n" + function("bodaqs_master_profile_clock")
    functions += "\n" + function("bodaqs_master_profile_record")
if args.bulk:
    window=(ROOT/'firmware/can-fd/common/protocol/bodaqs_master_window.h').read_text()
    functions=function('window_clear_node',window)+'\n'+functions
if args.queue_timing:
    assert args.v2 and args.phase_timing
    functions += "\n" + function("drain_queue_sample")
    functions += "\n" + function("drain_queue_record")
    functions = "static void drain_queue_sample(void);\nstatic void drain_queue_record(const uint8_t *,size_t,SpiReceiveTiming,uint32_t,uint32_t,uint16_t,bool);\n" + functions
# Deliver a real capture IRQ just before take_record masks interrupts.
take = function("take_record")
functions = functions.replace(take, take.replace("__disable_irq();", "inject_can_arrival(queue); __disable_irq();"))
spi_receive = function("service_spi_receive")
functions = functions.replace(spi_receive, spi_receive.replace("gSpiTransmitReady=true;",
    "gSpiTransmitReady=true; injected_reply_retirement();"))
if args.queue_timing:
    functions = functions.replace("primask=__get_PRIMASK();\n    __disable_irq();\n    length=gSpiReceiveLengths",
        "primask=__get_PRIMASK();\n    inject_spi_arrival(false);\n    __disable_irq();\n    length=gSpiReceiveLengths")
    sample = function("drain_queue_sample")
    functions = functions.replace(sample, sample.replace("__disable_irq();", "inject_spi_arrival(true); __disable_irq();"))
drain_types = source[source.index("/* Active drain diagnostic state. */"):source.index("/* End drain diagnostic state. */")]
# Interrupt exactly after pending publication, before the owner's next store.
common = (ROOT / "firmware/can-fd/common/protocol/bodaqs_master_service.c").read_text()
result = function("acquisition_result", common)
assert result.count("s->acquisition_retirement_pending=true;") == 1
functions += "\n" + result.replace("s->acquisition_retirement_pending=true;",
    "s->acquisition_retirement_pending=true; injected_cs_preemption();")
fixture = Path(__file__).with_name("adapter_fixture.c").read_text().replace("/* DRAIN_TYPES */", drain_types)
constants=source[source.index('#define CAN_RX_SERVICE_BUDGET'):source.index('typedef struct {',source.index('#define CAN_RX_SERVICE_BUDGET'))]
fixture=fixture.replace('#define CAN_RX_CAPACITY 8U\n#define CAN_RX_SERVICE_BUDGET 8U',constants)
owned=source[source.index("/* SPI adapter ownership storage. */"):source.index("/* End SPI adapter ownership storage. */")]
if args.boundary_trace:
    assert args.v2
    # Same functions, declared after SDK stand-ins rather than before them.
    helpers="\n".join(function(n) for n in ("spi_trace_hardware","spi_trace_barrier","spi_trace_cost","spi_trace_arm"))
    for name in ("spi_trace_hardware","spi_trace_barrier","spi_trace_cost","spi_trace_arm"):
        owned=owned.replace(function(name),"")
    functions=helpers+"\n"+functions
fixture=fixture.replace("/* SPI_ADAPTER_STORAGE */",owned)
if args.v2:
    assert "/* SPI adapter ownership storage. */" in source, "v2 DMA storage must match production"
    fixture=fixture[:fixture.index("int main(void) {")]+Path(__file__).with_name("adapter_v2_cases.c").read_text()
    fixture=fixture.replace("/* RX_RETRY_CASES */",'' if args.bulk else Path(__file__).with_name("adapter_v2_retry_cases.c").read_text())
if args.queue_timing:
    fixture=fixture.replace("/* QUEUE_TIMING_CASES */",Path(__file__).with_name("adapter_queue_cases.c").read_text())
if args.v2:
    # Observe the real receive-turn's ordering at SPI dispatch. CAN decoding is
    # already a peripheral stand-in; bounded queue pops and SPI dispatch are real.
    fixture=fixture.replace("static void update_service_status(void) {test_tick+=3;}",
        "static unsigned can_seen_at_spi, processed_can;\nstatic void update_service_status(void) {can_seen_at_spi=processed_can;test_tick+=3;}")
    pos=fixture.rfind("\n}")
    fixture=fixture[:pos]+Path(__file__).with_name("adapter_receive_order_cases.c").read_text()+fixture[pos:]
if args.boundary_trace:
    pos=fixture.rfind("\n}")
    assert pos>0
    fixture=fixture[:pos]+Path(__file__).with_name("adapter_trace_cases.c").read_text()+fixture[pos:]
if args.bulk:
    assert not args.boundary_trace and not args.queue_timing
    # Keep the production CS, DMA, copy and publication code untouched. Only
    # parameterize the existing physical input/output vectors and command oracle.
    fixture=fixture.replace('256','BODAQS_MEASUREMENT_BYTES').replace('[255]','[BODAQS_MEASUREMENT_BYTES-1]')
    # Window profiles classify all evidence as essential, unlike v2.
    fixture=fixture.replace('assert(!gRejectedCan[0].essential);','assert(gRejectedCan[0].essential);')
    fixture=fixture.replace('{84,BODAQS_MEASUREMENT_BYTES,255,BODAQS_MEASUREMENT_BYTES}',
        '{84,BODAQS_MEASUREMENT_BYTES,BODAQS_MEASUREMENT_BYTES-1,BODAQS_MEASUREMENT_BYTES}')
    for command in ('idle','order_idle'):
        fixture=fixture.replace('bodaqs_measurement_encode(&'+command+',','bodaqs_measurement_encode_request(&'+command+',')
    fixture=fixture.replace('/* PRODUCTION_FUNCTIONS */','static uint32_t gDrainSampleSeen[4][4];\nstatic BodaqsMasterWindowStorage gWindow;\n/* PRODUCTION_FUNCTIONS */')
    fixture=fixture.replace('remaining=0;retire_spi_boundary();gSpiTransmitReady=false;\n    service_spi_receive();assert(gSpiTransmitReady',
        'memset(gReceiveSlots[gReceiveIndex]+128,0xa7,BODAQS_MEASUREMENT_BYTES-128);\n    remaining=0;retire_spi_boundary();gSpiTransmitReady=false;\n    service_spi_receive();assert(gSpiTransmitReady',1)
with tempfile.TemporaryDirectory() as temp:
    c = Path(temp) / "adapter.c"
    exe = Path(temp) / "adapter.exe"
    c.write_text(fixture.replace("/* PRODUCTION_FUNCTIONS */", functions))
    flags=["-DBODAQS_SPI_MEASUREMENT_V2=1", "-Wno-unused-function", "-Wno-unused-variable"] if args.v2 else []
    if args.phase_timing:
        flags.append("-DBODAQS_MASTER_PHASE_TIMING=1")
    if args.bulk:
        flags += ['-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512']
    if args.queue_timing:
        flags.append("-DBODAQS_MASTER_QUEUE_TIMING=1")
    if args.rx_capacity:
        flags.append(f"-DBODAQS_MASTER_SPI_RX_CAPACITY={args.rx_capacity}")
    if args.boundary_trace:flags.append("-DBODAQS_SPI_BOUNDARY_TRACE=1")
    flags.extend([f"-DBODAQS_MASTER_BLOCK_CRC={int(args.block_crc)}",
                  f"-DBODAQS_MASTER_CAN_FIRST={int(args.can_first)}"])
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",*flags,
        "-I" + str(ROOT / "firmware/can-fd/common/protocol"),
        "-I" + str(ROOT / "firmware/can-fd/common/network"),
        "-I" + str(ROOT / "firmware/can-fd/common/transport"),
        "-ffunction-sections", "-Wl,--gc-sections",
        *[str(ROOT / "firmware/can-fd/common/protocol" / n) for n in ("bodaqs_master_service.c", "bodaqs_control.c", "bodaqs_control_exchange.c", "bodaqs_master_protocol.c")],
        str(c), str(ROOT / "firmware/can-fd/common/network/bodaqs_can_network.c"),
        "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
