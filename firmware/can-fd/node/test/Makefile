CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O2 -I. -I../src -I../../common/protocol
NODE := ../src/imu_spi.c ../src/imu_capture.c ../src/imu_acquisition.c
COMMON := ../../common/protocol/bodaqs_imu_disabled.c ../../common/protocol/bodaqs_control.c
.PHONY: test
test: test_capture.exe test_spi.exe test_acquisition.exe
	./test_capture.exe
	./test_spi.exe
	./test_acquisition.exe
	./test_acquisition.exe 2
	./test_acquisition.exe 3
	./test_acquisition.exe 4
	./test_acquisition.exe 5
test_capture.exe: test_capture.c ../src/imu_capture.c
	$(CC) $(CFLAGS) $^ -o $@
test_spi.exe: test_spi.c ../src/imu_spi.c
	$(CC) $(CFLAGS) $^ -o $@
test_acquisition.exe: test_acquisition.c $(NODE) $(COMMON)
	$(CC) $(CFLAGS) $^ -o $@
