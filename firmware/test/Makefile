# ─────────────────────────────────────────────────────────────────
# Makefile for host-based tests
#
# Compiles stubs + production source + test files with host g++.
# Stubs take precedence over real headers via -I order.
#
# Usage:
#   make -C test test     # build and run tests
#   make -C test clean    # remove build artifacts
# ─────────────────────────────────────────────────────────────────

CXX      = g++
PYTHON   ?= python
CXXFLAGS = -std=gnu++2a -I stubs -I ../src -Wall -Wno-unused
CXXFLAGS += '-DBODAQS_FW_VERSION="0.4.1"' '-DBODAQS_FW_NAME="BODAQS"'

# Production source files to compile (extend as more files are tested)
PROD_SRCS = ../src/HtmlUtil.cpp ../src/Routes_Static.cpp ../src/BMI270FifoParser.cpp ../src/BdqV2Catalog.cpp ../src/BdqV2PrimaryStream.cpp ../src/BdqV2Writer.cpp ../src/BoardProfile.cpp ../src/CanMasterProtocol.cpp ../src/SensorParams.cpp ../src/SensorAssignment.cpp ../src/SensorDiagnostics.cpp ../src/SensorInventory.cpp

# Stub source files
STUB_SRCS = stubs/mocks.cpp stubs/HttpFileSender_stub.cpp

# Test files (auto-discovered)
TEST_SRCS = $(wildcard test_*.cpp)

# Test binary
BUILD_DIR ?= .build
TEST_BIN = $(BUILD_DIR)/test_runner.exe

.PHONY: test clean

test: $(TEST_BIN)
	@echo "Running tests..."
	"$(TEST_BIN)"
	$(PYTHON) ../tools/test_i2c_schedule_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_i2c_startup_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_startup_log_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_logging_start_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_logging_start_runtime.py --async-storage --compiler "$(CXX)"
	$(PYTHON) ../tools/test_storage_worker_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_sensor_config_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_control_recovery_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_mute_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_control_recording_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_master_timing_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_measurement_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_acquisition_control_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_imu_admission_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_lifecycle_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_lifecycle_runtime.py --smoke --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_lifecycle_runtime.py --smoke --v2 --compiler "$(CXX)"
	$(PYTHON) ../tools/test_measurement_v2_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_master_phase_timing_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_spi_start_spacing_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_lifecycle_runtime.py --smoke --v2 --start-spacing-us 500 --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_lifecycle_runtime.py --smoke --v2 --start-spacing-us 500 --flow-diagnostics --compiler "$(CXX)"
	$(PYTHON) ../tools/test_imu_flow_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_stream_contract.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_recording_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_remote_imu_loss_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_node_master_bdq_runtime.py --compiler "$(CXX)" --cc "$(CC)"
	$(PYTHON) ../tools/test_node_master_bdq_runtime.py --v2 --compiler "$(CXX)" --cc "$(CC)"
	$(PYTHON) ../tools/test_integrated_imu_recording_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../tools/test_integrated_imu_recording_runtime.py --first-recording --compiler "$(CXX)" --cc "$(CC)"
	$(PYTHON) ../tools/test_integrated_imu_recording_runtime.py --first-recording --flow-diagnostics --compiler "$(CXX)" --cc "$(CC)"
	@echo "All tests passed."

$(TEST_BIN): $(PROD_SRCS) $(STUB_SRCS) $(TEST_SRCS) | $(BUILD_DIR)
	@echo "Compiling test binary..."
	$(CXX) $(CXXFLAGS) -o $@ $(PROD_SRCS) $(STUB_SRCS) $(TEST_SRCS)

clean:
	$(PYTHON) -c "from pathlib import Path; Path('$(TEST_BIN)').unlink(missing_ok=True)"

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
