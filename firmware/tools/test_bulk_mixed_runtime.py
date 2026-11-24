"""Exercise exact mixed admission through real remote configuration/ownership."""
import argparse,subprocess,tempfile,os
from pathlib import Path
from test_remote_imu_lifecycle_runtime import fixture_source

p=argparse.ArgumentParser();p.add_argument('--compiler',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];common=root/'can-fd/common/protocol'
source=fixture_source(root)
source=source.replace('bool getMuted(uint8_t,bool& value) { value=muted; return true; }',
    'bool getMuted(uint8_t i,bool& value) {SensorSpec s;if(!config.getSensorSpec(i,s)) return false;value=muted || s.mutedDefault;return true;}')
cases=(root/'test/remote_imu_lifecycle_runtime_fixture.cpp').read_text()
helpers=cases[:cases.index('int main(')]
start=cases[cases.index('int main('):cases.index('  const unsigned remoteNodes=fixtureSensorCount;')]
start=start.replace('fixtureSensorCount=argc>1 && (!std::strcmp(argv[1],"four") || !std::strcmp(argv[1],"four-bus-off"))?4:1;','fixtureSensorCount=4;')
body=r'''
 assert(argc==2);const std::string test=argv[1];
 config.sampleRateHz=500;profile.external_adc_count=2;profile.analog.count=8;
 for(unsigned adc=0;adc<2;++adc) {
  profile.external_adcs[adc].spi_hz=1000000;
  auto& in=profile.analog.inputs[adc*4];in.source=board::AnalogSourceType::ExternalAdc;
  in.external_adc_index=adc;in.external_channel=0;
  const unsigned i=fixtureSensorCount++-1;extra[i]={};extra[i].type=SensorType::AnalogPot;
  extraParams[i]={};assert(extraParams[i].set("ain",adc?"4":"0"));
  assert(extraParams[i].set("output_mode","0"));extra[i].params.bind(&extraParams[i]);
 }
 fixtureAdcChannels=1;fixtureAdcSps=1000;
 const bool rejected=test.find("reject-")==0;
 if(test=="adc-only") {saved.mutedDefault=true;for(unsigned i=0;i<3;++i)extra[i].mutedDefault=true;}
 if(test=="reject-duplicate")assert(extraParams[4].set("ain","0"));
 if(test=="reject-pin")assert(extraParams[4].set("ain","5"));
 if(test=="reject-map")profile.analog.inputs[4].external_channel=1;
 if(test=="reject-rate")config.sampleRateHz=200;
 if(test=="reject-count")extra[0].mutedDefault=true;
 if(test=="reject-other") {extra[5]={};extra[5].type=SensorType::BMI270ImuI2C;fixtureSensorCount=7;}
 if(test=="reject-raw-column")assert(extraParams[3].set("include_raw","true"));
 if(test=="reject-linear")assert(extraParams[3].set("output_mode","1"));
 if(test=="reject-transform")assert(extraParams[3].set("output_mode","2"));
 if(test=="reject-channels")fixtureAdcChannels=2;
 if(test=="reject-sps")fixtureAdcSps=2000;
 if(test=="reject-spi")profile.external_adcs[1].spi_hz=2000000;
 if(test=="reject-no-specs")extra[3].mutedDefault=extra[4].mutedDefault=true;
 if(test=="reject-inactive")fixtureAdcChannels=fixtureAdcSps=0;
 if(test=="reject-missing")extra[4].mutedDefault=true;
 if(test=="pure") {extra[3].mutedDefault=extra[4].mutedDefault=true;fixtureAdcChannels=fixtureAdcSps=0;}
 assert(RemoteImuRecording::configure(config));
 if(rejected) {
  assert(RemoteImuRecording::admission().reason!=ImuAdmission::Reason::None);
  assert(!RemoteImuRecording::configured() && !AcquisitionControl::active());
  assert(DynamicSpscQueueDetail::liveAllocations==0);
 } else {
  const auto& admission=RemoteImuRecording::admission();
  assert(admission.reason==ImuAdmission::Reason::None && admission.benchOnly && !admission.qualified);
  if(test=="adc-only") {
   assert(!admission.attempted && !RemoteImuRecording::configured());
   assert(!AcquisitionControl::active() && DynamicSpscQueueDetail::liveAllocations==0);
  } else {
   assert(admission.attempted && RemoteImuRecording::configured());
   assert(!AcquisitionControl::active()); // Buffers allocated, no remote authorization before storage readiness.
   BdqV2StreamDescriptor streams[8];assert(RemoteImuRecording::describe(streams,8,1)==8);
   RemoteImuRecording::discardAllocated();assert(DynamicSpscQueueDetail::liveAllocations==0);
  }
 }
 for(unsigned n=0;n<4;++n)assert(!acquisitions[n].recording && !acquisitions[n].lease_valid);
 printf("Production bulk mixed scope %s: PASS\n",test.c_str());
}
'''
sources=[*common.glob('bodaqs_control*.c'),common/'bodaqs_imu_disabled.c',common/'bodaqs_master_service.c',common/'bodaqs_master_protocol.c']
sources += [root/'src'/n for n in ('CanMasterProtocol.cpp','SensorAssignment.cpp','SensorParams.cpp','Lsm6dso32xConfig.cpp','RemoteImuStream.cpp','BdqV2Catalog.cpp','ImuAdmission.cpp')]
flags=['BODAQS_SINGLE_NODE_IMU_SMOKE','BODAQS_SPI_MEASUREMENT_V3','BODAQS_V3_TWO_NODE_BENCH','BODAQS_SPI_MEASUREMENT_V4','BODAQS_V4_FOUR_NODE_BENCH','BODAQS_BULK_MIXED_ADC_BENCH','BODAQS_REQUEST_BUILD_FAST','BODAQS_MASTER_BLOCK_CRC']
with tempfile.TemporaryDirectory() as temp:
    temp=Path(temp);cpp=temp/'fixture.cpp';exe=temp/'fixture.exe'
    cpp.write_text(source+'\n'+helpers+start+body,encoding='utf-8')
    subprocess.run([a.compiler,'-std=c++17','-DBODAQS_QUEUE_ALLOCATION_TEST',*['-D'+f+'=1' for f in flags],'-DBODAQS_SPI_BULK_BYTES=512',
      '-ffunction-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror','-Wno-class-memaccess','-Wno-unused-function','-Wno-unused-variable',
      '-I',str(root/'test/stubs'),'-I',str(root/'src'),'-I',str(common),'-I',str(root/'can-fd/common/test'),str(cpp),*map(str,sources),'-o',str(exe)],check=True)
    for case in ['mixed','adc-only','pure','reject-duplicate','reject-pin','reject-map','reject-rate','reject-count','reject-other','reject-raw-column','reject-linear','reject-transform','reject-channels','reject-sps','reject-spi','reject-no-specs','reject-inactive','reject-missing']:
        subprocess.run([str(exe),case],check=True)
