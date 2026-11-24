"""Run the real card/file ownership adapter against an independent SDK/filesystem model."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    sdk=r'''
#pragma once
#include <Arduino.h>
#include <memory>
#include <string>
using boolean=bool;
constexpr int BOARD_MAX_SDMMC_FREQ=20000;
using sdcard_type_t=int;
constexpr sdcard_type_t CARD_NONE=0;
namespace Hardware {inline bool mounted=false,beginOk=true;inline unsigned unmounts=0,accesses=0;}
namespace fs {
enum SeekMode{SeekSet};
class FileImpl;
using FileImplPtr=std::shared_ptr<FileImpl>;
class FileImpl {
public:
 virtual ~FileImpl()=default;
 virtual size_t write(const uint8_t*,size_t n){return n;}
 virtual size_t read(uint8_t*,size_t){return 0;}
 virtual void flush(){} virtual bool seek(uint32_t,SeekMode){return true;}
 virtual size_t position()const{return 0;}virtual size_t size()const{return 0;}
 virtual bool setBufferSize(size_t){return true;}virtual void close(){}
 virtual time_t getLastWrite(){return 0;}virtual const char* path()const{return "/recording.bdq";}
 virtual const char* name()const{return "recording.bdq";}virtual boolean isDirectory(){return false;}
 virtual FileImplPtr openNextFile(const char*){return std::make_shared<FileImpl>();}
 virtual boolean seekDir(long){return true;}virtual String getNextFileName(){return "recording.bdq";}
 virtual String getNextFileName(bool*){return "recording.bdq";}virtual void rewindDirectory(){}
 virtual operator bool(){return true;}
};
class File {
 FileImplPtr impl_;
public:
 File()=default;explicit File(FileImplPtr value):impl_(std::move(value)){}
 explicit operator bool()const{return bool(impl_);}
 File openNextFile(){return File(impl_->openNextFile("r"));}
};
class VFSImpl {
public:
 virtual ~VFSImpl()=default;
 virtual FileImplPtr open(const char*,const char*,bool){++Hardware::accesses;return std::make_shared<FileImpl>();}
 virtual bool exists(const char*){++Hardware::accesses;return true;}
 virtual bool rename(const char*,const char*){++Hardware::accesses;return true;}
 virtual bool remove(const char*){++Hardware::accesses;return true;}
 virtual bool mkdir(const char*){++Hardware::accesses;return true;}
 virtual bool rmdir(const char*){++Hardware::accesses;return true;}
};
class SDMMCFS {
 std::shared_ptr<VFSImpl> impl_;
public:
 void* _card=nullptr;
 SDMMCFS():impl_(std::make_shared<VFSImpl>()){}
 explicit SDMMCFS(std::shared_ptr<VFSImpl> impl):impl_(std::move(impl)){}
 bool begin(const char*="/sdcard",bool=false,bool=false,int=20000,uint8_t=5){
  if(!Hardware::beginOk)return false;_card=this;Hardware::mounted=true;return true;
 }
 void end(){++Hardware::unmounts;Hardware::mounted=false;_card=nullptr;}
 sdcard_type_t cardType(){++Hardware::accesses;return Hardware::mounted?1:0;}
 uint64_t cardSize(){++Hardware::accesses;return 1024;}
 uint64_t totalBytes(){++Hardware::accesses;return 1024;}
 uint64_t usedBytes(){++Hardware::accesses;return 100;}
 File open(const char* name){return File(impl_->open(name,"r",false));}
 bool exists(const char* name){return impl_->exists(name);}
};
}
using fs::VFSImpl;
using fs::SeekMode;
inline fs::SDMMCFS SD_MMC;
'''
    fixture=r'''
#include "StorageFilesystem.h"
#include <cassert>
#include <cstdio>
int main(){
 auto& card=StorageFilesystem::card();
 assert(card.begin());
#if BODAQS_A8_USB_DRIVE
 auto& owner=StorageFilesystem::ownership();
 auto file=card.open("/recording.bdq");auto copy=file;assert(file && copy);
 assert(owner.requestExternal());card.service();assert(Hardware::mounted);
 const auto accesses=Hardware::accesses;
 assert(!card.open("/new.bdq") && !card.exists("/recording.bdq") && card.cardType()==CARD_NONE);
 assert(Hardware::accesses==accesses);
 file={};card.service();assert(Hardware::mounted); // copied handle still owns access
 copy={};card.service();assert(!Hardware::mounted && owner.state()==StorageOwnership::State::External);
 Hardware::beginOk=false;assert(!card.reclaim());assert(owner.state()==StorageOwnership::State::Error);
 Hardware::beginOk=true;assert(card.reclaim());assert(owner.localAvailable());
 auto directory=card.open("/");auto child=directory.openNextFile();directory={};
 assert(owner.requestExternal());card.service();assert(Hardware::mounted);
 child={};card.service();assert(!Hardware::mounted);assert(card.reclaim());
 puts("Actual card/file adapter: copied handles, directory children, external no-I/O and failed reclaim/retry passed");
#else
 assert(&card==&SD_MMC);
 puts("USB-disabled filesystem remains the original SDK card");
#endif
}
'''
    with tempfile.TemporaryDirectory(prefix='bodaqs-card-ownership-') as tmp:
        folder=Path(tmp)
        (folder/'SD_MMC.h').write_text(sdk.replace('const char*=', 'const char* ='),encoding='utf-8')
        (folder/'vfs_api.h').write_text('#pragma once\n#include "SD_MMC.h"\n')
        (folder/'test.cpp').write_text(fixture,encoding='utf-8')
        for enabled in (0,1):
            exe=folder/f'card{enabled}.exe'
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Wno-misleading-indentation',
                '-DARDUINO_ARCH_ESP32=1',f'-DBODAQS_A8_USB_DRIVE={enabled}',
                '-I',str(folder),'-I',str(root/'test/stubs'),'-I',str(root/'src'),
                str(folder/'test.cpp'),str(root/'src/StorageFilesystem.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=15)


if __name__=='__main__':main()
