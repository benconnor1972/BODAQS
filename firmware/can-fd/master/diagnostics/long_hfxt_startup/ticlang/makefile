ifndef MSPM0_SDK_INSTALL_DIR
$(error Set MSPM0_SDK_INSTALL_DIR to the MSPM0 SDK directory)
endif

include $(MSPM0_SDK_INSTALL_DIR)/imports.mak

CC := "$(TICLANG_ARMCOMPILER)/bin/tiarmclang"
LNK := "$(TICLANG_ARMCOMPILER)/bin/tiarmclang"
SYSCFG_CMD := $(SYSCONFIG_TOOL) --compiler ticlang --product $(MSPM0_SDK_INSTALL_DIR)/.metadata/product.json
SYSCFG_FILES := $(shell $(SYSCFG_CMD) --listGeneratedFiles --listReferencedFiles --output . ../long_hfxt_startup_test.syscfg)
SYSCFG_C_FILES := $(filter %.c,$(SYSCFG_FILES))
SYSCFG_H_FILES := $(filter %.h,$(SYSCFG_FILES))
SYSCFG_OPT_FILES := $(filter %.opt,$(SYSCFG_FILES))
GENERATED_FILES := device.opt device.cmd.genlibs device_linker.cmd \
    ti_msp_dl_config.c ti_msp_dl_config.h Event.dot Graph.dot

NAME := bodaqs_can_master_long_hfxt_startup_test
SOURCES := ../main.c
OBJECTS := main.obj $(patsubst %.c,%.obj,$(notdir $(SYSCFG_C_FILES)))

V := @
ifeq ($(VERBOSE),1)
V :=
endif

CFLAGS := -I. \
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
    -Werror

LFLAGS := -ldevice.cmd.genlibs \
    "-L$(MSPM0_SDK_INSTALL_DIR)/source" \
    -L. \
    device_linker.cmd \
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

syscfg: ../long_hfxt_startup_test.syscfg
	@echo Generating configuration files...
	$(V) $(SYSCFG_CMD) --output . $<

define C_RULE
$(basename $(notdir $(1))).obj: $(1) $(SYSCFG_H_FILES)
	@echo Building $$@
	$(V) $(CC) $(CFLAGS) -c $$< -o $$@
endef

$(foreach source,$(SOURCES),$(eval $(call C_RULE,$(source))))
$(foreach source,$(SYSCFG_C_FILES),$(eval $(call C_RULE,$(source))))

$(NAME).out: $(OBJECTS)
	@echo Linking $@
	$(V) $(LNK) -Wl,-u,_c_int00 $(OBJECTS) $(LFLAGS) -o $@

clean:
	@echo Cleaning...
	-$(V) $(RM) $(OBJECTS) $(NAME).out $(NAME).map > $(DEVNULL) 2>&1
	-$(V) $(RM) $(GENERATED_FILES) > $(DEVNULL) 2>&1

