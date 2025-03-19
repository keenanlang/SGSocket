#Makefile at top of application tree
TOP = .
include $(TOP)/configure/CONFIG

DIRS += configure
DIRS += $(wildcard *App)

ifeq ($(BUILD_IOCS), YES)
    DIRS += iocs
    iocs_DEPEND_DIRS = $(filter-out iocs, $(DIRS))
endif

$(foreach dir, $(filter %App, $(DIRS)), \
    $(eval $(dir)_DEPEND_DIRS = configure))

include $(TOP)/configure/RULES_TOP
