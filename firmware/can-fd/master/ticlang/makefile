ifndef MSPM0_SDK_INSTALL_DIR
$(error Set MSPM0_SDK_INSTALL_DIR to the MSPM0 SDK directory)
endif

include $(MSPM0_SDK_INSTALL_DIR)/imports.mak

CC := "$(TICLANG_ARMCOMPILER)/bin/tiarmclang"
LNK := "$(TICLANG_ARMCOMPILER)/bin/tiarmclang"
SYSCFG_CMD := $(SYSCONFIG_TOOL) --compiler ticlang --product $(MSPM0_SDK_INSTALL_DIR)/.metadata/product.json
SYSCFG_FILES := $(shell $(SYSCFG_CMD) --listGeneratedFiles --listReferencedFiles --output . ../master.syscfg)
SYSCFG_C_FILES := $(filter %.c,$(SYSCFG_FILES))
SYSCFG_H_FILES := $(filter %.h,$(SYSCFG_FILES))
SYSCFG_OPT_FILES := $(filter %.opt,$(SYSCFG_FILES))
GENERATED_FILES := device.opt device.cmd.genlibs device_linker.cmd \
    ti_msp_dl_config.c ti_msp_dl_config.h Event.dot Graph.dot

# Both boards must select the same explicit link; no runtime rate changes.
CAN_LINK_PROFILE ?= bringup
ifeq ($(CAN_LINK_PROFILE),bringup)
CAN_LINK_DEFINE := 1
else ifeq ($(CAN_LINK_PROFILE),acquisition)
CAN_LINK_DEFINE := 2
else
$(error CAN_LINK_PROFILE must be bringup or acquisition)
endif

SPI_MEASUREMENT_PROFILE ?= legacy
ifeq ($(SPI_MEASUREMENT_PROFILE),legacy)
MEASUREMENT_DEFINE := 0
MASTER_STACK_BYTES := 2048
else ifeq ($(SPI_MEASUREMENT_PROFILE),first-recording)
MEASUREMENT_DEFINE := 1
MASTER_STACK_BYTES := 4096
else
$(error SPI_MEASUREMENT_PROFILE must be legacy or first-recording)
endif

# Only the explicit v2 comparison may select two cells. Defaults stay unchanged.
ifeq ($(SPI_MEASUREMENT_PROFILE),first-recording)
SPI_RX_CAPACITY ?= 4
ifneq ($(SPI_RX_CAPACITY),2)
ifneq ($(SPI_RX_CAPACITY),4)
$(error first-recording SPI_RX_CAPACITY must be 2 or 4)
endif
endif
else
SPI_RX_CAPACITY ?= 1
ifneq ($(SPI_RX_CAPACITY),1)
$(error legacy SPI_RX_CAPACITY must remain 1)
endif
endif

