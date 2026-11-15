BUILD_DIR ?= .build
PYTHON ?= python
CXX ?= g++
CXXFLAGS := -std=c++17 -Wall -Wextra -Werror -O2

TEST_BINS := $(BUILD_DIR)/test_can_link.exe $(BUILD_DIR)/test_timing.exe $(BUILD_DIR)/test_master_retention.exe $(BUILD_DIR)/test_acquisition.exe $(BUILD_DIR)/test_frag_transport.exe $(BUILD_DIR)/test_measurement.exe $(BUILD_DIR)/test_apply.exe $(BUILD_DIR)/test_authority.exe $(BUILD_DIR)/test_master_protocol.exe $(BUILD_DIR)/test_can_network.exe $(BUILD_DIR)/test_deferred_transport.exe $(BUILD_DIR)/test_control.exe $(BUILD_DIR)/test_control_transport.exe $(BUILD_DIR)/test_snapshot.exe
LOGGER_PROTOCOL := ../../../src/CanMasterProtocol.cpp
MASTER_PROTOCOL := ../protocol/bodaqs_master_protocol.c
CONTROL := ../protocol/bodaqs_control_acquisition.c ../protocol/bodaqs_control_apply.c ../protocol/bodaqs_control_apply_client.c ../protocol/bodaqs_imu_disabled.c ../protocol/bodaqs_control_authority.c ../protocol/bodaqs_control_authority_client.c ../protocol/bodaqs_control_snapshot.c ../protocol/bodaqs_control_observer.c ../protocol/bodaqs_control.c ../protocol/bodaqs_control_exchange.c
MASTER_SERVICE := ../protocol/bodaqs_master_service.c $(CONTROL)
CAN_NETWORK := ../network/bodaqs_can_network.c
NODE_INVENTORY := ../network/bodaqs_node_inventory.c

.PHONY: test clean

test: $(TEST_BINS)
	$(PYTHON) ../../../tools/test_master_progress_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_master_progress_parser.py
	$(PYTHON) ../../../tools/test_bulk_codec_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_master_window_runtime.py --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_master_batch_diagnostics.py --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_measurement_crc_runtime.py --cc "$(CC)" --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_measurement_crc_runtime.py --block-crc --cc "$(CC)" --compiler "$(CXX)"
	$(PYTHON) ../../../tools/test_master_terminal_reserve.py --compiler "$(CXX)"
	$(BUILD_DIR)/test_can_link.exe
	$(BUILD_DIR)/test_timing.exe
	$(BUILD_DIR)/test_master_retention.exe
	$(BUILD_DIR)/test_acquisition.exe
	$(BUILD_DIR)/test_frag_transport.exe
	$(BUILD_DIR)/test_measurement.exe
	$(BUILD_DIR)/test_apply.exe
	$(BUILD_DIR)/test_authority.exe
	$(BUILD_DIR)/test_master_protocol.exe
	$(BUILD_DIR)/test_can_network.exe
	$(BUILD_DIR)/test_deferred_transport.exe
	$(BUILD_DIR)/test_control.exe
	$(BUILD_DIR)/test_control_transport.exe
	$(BUILD_DIR)/test_snapshot.exe

$(BUILD_DIR)/test_master_protocol.exe: test_master_protocol.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_can_network.exe: test_can_network.cpp $(CAN_NETWORK) $(NODE_INVENTORY)
	$(CXX) $(CXXFLAGS) -I../network -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_deferred_transport.exe: test_deferred_transport.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE) ../transport/bodaqs_record_queue.h
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

clean:
	$(PYTHON) -c "from pathlib import Path; [Path(p).unlink(missing_ok=True) for p in '$(TEST_BINS)'.split()]"

$(BUILD_DIR)/test_control.exe: test_control.cpp $(CONTROL)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_control_transport.exe: test_control_transport.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE) $(CAN_NETWORK) $(NODE_INVENTORY)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

$(filter-out $(BUILD_DIR)/test_can_network.exe,$(TEST_BINS)): $(wildcard ../protocol/bodaqs_control*.h)

$(BUILD_DIR)/test_authority.exe: test_authority.cpp ../protocol/bodaqs_control.c ../protocol/bodaqs_control_authority.c ../protocol/bodaqs_control_authority_client.c
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_snapshot.exe: test_snapshot.cpp $(CONTROL)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_apply.exe: test_apply.cpp $(CONTROL) $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) ../protocol/bodaqs_master_service.c
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_measurement.exe: test_measurement.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

$(filter-out $(BUILD_DIR)/test_can_network.exe,$(TEST_BINS)): ../protocol/bodaqs_measurement.h ../protocol/bodaqs_crc32_table_values.h
$(filter-out $(BUILD_DIR)/test_can_network.exe,$(TEST_BINS)): ../protocol/bodaqs_crc32_blocks.h

$(BUILD_DIR)/test_frag_transport.exe: test_frag_transport.cpp $(MASTER_PROTOCOL) $(MASTER_SERVICE) ../protocol/bodaqs_fragment_transport.h
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(filter-out $(BUILD_DIR)/test_can_network.exe,$(TEST_BINS)): ../protocol/bodaqs_fragment_transport.h

$(BUILD_DIR)/test_acquisition.exe: test_acquisition.cpp $(CONTROL) $(MASTER_PROTOCOL) ../protocol/bodaqs_master_service.c
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_master_retention.exe: test_master_retention.cpp $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_timing.exe: test_timing.cpp $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

$(BUILD_DIR)/test_can_link.exe: test_can_link.cpp ../network/bodaqs_can_link.h ../network/bodaqs_can_link_ti.h
	$(CXX) $(CXXFLAGS) -I../network -o $@ $<

$(TEST_BINS): | $(BUILD_DIR)

$(BUILD_DIR):
	$(PYTHON) -c "from pathlib import Path; Path('$(BUILD_DIR)').mkdir(parents=True, exist_ok=True)"
