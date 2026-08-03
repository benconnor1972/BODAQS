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
CXXFLAGS = -std=gnu++2a -I stubs -I ../src -Wall -Wno-unused
CXXFLAGS += '-DBODAQS_FW_VERSION="0.4.1"' '-DBODAQS_FW_NAME="BODAQS"'

# Production source files to compile (extend as more files are tested)
PROD_SRCS = ../src/HtmlUtil.cpp ../src/Routes_Static.cpp

# Stub source files
STUB_SRCS = stubs/mocks.cpp stubs/HttpFileSender_stub.cpp

# Test files (auto-discovered)
TEST_SRCS = $(wildcard test_*.cpp)

# Test binary
TEST_BIN = test_runner

.PHONY: test clean

test: $(TEST_BIN)
	@echo "Running tests..."
	./$(TEST_BIN)
	@echo "All tests passed."

$(TEST_BIN): $(PROD_SRCS) $(STUB_SRCS) $(TEST_SRCS)
	@echo "Compiling test binary..."
	$(CXX) $(CXXFLAGS) -o $@ $(PROD_SRCS) $(STUB_SRCS) $(TEST_SRCS)

clean:
	rm -f $(TEST_BIN)