NAME := bodaqs_can_master
SPI_SAMPLE_UNITS ?= 0
SPI_SAMPLE_WINDOW ?= 0
ifneq ($(SPI_SAMPLE_WINDOW),0)
ifneq ($(SPI_SAMPLE_WINDOW),1)
$(error SPI_SAMPLE_WINDOW must be 0 or 1)
endif
ifneq ($(SPI_SAMPLE_UNITS),1)
$(error SPI_SAMPLE_WINDOW requires SPI_SAMPLE_UNITS=1)
endif
endif
ifneq ($(SPI_SAMPLE_UNITS),0)
ifneq ($(SPI_SAMPLE_UNITS),1)
$(error SPI_SAMPLE_UNITS must be 0 or 1)
endif
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error SPI_SAMPLE_UNITS requires first-recording)
endif
endif
MASTER_BLOCK_CRC ?= 0
MASTER_CAN_FIRST ?= 0
MASTER_BOUNDARY_RESERVE ?= 0
ifneq ($(MASTER_BOUNDARY_RESERVE),0)
ifneq ($(MASTER_BOUNDARY_RESERVE),2)
$(error MASTER_BOUNDARY_RESERVE must be 0 or 2)
endif
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error Boundary reserve requires first-recording)
endif
endif
ifneq ($(MASTER_BLOCK_CRC),0)
ifneq ($(MASTER_BLOCK_CRC),1)
$(error MASTER_BLOCK_CRC must be 0 or 1)
endif
endif
ifneq ($(MASTER_CAN_FIRST),0)
ifneq ($(MASTER_CAN_FIRST),1)
$(error MASTER_CAN_FIRST must be 0 or 1)
endif
endif
ifneq ($(MASTER_BLOCK_CRC)$(MASTER_CAN_FIRST),00)
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error Master drain experiments require first-recording)
endif
endif
SPI_DISABLED_INIT ?= 0
ifneq ($(SPI_DISABLED_INIT),0)
ifneq ($(SPI_DISABLED_INIT),1)
$(error SPI_DISABLED_INIT must be 0 or 1)
endif
ifneq ($(SPI_TX_PRIME),1)
$(error SPI_DISABLED_INIT requires SPI_TX_PRIME=1)
endif
endif
SPI_BOUNDARY_TRACE ?= 0
ifneq ($(SPI_BOUNDARY_TRACE),0)
ifneq ($(SPI_BOUNDARY_TRACE),1)
$(error SPI_BOUNDARY_TRACE must be 0 or 1)
endif
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error SPI_BOUNDARY_TRACE requires first-recording)
endif
ifneq ($(SPI_TX_PRIME),1)
$(error SPI_BOUNDARY_TRACE requires SPI_TX_PRIME=1)
endif
endif
SPI_BENCH_MODE ?= 0
ifneq ($(SPI_BENCH_MODE),0)
ifneq ($(SPI_BENCH_MODE),1)
$(error SPI_BENCH_MODE must be 0 or 1)
endif
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error SPI_BENCH_MODE=1 requires SPI_MEASUREMENT_PROFILE=first-recording)
endif
ifneq ($(SPI_TX_PRIME),1)
$(error SPI_BENCH_MODE=1 requires SPI_TX_PRIME=1)
endif
endif
SPI_TX_PRIME ?= 0
ifneq ($(SPI_TX_PRIME),0)
ifneq ($(SPI_TX_PRIME),1)
$(error SPI_TX_PRIME must be 0 or 1)
endif
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error SPI_TX_PRIME=1 requires SPI_MEASUREMENT_PROFILE=first-recording)
endif
endif
SPI_PHASE_TIMING ?= 0
SPI_QUEUE_TIMING ?= 0
ifeq ($(SPI_QUEUE_TIMING),1)
ifneq ($(SPI_PHASE_TIMING),1)
$(error SPI_QUEUE_TIMING=1 requires SPI_PHASE_TIMING=1)
endif
else ifneq ($(SPI_QUEUE_TIMING),0)
$(error SPI_QUEUE_TIMING must be 0 or 1)
endif
ifeq ($(SPI_PHASE_TIMING),1)
ifneq ($(SPI_MEASUREMENT_PROFILE),first-recording)
$(error SPI_PHASE_TIMING=1 requires SPI_MEASUREMENT_PROFILE=first-recording)
endif
else ifneq ($(SPI_PHASE_TIMING),0)
$(error SPI_PHASE_TIMING must be 0 or 1)
endif
SOURCES := ../src/main.c ../src/master_timing.c ../src/master_sysconfig.c \
    ../../common/protocol/bodaqs_control.c \
    ../../common/protocol/bodaqs_control_exchange.c \
    ../src/master_identity.c \
    ../../common/protocol/bodaqs_master_protocol.c \
    ../../common/protocol/bodaqs_master_service.c \
    ../../common/network/bodaqs_can_network.c \
    ../../common/network/bodaqs_node_inventory.c
OBJECTS := master_timing.obj bodaqs_control.obj bodaqs_control_exchange.obj main.obj master_identity.obj bodaqs_master_protocol.obj \
    bodaqs_master_service.obj bodaqs_can_network.obj \
    bodaqs_node_inventory.obj \
    master_sysconfig.obj $(patsubst %.c,%.obj,$(notdir $(filter-out %/ti_msp_dl_config.c ti_msp_dl_config.c,$(SYSCFG_C_FILES))))

V := @
ifeq ($(VERBOSE),1)
V :=
endif

