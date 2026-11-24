"""Run the operational storage adapter against an independent SD/allocator model."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-storage-path-") as tmp:
        folder = Path(tmp)
        headers = {
            "freertos/FreeRTOS.h": "#pragma once\n",
            "esp_heap_caps.h": """
#pragma once
#include <stddef.h>
#define MALLOC_CAP_INTERNAL 1
#define MALLOC_CAP_DMA 2
#define MALLOC_CAP_8BIT 4
void* heap_caps_malloc(size_t, unsigned);
void heap_caps_free(void*);
""",
            "soc/soc_memory_types.h": "#pragma once\nbool esp_ptr_dma_capable(const void*);\n",
            "esp_rom_crc.h": "#pragma once\n#include <stdint.h>\nuint32_t esp_rom_crc32_le(uint32_t,const uint8_t*,uint32_t);\n",
            "freertos/task.h": "#pragma once\nusing TaskHandle_t = void*;\nTaskHandle_t xTaskGetCurrentTaskHandle();\n",
            "sdmmc_cmd.h": """
#pragma once
#include <stddef.h>
#include <stdint.h>
using esp_err_t = int;
struct sdmmc_card_t { struct {uint32_t sector_size; int capacity;} csd; };
""",
        }
        for name, content in headers.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        exe = folder / "storage-path.exe"
        subprocess.run([
            args.compiler, "-std=c++17", "-Wall", "-Wextra", "-DESP32=1",
            "-DBODAQS_PRODUCTION_RECORDING=1", "-I", str(folder), "-I", str(root / "src"),
            str(root / "src/RecordingStoragePath.cpp"),
            str(root / "test/recording_storage_path_runtime_fixture.cpp"), "-o", str(exe),
        ], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == "__main__":
    main()
