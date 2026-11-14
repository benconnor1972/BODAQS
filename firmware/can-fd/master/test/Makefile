BUILD_DIR ?= .build
CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../include
PYTHON ?= python
.PHONY: test
test: $(BUILD_DIR)/test_timing.exe $(BUILD_DIR)/test_spi_trace.exe
	$(BUILD_DIR)/test_timing.exe
	$(BUILD_DIR)/test_spi_trace.exe
	$(PYTHON) test_adapter_runtime.py --cc "$(CC)"
	$(PYTHON) test_spi_priming_runtime.py --cc "$(CC)"
	$(PYTHON) test_spi_priming_runtime.py --boundary-trace --cc "$(CC)"
	$(PYTHON) test_spi_priming_runtime.py --disabled-init --boundary-trace --cc "$(CC)"
	$(PYTHON) test_spi_initialization_runtime.py --cc "$(CC)"
	$(PYTHON) test_spi_priming_runtime.py --bulk --disabled-init --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --bulk --phase-timing --rx-capacity 2 --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --phase-timing --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --phase-timing --queue-timing --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --phase-timing --queue-timing --rx-capacity 2 --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --phase-timing --queue-timing --rx-capacity 2 --block-crc --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --phase-timing --queue-timing --rx-capacity 2 --can-first --cc "$(CC)"
	$(PYTHON) test_adapter_runtime.py --v2 --boundary-trace --rx-capacity 2 --cc "$(CC)"
	$(PYTHON) test_inventory_runtime.py --cc "$(CC)"
$(BUILD_DIR)/test_timing.exe: test_timing.c ../src/master_timing.c ../include/master_timing.h ti_msp_dl_config.h
	$(CC) $(CFLAGS) $(filter %.c,$^) -o $@

$(BUILD_DIR)/test_timing.exe: | $(BUILD_DIR)

$(BUILD_DIR)/test_spi_trace.exe: test_spi_trace.c ../../common/transport/bodaqs_spi_trace.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) -DBODAQS_SPI_MEASUREMENT_V2=1 test_spi_trace.c -o $@

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
