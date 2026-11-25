"""Exact debugger snapshots. uint64 values are strings, never JSON doubles."""
from __future__ import annotations
import re

BASE = dict.fromkeys(("version state finish_reason started_tick elapsed_us clock_epoch timing_invalid nodes_seen "
    "spi_dropped_base can_dropped_base can_hardware_base retained_base spi_dropped can_dropped "
    "can_hardware_losses retained_frames empty_replies malformed_slots can_queue_sampled_high_water").split(), ())
BASE.update({k: (5,) for k in ("polls", "acks", "fragments")})
BASE.update({k: (4,) for k in ("ingress_dropped_base", "ingress_dropped", "ingress_depth", "ingress_sampled_high_water")})
BASE.update({k: (3,) for k in ("calls", "max_us", "total_us")})
BASE["histogram"]=(3,5)
BASE.update({k:(2,) for k in ("data_objects data_records data_unique_fragments data_repeat_fragments "
    "data_acked_objects data_acked_records data_head_polls data_empty_polls").split()})
BASE.update(data_batch_records=(2,14),data_last_object=(2,4),data_fragment_mask=(2,4),context=(),recording=())
PHASE={"phase_calls":(4,),"phase_max_us":(4,3),"phase_total_us":(4,3)}
QUEUE=dict.fromkeys(("spi_queue_wait_count spi_queue_wait_excluded spi_queue_time_invalid spi_queue_wait_max_us "
    "spi_queue_depth spi_queue_peak spi_queue_head_age_us spi_queue_head_valid spi_queue_wait_total_us").split(),())
QUEUE.update(spi_queue_wait_hist=(6,),spi_queue_depth_hist=(5,))
V5={"ack_fetches":(5,),"ack_fetch_targets":(5,),"layout_flags":(),"size_bytes":()}
U64={"context","recording","total_us","phase_total_us","spi_queue_wait_total_us"}
RUNTIME=dict.fromkeys(("reset_cause can_link_profile uptime_ms slots_received probes_received status_requests_received "
    "inventory_requests_received malformed_slots spi_recoveries bad_magic_slots unsupported_version_slots invalid_length_slots "
    "bad_crc_slots invalid_argument_slots last_decode_result cs_release_timeouts spi_rx_dropped spi_rx_capacity spi_rx_high_water "
    "buck_gpio_doe31_0 buck_gpio_dout31_0 buck_gpio_din31_0 can_rx_frames can_rx_dropped can_rx_hardware_losses "
    "can_rx_capacity can_rx_pending can_rx_pending_high_water can_tx_frames can_error_events can_bus_off_recovery_attempts "
    "can_bus_off_recoveries can_last_interrupts can_malformed_frames can_unsupported_version_frames can_unknown_frames "
    "can_address_mismatches discovery_requests_sent discovery_enqueue_failures last_can_decode_result can_rx_queue_depth "
    "can_rx_queue_high_water nodes_present nodes_stale nodes_duplicate can_initialized can_bus_off clock_fault "
    "buck_build_enabled buck_output_enabled buck_output_latch_high buck_pin_high buck_driverlib_read_high front_power_fault rear_power_fault").split(),())
RUNTIME.update({k:(4,) for k in ("ingress_capacity","ingress_depth","ingress_high_water","ingress_dropped")})


def exact64(value) -> int:
    if not isinstance(value,str) or not re.fullmatch(r"(?:0x[0-9a-fA-F]{1,16}|[0-9]{1,20})",value):
        raise ValueError("uint64 requires an exact decimal/hex string (rounded debugger numbers are uncertain)")
    number=int(value,16 if value.startswith("0x") else 10)
    if number>=1<<64: raise ValueError("uint64 overflow")
    return number


def fields(version:int, phase:bool, queue:bool) -> dict:
    if version not in (2,3,4,5): raise ValueError("Unsupported drain version")
    if version<5 and (phase!=(version>=3) or queue!=(version>=4)):
        raise ValueError("Legacy layout flags conflict with version")
    return {**BASE,**(PHASE if phase else {}),**(QUEUE if queue else {}),**(V5 if version==5 else {})}


