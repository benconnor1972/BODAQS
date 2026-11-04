CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../include
PYTHON ?= python
.PHONY: test
test: test_timing.exe
	./test_timing.exe
	$(PYTHON) test_adapter_runtime.py --cc "$(CC)"
test_timing.exe: test_timing.c ../src/master_timing.c ../include/master_timing.h ti_msp_dl_config.h
	$(CC) $(CFLAGS) $(filter %.c,$^) -o $@
