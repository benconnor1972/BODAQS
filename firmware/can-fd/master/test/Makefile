BUILD_DIR ?= .build
CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../include
PYTHON ?= python
.PHONY: test
test: $(BUILD_DIR)/test_timing.exe
	$(BUILD_DIR)/test_timing.exe
	$(PYTHON) test_adapter_runtime.py --cc "$(CC)"
	$(PYTHON) test_inventory_runtime.py --cc "$(CC)"
$(BUILD_DIR)/test_timing.exe: test_timing.c ../src/master_timing.c ../include/master_timing.h ti_msp_dl_config.h
	$(CC) $(CFLAGS) $(filter %.c,$^) -o $@

$(BUILD_DIR)/test_timing.exe: | $(BUILD_DIR)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
