TOP=../..

include $(TOP)/configure/CONFIG
#----------------------------------------
#  ADD MACRO DEFINITIONS AFTER THIS LINE
#=============================

#=============================
# build an ioc application for testing

PROD_IOC = moduleApp

DBD += module.dbd

module_DBD += base.dbd
module_DBD += $(MODULE_IOC_DBDS)

# <name>_registerRecordDeviceDriver.cpp will be created from <name>.dbd
moduleApp_SRCS_DEFAULT += module_registerRecordDeviceDriver.cpp
moduleApp_SRCS_DEFAULT += main.cpp
moduleApp_SRCS_vxWorks += -nil-

#The following adds support from base/src/vxWorks
asApp_OBJS_vxWorks += $(EPICS_BASE_BIN)/vxComLibrary


moduleApp_LIBS := $(MODULE_IOC_LIBS) $(EPICS_BASE_IOC_LIBS)

#===========================

include $(TOP)/configure/RULES
#----------------------------------------
#  ADD RULES AFTER THIS LINE