def validate(snapshot:dict) -> dict:
    if snapshot.get("schema")!="bodaqs.master-snapshot.v1": raise ValueError("Unsupported snapshot schema")
    if snapshot.get("scope") not in ("first_loss","stop_admitted","identity_change"):
        raise ValueError("Snapshot freeze scope missing")
    exact64(snapshot.get("master_boot"))
    layout=snapshot["layout"]
    if type(layout.get("phase_timing")) is not bool or type(layout.get("queue_timing")) is not bool:
        raise ValueError("Timing layout must be explicit")
    drain=snapshot["drain"]
    expected=fields(drain["version"],layout["phase_timing"],layout["queue_timing"])
    def check(value,shape,wide=False):
        if shape:
            if not isinstance(value,list) or len(value)!=shape[0]: raise ValueError("Incomplete snapshot array")
            for entry in value:check(entry,shape[1:],wide)
        elif wide:exact64(value)
        elif type(value) is not int or not 0<=value<1<<32:raise ValueError("Expected uint32")
    for container,schema in ((drain,expected),(snapshot["runtime"],RUNTIME)):
        if set(container)!=set(schema): raise ValueError("Snapshot fields missing or unsupported")
        for key,shape in schema.items():check(container[key],shape,container is drain and key in U64)
    if drain["state"]!=2 or drain["finish_reason"]!={"first_loss":1,"stop_admitted":2,"identity_change":3}[snapshot["scope"]]:
        raise ValueError("Snapshot is not frozen at declared boundary")
    if drain["version"]==5:
        if drain["layout_flags"]!=int(layout["phase_timing"])+2*int(layout["queue_timing"]) or drain["size_bytes"]<=0:
            raise ValueError("Snapshot layout identity mismatch")
    return snapshot


def ccs_script(version=5,phase=True,queue=True) -> str:
    """Call exportBodaqsSnapshot(existingDebugSession, exactBootString) while halted.

    Does not connect, halt, resume, write memory or flash. TI's shipped DSS examples
    use session.expression.evaluate; every evaluated integer here fits 32 bits.
    """
    import json
    schema={"drain":fields(version,phase,queue),"runtime":RUNTIME}
    return '''// Load into an existing, operator-selected halted CCS DSS session.
function exportBodaqsSnapshot(session, masterBoot, operatorConfirmedHalted) {
 if(operatorConfirmedHalted !== true || typeof masterBoot !== 'string') throw 'Confirm halted session and exact boot string';
 var schema=SCHEMA, wide=WIDE;
 function scalar(expression,isWide) {
   function part(e) {var n=Number(session.expression.evaluate(e)); if(n<0)n+=4294967296;return n;}
   if(!isWide)return part('(unsigned long)('+expression+')');
   var hi=part('(unsigned long)(('+expression+') >> 32)'),lo=part('(unsigned long)('+expression+')');
   return '0x'+('00000000'+hi.toString(16)).slice(-8)+('00000000'+lo.toString(16)).slice(-8);
 }
 function read(expression,shape,isWide) {
   if(!shape.length)return scalar(expression,isWide);
   var rows=[];for(var i=0;i<shape[0];i++)rows.push(read(expression+'['+i+']',shape.slice(1),isWide));return rows;
 }
 var result={schema:'bodaqs.master-snapshot.v1',master_boot:masterBoot,layout:LAYOUT};
 for(var section in schema){result[section]={};for(var key in schema[section])
   result[section][key]=read((section==='drain'?'gMasterDrainInfo.':'gMasterRuntimeInfo.')+key,schema[section][key],section==='drain'&&wide.indexOf(key)>=0);}
 if(result.drain.version!==VERSION || result.drain.state!==2)throw 'Wrong layout or unfrozen snapshot';
 result.scope={1:'first_loss',2:'stop_admitted',3:'identity_change'}[result.drain.finish_reason];
 return JSON.stringify(result,null,2);
}
'''.replace('SCHEMA',json.dumps(schema)).replace('WIDE',json.dumps(sorted(U64))).replace('LAYOUT',json.dumps(
        {"phase_timing":phase,"queue_timing":queue})).replace('VERSION',str(version))
