#Makefile at top of application tree
TOP = .
include $(TOP)/configure/CONFIG

DIRS += configure iocBoot
DIRS += $(wildcard *App)

iocboot_DEPEND_DIRS = $(wildcard *App)

$(foreach dir, $(filter %App, $(DIRS)), \
    $(eval $(dir)_DEPEND_DIRS = configure))

include $(TOP)/configure/RULES_TOP
