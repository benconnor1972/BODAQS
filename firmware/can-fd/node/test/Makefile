BUILD_DIR ?= .build
PYTHON ?= python
CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../src -I../../common/protocol
NODE := ../src/imu_spi.c ../src/imu_capture.c ../src/imu_acquisition.c
COMMON := ../../common/protocol/bodaqs_imu_disabled.c ../../common/protocol/bodaqs_control.c
.PHONY: test
test: $(BUILD_DIR)/test_capture.exe $(BUILD_DIR)/test_spi.exe $(BUILD_DIR)/test_acquisition.exe
	$(BUILD_DIR)/test_capture.exe
	$(BUILD_DIR)/test_spi.exe
	$(BUILD_DIR)/test_acquisition.exe
	$(BUILD_DIR)/test_acquisition.exe 2
	$(BUILD_DIR)/test_acquisition.exe 3
	$(BUILD_DIR)/test_acquisition.exe 4
	$(BUILD_DIR)/test_acquisition.exe 5
	$(BUILD_DIR)/test_acquisition.exe 6
	$(BUILD_DIR)/test_acquisition.exe 7
	$(BUILD_DIR)/test_acquisition.exe 8
	$(BUILD_DIR)/test_acquisition.exe 9
	$(BUILD_DIR)/test_acquisition.exe 10
	$(BUILD_DIR)/test_acquisition.exe 11
	$(BUILD_DIR)/test_acquisition.exe 12
	$(BUILD_DIR)/test_acquisition.exe 13
$(BUILD_DIR)/test_capture.exe: test_capture.c ../src/imu_capture.c
	$(CC) $(CFLAGS) $^ -o $@
$(BUILD_DIR)/test_spi.exe: test_spi.c ../src/imu_spi.c
	$(CC) $(CFLAGS) $^ -o $@
$(BUILD_DIR)/test_acquisition.exe: test_acquisition.c $(NODE) $(COMMON)
	$(CC) $(CFLAGS) $^ -o $@

$(BUILD_DIR)/test_capture.exe $(BUILD_DIR)/test_spi.exe $(BUILD_DIR)/test_acquisition.exe: | $(BUILD_DIR)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
