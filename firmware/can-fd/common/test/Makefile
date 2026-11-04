CXX ?= g++
CXXFLAGS := -std=c++17 -Wall -Wextra -Werror -O2

TEST_BINS := test_master_protocol.exe test_can_network.exe
LOGGER_PROTOCOL := ../../../src/CanMasterProtocol.cpp
MASTER_PROTOCOL := ../protocol/bodaqs_master_protocol.c
MASTER_SERVICE := ../protocol/bodaqs_master_service.c
CAN_NETWORK := ../network/bodaqs_can_network.c
NODE_INVENTORY := ../network/bodaqs_node_inventory.c

ifeq ($(OS),Windows_NT)
REMOVE := cmd /c del /q
else
REMOVE := rm -f
endif

.PHONY: test clean

test: $(TEST_BINS)
	./test_master_protocol.exe
	./test_can_network.exe

test_master_protocol.exe: test_master_protocol.cpp $(LOGGER_PROTOCOL) $(MASTER_PROTOCOL) $(MASTER_SERVICE)
	$(CXX) $(CXXFLAGS) -I../protocol -I../../../src -o $@ $^

test_can_network.exe: test_can_network.cpp $(CAN_NETWORK) $(NODE_INVENTORY)
	$(CXX) $(CXXFLAGS) -I../network -o $@ $^

clean:
	-$(REMOVE) $(TEST_BINS)