CFLAGS := -I../include \
    -I../../common/protocol \
    -I../../common/network \
    -I../../common/transport \
    -I. \
    $(addprefix @,$(SYSCFG_OPT_FILES)) \
    -O2 \
    -gdwarf-3 \
    "-I$(MSPM0_SDK_INSTALL_DIR)/source/third_party/CMSIS/Core/Include" \
    "-I$(MSPM0_SDK_INSTALL_DIR)/source" \
    -mcpu=cortex-m0plus \
    -march=thumbv6m \
    -mfloat-abi=soft \
    -mthumb \
    -Wall \
    -Wextra \
    -DBODAQS_CAN_LINK_PROFILE=$(CAN_LINK_DEFINE) \
    -DBODAQS_SPI_MEASUREMENT_V2=$(MEASUREMENT_DEFINE) \
    -DBODAQS_SPI_MEASUREMENT_V3=$(SPI_SAMPLE_UNITS) \
    -DBODAQS_SPI_MEASUREMENT_V4=$(SPI_SAMPLE_WINDOW) \
    -DBODAQS_MASTER_PHASE_TIMING=$(SPI_PHASE_TIMING) \
    -DBODAQS_MASTER_QUEUE_TIMING=$(SPI_QUEUE_TIMING) \
    -DBODAQS_MASTER_BLOCK_CRC=$(MASTER_BLOCK_CRC) \
    -DBODAQS_MASTER_CAN_FIRST=$(MASTER_CAN_FIRST) \
    -DBODAQS_MASTER_BOUNDARY_RESERVE=$(MASTER_BOUNDARY_RESERVE) \
    -DBODAQS_MASTER_SPI_RX_CAPACITY=$(SPI_RX_CAPACITY) \
    -DBODAQS_MASTER_SPI_TX_PRIME=$(SPI_TX_PRIME) \
    -DBODAQS_CAN_SPI_BENCH_MODE=$(SPI_BENCH_MODE) \
    -DBODAQS_SPI_BOUNDARY_TRACE=$(SPI_BOUNDARY_TRACE) \
    -DBODAQS_MASTER_SPI_DISABLED_INIT=$(SPI_DISABLED_INIT) \
    -Werror \
    $(CFLAGS_EXTRA)

LFLAGS := -ldevice.cmd.genlibs \
    "-L$(MSPM0_SDK_INSTALL_DIR)/source" \
    -L. \
    device_linker.cmd \
    spi_buffers.cmd \
    -Wl,--stack_size=$(MASTER_STACK_BYTES) \
    "-Wl,-m,$(NAME).map" \
    -Wl,--rom_model \
    -Wl,--warn_sections \
    "-L$(TICLANG_ARMCOMPILER)/lib" \
    -llibc.a

.PHONY: all clean syscfg

all: $(NAME).out

.INTERMEDIATE: syscfg
$(SYSCFG_FILES): syscfg
	@echo generation complete

syscfg: ../master.syscfg
	@echo Generating configuration files...
	$(V) $(SYSCFG_CMD) --output . $<

define C_RULE
$(basename $(notdir $(1))).obj: $(1) $(SYSCFG_H_FILES)
	@echo Building $$@
	$(V) $(CC) $(CFLAGS) -c $$< -o $$@
endef

$(foreach source,$(SOURCES),$(eval $(call C_RULE,$(source))))
$(foreach source,$(filter-out %/ti_msp_dl_config.c ti_msp_dl_config.c,$(SYSCFG_C_FILES)),$(eval $(call C_RULE,$(source))))

master_sysconfig.obj: ti_msp_dl_config.c ../include/master_spi_initialization.h ../include/master_spi_priming.h

main.obj: ../../common/transport/bodaqs_record_queue.h

$(NAME).out: $(OBJECTS)
	@echo Linking $@
	$(V) $(LNK) -Wl,-u,_c_int00 $(OBJECTS) $(LFLAGS) -o $@

clean:
	@echo Cleaning...
	-$(V) $(RM) $(OBJECTS) $(NAME).out $(NAME).map > $(DEVNULL) 2>&1
	-$(V) $(RM) $(GENERATED_FILES) > $(DEVNULL) 2>&1

main.obj master_identity.obj bodaqs_master_service.obj bodaqs_control.obj bodaqs_control_exchange.obj: ../../common/protocol/bodaqs_control.h ../../common/protocol/bodaqs_control_exchange.h

main.obj bodaqs_master_service.obj master_identity.obj: ../../common/protocol/bodaqs_measurement.h

main.obj bodaqs_master_service.obj: ../../common/protocol/bodaqs_master_service.h ../../common/protocol/bodaqs_fragment_transport.h
main.obj bodaqs_master_service.obj: ../../common/protocol/bodaqs_master_profile.h
main.obj bodaqs_master_service.obj master_identity.obj: ../../common/protocol/bodaqs_crc32_blocks.h

# Profile is a make input, not a generated-code edit. Rebuild its two consumers
# on every invocation so switching back to a previously built profile is safe.
.PHONY: can-link-profile
can-link-profile:
main.obj: can-link-profile ../../common/network/bodaqs_can_link.h ../../common/network/bodaqs_can_link_ti.h
master_identity.obj: can-link-profile ../../common/network/bodaqs_can_link.h ../../common/network/bodaqs_can_link_ti.h

.PHONY: measurement-profile
measurement-profile:
main.obj bodaqs_master_service.obj master_sysconfig.obj: measurement-profile
$(NAME).out: spi_buffers.cmd
