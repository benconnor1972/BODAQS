CXX ?= g++
CXXFLAGS := -std=c++17 -Wall -Wextra -Werror -O2

TEST_BINS := test_authority.exe test_master_protocol.exe test_can_network.exe test_deferred_transport.exe test_control.exe test_control_transport.exe test_snapshot.exe
LOGGER_PROTOCOL := ../../../src/CanMasterProtocol.cpp
MASTER_PROTOCOL := ../protocol/bodaqs_master_protocol.c
CONTROL := ../protocol/bodaqs_control_authority.c ../protocol/bodaqs_control_authority_client.c ../protocol/bodaqs_control_snapshot.c ../protocol/bodaqs_control_observer.c ../protocol/bodaqs_control.c ../protocol/bodaqs_control_exchange.c
MASTER_SERVICE := ../protocol/bodaqs_master_service.c $(CONTROL)
CAN_NETWORK := ../network/bodaqs_can_network.c
NODE_INVENTORY := ../network/bodaqs_node_inventory.c

ifeq ($(OS),Windows_NT)
REMOVE := cmd /c del /q
else
REMOVE := rm -f
endif

.PHONY: test clean

test: $(TEST_BINS)
	./test_authority.exe
	./test_master_protocol.exe
	./test_can_network.exe
	./test_deferred_transport.exe
	./test_control.exe
	./test_control_transport.exe
	./test_snapshot.exe

test_master_protocol.exe: test_master_protocol.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

test_can_network.exe: test_can_network.cpp $(CAN_NETWORK) $(NODE_INVENTORY)
	$(CXX) $(CXXFLAGS) -I../network -o $@ $(filter %.cpp %.c,$^)

test_deferred_transport.exe: test_deferred_transport.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE) ../transport/bodaqs_record_queue.h
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

clean:
	-$(REMOVE) $(TEST_BINS)

test_control.exe: test_control.cpp $(CONTROL)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

test_control_transport.exe: test_control_transport.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $(filter %.cpp %.c,$^)

$(filter-out test_can_network.exe,$(TEST_BINS)): $(wildcard ../protocol/bodaqs_control*.h)

test_authority.exe: test_authority.cpp ../protocol/bodaqs_control.c ../protocol/bodaqs_control_authority.c ../protocol/bodaqs_control_authority_client.c
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)

test_snapshot.exe: test_snapshot.cpp $(CONTROL)
	$(CXX) $(CXXFLAGS) -I../protocol -o $@ $(filter %.cpp %.c,$^)
