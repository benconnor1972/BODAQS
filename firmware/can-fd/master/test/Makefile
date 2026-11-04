CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../include
.PHONY: test
test: test_timing.exe
	./test_timing.exe
test_timing.exe: test_timing.c ../src/master_timing.c ../include/master_timing.h ti_msp_dl_config.h
	$(CC) $(CFLAGS) $(filter %.c,$^) -o $@
