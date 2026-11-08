"""Compile real ESP32 ADC/shared-SPI code against GPIO/SPI/RTOS boundary fixtures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--case-runner", action="store_true", help="Also compile public serial/result and transport seam")
    parser.add_argument("--gpio-startup", action="store_true", help="Actual Arduino GPIO wrapper with paused first ISR allocation")
    parser.add_argument("--gpio-production", action="store_true", help="Exercise GPIO startup with probe instrumentation compiled out")
    parser.add_argument("--framework", type=Path, default=Path.home() / ".platformio/packages/framework-arduinoespressif32")
    parser.add_argument("--capture", type=Path, help="Retain emitted public JSON cases")
    parser.add_argument("--skip-analyzer", action="store_true", help="Logger-only development before analyzer integration")
    parser.add_argument("--crc-bitwise", action="store_true", help="Build the logger probe comparison image")
    args = parser.parse_args()
    if args.gpio_production and (not args.gpio_startup or args.case_runner):
        parser.error("--gpio-production requires --gpio-startup without --case-runner")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-spi-probe-") as temp:
        temp = Path(temp)
        arduino = (root / "test/stubs/Arduino.h").read_text(encoding="utf-8")
        arduino = arduino.replace('inline void delay(unsigned long /*ms*/) {}', 'void delay(unsigned long ms);')
        start = arduino.index('inline unsigned long millis()')
        end = arduino.index('\n}', start) + 2
        arduino = arduino[:start] + 'unsigned long millis();' + arduino[end:]
        arduino += (root / "test/spi_probe_stubs/ArduinoBoundary.h").read_text(encoding="utf-8")
        (temp / "Arduino.h").write_text(arduino, encoding="utf-8")
        for src in (root / "test/spi_probe_stubs").rglob("*.h"):
            if src.name == "ArduinoBoundary.h":
                continue
            dest = temp / src.relative_to(root / "test/spi_probe_stubs")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        fixture = (root / "test/spi_probe_runtime_fixture.cpp").read_text(encoding="utf-8")
        config_support = (root / "test/sensor_config_runtime_fixture.cpp").read_text(encoding="utf-8").split('// PRODUCTION_CONFIG')[0]
        config_support = '\n'.join(line for line in config_support.splitlines()
            if not any(s in line for s in ('ArduinoJson', 'convertFromJson', 'canConvertFromJson', 'WebServer.h', 'namespace AnalogInputManager')))
        config = '\n'.join(line for line in (root / "src/ConfigManager.cpp").read_text(encoding="utf-8").splitlines() if not line.startswith('#include'))
        fixture = fixture.replace('// CONFIG_SUPPORT', config_support + '\n' + config)
        if args.gpio_startup:
            from spi_probe_gpio_startup import fixture_with_gpio_startup
            fixture = fixture_with_gpio_startup(fixture, args.framework)
        if args.case_runner:
            fixture = '#define TEST_CASE_RUNNER 1\n' + fixture
        cpp, exe = temp / "fixture.cpp", temp / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        sources = [root / 'src' / name for name in ('AnalogInputManager.cpp', 'SharedSpiBus.cpp', 'SensorParams.cpp', 'SensorAssignment.cpp', 'BoardProfile.cpp')]
        sources += [root / 'can-fd/common/protocol/bodaqs_control.c']
        if args.case_runner:
            sources += [root / 'src' / name for name in ('SpiMeasurementProbe.cpp', 'SpiProbeTransport.cpp', 'SpiProbeCodec.cpp')]
        from spi_probe_build_identity import source_identity
        # The identity must change for an isolated change to another compiled TU.
        identity_root = temp / "identity-firmware"
        (identity_root / "src").mkdir(parents=True)
        identity_file = identity_root / "src/AnalogInputManager.cpp"
        identity_file.write_text("before", encoding="utf-8")
        subprocess.run(['git', 'init', '--quiet', str(identity_root)], check=True)
        (identity_root / '.gitignore').write_text('can-fd/master/ticlang/ti_msp_dl_config.*\n', encoding='utf-8')
        subprocess.run(['git', 'add', '.'], cwd=identity_root, check=True)
        first_identity = source_identity(identity_root)
        generated = identity_root / 'can-fd/master/ticlang/ti_msp_dl_config.c'
        generated.parent.mkdir(parents=True)
        generated.write_text('ignored SDK generation', encoding='utf-8')
        assert source_identity(identity_root) == first_identity
        identity_file.write_text("after", encoding="utf-8")
        assert source_identity(identity_root) != first_identity
        probe_flags = [] if args.gpio_production else ['-DBODAQS_SPI_PROBE=1',
            '-DBODAQS_SPI_PROBE_LOGGER_CRC_TABLE=' + str(int(not args.crc_bitwise)),
            '-DBODAQS_SPI_PROBE_BUILD="' + source_identity(root,int(not args.crc_bitwise)) + '"']
        subprocess.run([args.compiler, '-std=gnu++2a', '-pthread', '-DESP32=1', *probe_flags, '-DLOG_COMPILED=0', '-Wno-unused', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-I', str(temp), '-I', str(root / 'test/stubs'), '-I', str(root / 'src'), str(cpp), *map(str, sources), '-o', str(exe)], check=True)
        run = subprocess.run([str(exe)], timeout=30, capture_output=True, text=True)
        print(run.stdout, end="")
        if run.returncode:
            print(run.stderr, end="")
            run.check_returncode()
        if args.case_runner:
            events = [json.loads(line) for line in run.stdout.splitlines() if line.startswith('{"schema"')]
            cases = [event for event in events if event['type'] == 'case']
            if args.capture:
                args.capture.write_text('\n'.join(json.dumps(event) for event in events) + '\n', encoding='utf-8')
            assert [case['case_id'] for case in cases] == [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, *range(33,57)]
            assert (cases[0]['rows'], cases[0]['missed_rows']) == (5000, 0)
            assert (cases[1]['rows'], cases[1]['missed_rows']) == (49, 1)
            assert (cases[2]['rows'], cases[2]['missed_rows']) == (1, 1)
            assert (cases[3]['rows'], cases[3]['missed_rows']) == (0, 50)
            assert cases[8]['outcome'] == 'failed' and cases[8]['elapsed_us'] < 100000
            for case in cases:
                assert case['workers_stopped'] and case['profile']['actual_sck_hz'] is None
                assert case['accepted_bytes'] == case['unique_objects'] * 1008
                assert case['valid_responses'] <= case['slots']
                assert case['schema'] == 'bodaqs.spi-probe.v10'
                cost=case['logger_cost'];cadence=cost['cadence']
                assert cost['crc_algorithm']==('bitwise' if args.crc_bitwise else 'table')
                assert case['artifacts']['logger_build'].endswith('-crc'+str(int(not args.crc_bitwise)))
                assert sum(v['count'] for v in cadence['decisions'].values())==cadence['cycle']['count']
                assert sum(v['total_us'] for v in cadence['decisions'].values())==cadence['cycle']['total_us']
                assert sum(cadence[n]['total_us'] for n in ('adc_ready_service','row_service','adc_start_service','transport_service'))<=cadence['cycle']['total_us']
                if case['case_id'] in (34,35,45,46,51):
                    assert cadence['decisions']['dispatch']['count']==case['slots']>0
                    assert cadence['decisions']['row_reserve']['count']>0
                    assert cadence['decisions']['pacing']['count']>0
                    assert cadence['dispatch_headroom']['min_us']>800
                d = case['diagnostics']
                assert sum(d['decode_counts']) + case['errors']['transfer'] == case['slots']
                assert sum(d['decode_counts'][1:]) == case['errors']['wire']
                assert len(d['failure_samples']) + d['failure_samples_omitted'] == case['errors']['wire']
                assert sum(p['responses'] for p in d['by_previous_cs']) == d['decode_counts'][0]
                assert sum(p['decode_failures'] for p in d['by_previous_cs']) == case['errors']['wire']
                assert d['expected_crc_calls'] == d['timing']['expected_crc']['count']
                assert case['timing']['decode']['count'] == sum(d['decode_counts'])
                if case['profile']['mode'] in ('adc', 'mixed'):
                    expected = {1: 5000, 3: 2, 6: 0}.get(case['case_id'], 50)
                    assert case['rows'] + case['missed_rows'] == expected
                    for adc in case['adc']:
                        assert adc['uses'] == case['rows']
                        assert adc['fresh'] + adc['reused'] + adc['no_sample'] == adc['uses']
                        assert 'drdy_to_read_attempt' in adc and 'drdy_pre_start' in adc
            print('JSON public results: parseable, balanced identities/rows, explicit unknown SCK passed')
            capture = temp / 'public-cases.jsonl'
            capture.write_text('\n'.join(json.dumps(case) for case in cases), encoding='utf-8')
            if args.skip_analyzer:
                return
            analyzed = subprocess.run([sys.executable, str(root / 'tools/analyze_spi_probe.py'), str(capture)],
                                      capture_output=True, text=True)
            assert analyzed.returncode == 0, analyzed.stderr
            rail_fault = next(case for case in json.loads(analyzed.stdout)['cases'] if case['case_id'] == 6)
            assert rail_fault['reason'] == 'analog_rail_fault' and rail_fault['raw_measurements']['elapsed_us'] == 0
            assert rail_fault['adc_status'] == 'failed' and rail_fault['candidate_evidence'] == 'failed'
            print('Public rail-fault capture through analyzer CLI: no observed ADC rows cannot report healthy passed')
            report = json.loads(analyzed.stdout)
            for cid in (53,54,55):
                flow=next(c for c in report['cases'] if c['case_id']==cid)
                assert flow['master_flow_control']['status']=='observed'
                assert flow['row_freshness_status']=='healthy' and flow['transport_status']=='clean'
                assert flow['master_flow_control']['bypassed']>=flow['request_window']['clock_requests']>0
            failed_entry=next(c for c in report['cases'] if c['case_id']==56)
            assert failed_entry['outcome']=='failed' and failed_entry['raw_measurements']['slots']==0
            unsupported=next(c for c in report['cases'] if c['case_id']==52)
            assert unsupported['raw_measurements']['master']['receive_measured'] is False
            assert unsupported['master_receive_turnover']['status']=='unknown'
            compat=unsupported['raw_measurements']
            assert compat['outcome']=='complete' and compat['rows']==50 and compat['missed_rows']==0
            assert compat['row_publication']['fresh_both']==50
            assert compat['errors']['accept']==compat['errors']['wire']==compat['errors']['transfer']==0
            switch_failure = next(case for case in report['cases'] if case['case_id'] == 15)
            assert switch_failure['candidate_evidence'] == 'failed'
            diagnostic = switch_failure['raw_measurements']['diagnostics']
            assert diagnostic['switch_transfers'] == 0 and diagnostic['switch_failures'] == 1
            assert not any(report[key] for key in ('production_qualified', 't01_go', 'admission_authorized'))
            print('Public first switch lock failure through analyzer CLI: independent counts retained as failed passed')
            for cid in (16,17):
                control = next(case for case in report['cases'] if case['case_id'] == cid)
                assert control['adc_status'] == 'not_applicable' and control['rows_per_second'] == 0
                assert control['sequential_control']['active'] and not control['sequential_control']['worker_start_requested']
                assert control['candidate_evidence'] != 'clean_measurement_candidate'
            for cid in (18,19,20,21,22):
                assert next(case for case in report['cases'] if case['case_id'] == cid)['candidate_evidence'] == 'failed'
            for cid,mask,core in ((23,3,0),(24,3,1),(25,1,0),(26,2,0),(27,3,1),(28,1,1)):
                case=next(c for c in cases if c['case_id']==cid)
                e=case['execution']
                assert (e['adc_mask'],e['adc_core'])==(mask,core)
                assert e['window_ended_us']>e['window_started_us']>0
                for adc,cs in enumerate((47,21)):
                    traffic=next((p for p in e['traffic'] if p['cs']==cs),None)
                    if mask & (1<<adc):
                        assert traffic and traffic['operations'][2]>0 and traffic['core_mask']==1<<core
                        rate=traffic['operations'][2]*1e6/(e['window_ended_us']-e['window_started_us'])
                        assert rate<1000 # minimum cycle bounds effective despite simulated peripherals
                    else:
                        assert traffic is None
                assert case['rows']==0 and case['workers_stopped']
            assert next(c for c in cases if c['case_id']==29)['reason']=='adc_ready_timeout'
            assert next(c for c in cases if c['case_id']==30)['outcome']=='stopped'
            assert next(c for c in cases if c['case_id']==32)['outcome']=='stopped'
            reset=next(c for c in cases if c['case_id']==31)['execution']
            assert (reset['adc_mask'],reset['adc_core'],reset['cycle_us'])==(3,0,0)
            for cid in (33,34,35,40):
                case=next(c for c in cases if c['case_id']==cid)
                publication=case['row_publication']
                assert case['rows']==50 and case['missed_rows']==0
                assert publication['published']==publication['valid_both']==publication['fresh_both']==50
                assert all(sample['counts']==[0,319] for sample in publication['samples'])
                assert all(sample['fresh_mask']==3 for sample in publication['samples'])
                assert all(a['fresh']==50 and a['reused']==a['no_sample']==0 for a in case['adc'])
                for adc,cs in enumerate((47,21)):
                    t=next(t for t in case['execution']['traffic'] if t['cs']==cs)
                    assert t['operations']==case['diagnostics']['sequence']['operations'][adc] # row consumption clocks no extra conversions
                if cid in (34,35):assert publication['master_deferrals']>0
                if cid==35:assert case['diagnostics']['timing']['request_interval']['min_us']>=1000
            for cid in (45,46,51):
                case=next(c for c in cases if c['case_id']==cid)
                assert case['rows']==50 and case['row_publication']['fresh_both']==50
                w=case['request_window']
                assert w['active'] and w['high_water']<=4
                assert w['new_requests']+w['retry_requests']+w['clock_requests']==case['slots']
                assert w['new_requests']==w['reply_age']['count']+w['pending']
            for cid in (47,48,49,50):
                result=next(c for c in report['cases'] if c['case_id']==cid)
                assert result['candidate_evidence']=='failed'
            assert next(c for c in cases if c['case_id']==48)['request_window']['retry_exhausted']==1
            slow=next(c for c in report['cases'] if c['case_id']==36)
            assert slow['row_freshness_status']=='failed' and slow['raw_measurements']['row_publication']['fresh_both']<50
            assert next(c for c in cases if c['case_id']==37)['reason']=='adc_ready_timeout'
            assert next(c for c in cases if c['case_id']==38)['outcome']=='stopped'
            print('Public owner row publication:500Hz fresh signed samples, reuse rejection, timeout, STOP and no implicit row SPI passed')
            print('Public execution controls: requested core/mask agrees with timed observations, pacing limits, worker-free owner, timeout and STOP passed')
            print('Public sequential controls: raw fault provenance, readiness timeout, lock failure, STOP in wait and empty-window failure passed')


if __name__ == '__main__':
    main()
