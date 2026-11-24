"""Interpret bounded logger request/reply observations without inventing causality."""
import argparse
from collections import Counter
import json
from pathlib import Path

CLASSES={2:1,3:2,4:3,12:4,13:5}
COLUMNS=["slot","start_us","duration_us","target_object","response_object","ack_object","available",
    "target_mask","requested_after_selection","request_kind","target_class","target_node","target_index",
    "response_kind","response_node","response_index","flags","ack_class","ack_node","response_mask_before","physical_sequence_valid"]

def analyze(text):
    records=[]
    errors=[]
    for number,line in enumerate(text.splitlines(),1):
        marker=line.find("[PIPE]")
        if marker<0:
            continue
        try:
            record=json.loads(line[marker+6:].strip())
            if not isinstance(record,dict):
                errors.append("nonobject_line_"+str(number))
                continue
            records.append(record)
        except ValueError:
            errors.append("invalid_json_line_"+str(number))
    summaries=[r for r in records if r.get("type")=="summary"]
    ends=[r for r in records if r.get("type")=="end"]
    headers=[r for r in records if r.get("type")=="window"]
    if len(summaries)!=1 or len(ends)!=1 or len(headers)!=2 or sorted(r.get("window") for r in headers)!=[0,1]:
        return dict(complete=False,errors=errors+["missing_or_multiple_trace_sections"],windows=[])
    summary=summaries[0]
    if records[0].get("type")!="summary" or records[-1].get("type")!="end":
        errors.append("invalid_trace_order")
    if summary.get("schema")!="bodaqs.spi-pipeline.v1" or not isinstance(summary.get("context"),str):
        errors.append("invalid_trace_identity")
    windows=[]
    for header in sorted(headers,key=lambda r:r["window"]):
        if header.get("columns")!=COLUMNS:
            errors.append("unknown_columns")
            continue
        raw=[r for r in records if r.get("type")=="frame" and r.get("window")==header["window"]]
        if len(raw)!=header["count"] or not 0<=len(raw)<=128:
            errors.append("frame_count_mismatch")
        rows=[]
        for item in raw:
            if len(item["v"])!=len(header["columns"]) or any(type(v) is not int or not 0<=v<=0xffffffff for v in item["v"]):
                errors.append("invalid_frame_geometry")
                continue
            rows.append(dict(zip(header["columns"],item["v"])))
        physical=[r for r in rows if r["physical_sequence_valid"]]
        if any(b["slot"]<=a["slot"] for a,b in zip(physical,physical[1:])):
            errors.append("nonmonotonic_physical_slots")
        omitted=sum(b["slot"]-a["slot"]-1 for a,b in zip(physical,physical[1:]) if b["slot"]>a["slot"])
        counts=Counter()
        candidates=[]
        for i,row in enumerate(rows):
            counts["requests"]+=1
            if not row["flags"]&1:
                counts["invalid_replies"]+=1
                continue
            if row["flags"]&64:
                counts["context_mismatch"]+=1
                continue
            if not row["response_kind"]:
                counts["empty"]+=1
                if row["available"]:
                    counts["empty_with_stale_backlog_hint"]+=1
            if row["flags"]&128:
                counts["idle_control_targets"]+=1
            if row["flags"]&2:
                counts["known_fragment_replies"]+=1
            cls=CLASSES.get(row["response_kind"],0)
            if not cls:
                continue
            # MISO was preloaded: this slot's MOSI is never its causal request.
            # Repeated identical earlier requests remain multiple candidates.
            prior=[q for q in rows[:i] if row["physical_sequence_valid"] and q["physical_sequence_valid"] and q["target_class"]==cls and
                q["target_node"]==row["response_node"] and
                q["target_index"]==row["response_index"] and
                (q["target_object"]==row["response_object"] or
                 q["target_object"]==0 and row["response_index"]==0)]
            if prior:
                candidates.append(dict(reply_slot=row["slot"],candidate_slots=[q["slot"] for q in prior],
                    minimum_slot_distance=row["slot"]-prior[-1]["slot"],
                    maximum_slot_distance=row["slot"]-prior[0]["slot"]))
            else:
                counts["data_without_prior_matching_request_in_window"]+=1
        windows.append(dict(window=header["window"],freeze_reason=header["reason"],
            overwritten=header["overwritten"],unobserved_physical_slots_between_valid_rows=omitted,
            physical_identity_unknown_rows=len(rows)-len(physical),counts=dict(counts),
            request_targets=dict(Counter(str((r["target_class"],r["target_node"])) for r in rows)),
            reply_correlation_candidates=candidates,
            limits="Distances use actual master-CS physical sequence. Matches identify only recorded earlier candidates, not a causal assignment or complete age bound; recovery/inspection gaps and overwritten prefix remain unknown. Empty replies have no causal class identity. Hints are stale. No recoverable-capacity percentage is inferred."))
    return dict(schema="bodaqs.spi_pipeline_analysis.v1",complete=not errors,errors=errors,
        summary=summary,windows=windows,qualification="diagnostic; not a physical throughput qualification")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial",type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():
        parser.error("Output exists; preserve earlier evidence")
    result=analyze(args.serial.read_text(encoding="utf-8-sig"))
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(complete=result["complete"],errors=result["errors"])))
    return 0 if result["complete"] else 1

if __name__=="__main__":
    raise SystemExit(main())
