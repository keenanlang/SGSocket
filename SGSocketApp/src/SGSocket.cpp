#include "SGSocket.h"

#include <iocsh.h>
#include <cstring>

#include <random>

static void collect_thread_callback(void *drvPvt)      { ((SGSocket*) drvPvt)->collectThread(); }
static void export_thread_callback(void *drvPvt)       { ((SGSocket*) drvPvt)->exportFrameThread(); }
static void connect_thread_callback(void *drvPvt)      { ((SGSocket*) drvPvt)->tryConnectThread(); }
static void disconnect_thread_callback(void *drvPvt)   { ((SGSocket*) drvPvt)->tryDisconnectThread(); }

SGSocket::SGSocket(const char* portName, const char* addr, int maxOutputs) :
	ADDriver(portName, maxOutputs, 0, 0, 0, asynEnumMask | asynFloat64ArrayMask, asynEnumMask | asynFloat64ArrayMask, ASYN_CANBLOCK | ASYN_MULTIDEVICE, 1, 0, 0)
{
	this->dequeLock = new epicsMutex();
	this->connected = false;
	this->output_matrix.reserve(24 * maxOutputs);
	
	this->stopAcquireEvent = new epicsEvent();
	
	aToIPAddr(addr, 8888, &this->addr.ia);
		
	setIntegerParam(ADStatus, ADStatusDisconnected);
	
	this->init();
	
	callParamCallbacks();
	
	this->connect();
}

void SGSocket::init()          
{ 	
	this->outputs_used = 0;
	createParam("SG_OUT_MATRIX", asynParamFloat64Array, &SGOutputMatrix);
	createParam("SG_OUT_NAMES",  asynParamOctet,        &SGOutputNames);
}


void SGSocket::pullSettings()          { }
void SGSocket::pushSettings()          { }

bool SGSocket::tryConnect()    
{	
	this->socket = epicsSocketCreate(this->addr.sa.sa_family, SOCK_STREAM, 0);
	
	if (this->socket == -1)
	{
		printf("Error creating socket\n");
		return false;
	}
	
	if (::connect(this->socket, (struct sockaddr*) &this->addr.sa, sizeof(this->addr.sa)))
	{
		printf("Error connecting to addr: %s\n", this->addr);
		return false;
	}
	
	return true; 
}


bool SGSocket::tryDisconnect() 
{ 
	close(this->socket);
	return true; 
}



void SGSocket::incrementValue(int param)
{
	int val;
	getIntegerParam(param, &val);
	val += 1;
	setIntegerParam(param, val);
}

void SGSocket::decrementValue(int param)
{
	int val;
	getIntegerParam(param, &val);
	val -= 1;
	setIntegerParam(param, val);
}


void SGSocket::pushFrame(NDArray* frame)
{
	dequeLock->lock();
		this->export_queue.push_back(frame); 
	dequeLock->unlock();
}

NDArray* SGSocket::pullFrame()
{
	NDArray* output = NULL;
	// Pull from available frames
	dequeLock->lock();
		output = export_queue.front();
		export_queue.pop_front();
	dequeLock->unlock();
		
	return output;
}

void SGSocket::connect()
{
	this->lock();
	
	int status;
	getIntegerParam(ADStatus, &status);
	
	if (status == ADStatusDisconnected)
	{
		setIntegerParam(ADStatus, ADStatusInitializing);
		callParamCallbacks();
		
		epicsThreadCreate("SGSocket::tryConnectThread()",
						epicsThreadPriorityLow,
						epicsThreadGetStackSize(epicsThreadStackMedium),
						(EPICSTHREADFUNC)::connect_thread_callback,
						this);
	}
					
	this->unlock();
}

void SGSocket::disconnect()
{
	this->lock();
	
	int status;
	getIntegerParam(ADStatus, &status);
	
	if (status == ADStatusIdle)
	{
		setIntegerParam(ADStatus, ADStatusWaiting);
		callParamCallbacks();
		
		epicsThreadCreate("SGSocket::tryDisconnectThread()",
						epicsThreadPriorityLow,
						epicsThreadGetStackSize(epicsThreadStackMedium),
						(EPICSTHREADFUNC)::disconnect_thread_callback,
						this);
	}
	
	this->unlock();
}
	
void SGSocket::tryDisconnectThread()
{
	while (this->connected)
	{
		if(this->tryDisconnect())
		{
			this->lock();
				this->connected = false;
				setIntegerParam(ADStatus, ADStatusDisconnected);
				callParamCallbacks();
			this->unlock();
		}
		else
		{
			printf("Could not disconnect, will attempt again\n");
			epicsThreadSleep(LONG_TIME);
		}
	}
}

void SGSocket::tryConnectThread()
{
	while (! this->connected)
	{
		if (this->tryConnect())
		{
			this->lock();
				this->pullSettings();
				this->connected = true;
				setIntegerParam(ADStatus, ADStatusIdle);
				callParamCallbacks();
			this->unlock();
			
			epicsThreadCreate("SGSocket::ExportThread()",
						epicsThreadPriorityLow,
						epicsThreadGetStackSize(epicsThreadStackMedium),
						(EPICSTHREADFUNC)::export_thread_callback,
						this);
		}
		else
		{
			printf("Could not connect, will attempt again\n");
			epicsThreadSleep(LONG_TIME);
		}
	}
}

void SGSocket::exportFrameThread()
{
	while(this->connected)
	{
		while (export_queue.empty())    { epicsThreadSleep(SHORT_TIME); }
		
		if (this->pImage)    { this->pImage->release(); }
		
		this->pImage = pullFrame();
		
		NDArrayInfo info;
		this->pImage->getInfo(&info);
		
		this->lock();
			incrementValue(NDArrayCounter);
			this->setIntegerParam(NDArraySize, info.totalBytes);
		
			int arrayCallbacks;
			getIntegerParam(NDArrayCallbacks, &arrayCallbacks);
		
			this->callParamCallbacks();
			if (arrayCallbacks)    { doCallbacksGenericPointer(this->pImage, NDArrayData, 0); }
		this->unlock();
	}
}

void SGSocket::collectThread()
{
	size_t imagedims[1] = { (size_t) 24 };
		
	std::vector<int> the_data;
	the_data.reserve(24);
	
	int index = 0;
	int event_size = 0;
	bool copying_data = false;
	
	while (true)
	{
		if( this->stopAcquireEvent->wait(4*SHORT_TIME) )    { break; }
		
		// Get number of words available from SoftGlue
		const char* message = "sendnumw";
		send(this->socket, (char*)message, strlen(message), 0);
		char check[11] = {0};
		recv(this->socket, check, 10, 0);
		int numw = atoi(check);
		
		printf("numw: %d\n", numw);
		
		if (numw < PACKET_SIZE)    { continue; }
		
		const char* get_data = "senddata";
		send(this->socket, (char*)get_data, strlen(get_data), 0);
		
		char output[4*PACKET_SIZE] = {0};
		recv(this->socket, output, 4*PACKET_SIZE, MSG_WAITALL);
		
		int* as_ints = (int*) output;
		
		for (int offset = 0; offset < PACKET_SIZE; offset += 1)
		{
			if (!copying_data && !(as_ints[offset] & 0x80000000))    { continue; }
		
			if (as_ints[offset] & 0xC0000000 == 0xC0000000)
			{
				printf("Found 24 word event\n");
				event_size = 24;
				copying_data = true;
			}
			else if (as_ints[offset] & 0x80000000 == 0x80000000)
			{
				event_size = 8;
				copying_data = true;
			}
			
			if (copying_data)
			{
				the_data[index] = as_ints[offset] << 2 >> 2;
				index += 1;
				
				if (index == event_size)
				{
					index = 0;
					NDArray* new_frame = pNDArrayPool->alloc(1, imagedims, NDInt32, 0, NULL);
					updateTimeStamps(new_frame);
					
					int* output = (int*) new_frame->pData;
					
					the_data[0] = index;
					output[0] = index;
					
					for (int data = 1; data < 24; data += 1)    { output[data] = the_data[data]; }
					
					for (int index = 0; index < this->outputs_used; index += 1)
					{
						epicsFloat64 product = 0.0;
					
						for (int element = 0; element < 24; element += 1)
						{
							int offset = index * 24 + element;
							product += the_data[element] * this->output_matrix[offset];
						}
						
						std::string output_name;
						getStringParam(index, SGOutputNames, output_name);
						
						new_frame->pAttributeList->add(output_name.c_str(), "", NDAttrFloat64, &product);
					}
					
					this->pushFrame(new_frame);
				}
			}
		}
	}
	
	this->setIntegerParam(ADAcquire, 0);
	this->setIntegerParam(ADStatus, ADStatusIdle);
	this->callParamCallbacks();
}

asynStatus SGSocket::writeOctet(asynUser *pasynuser, const char *value, size_t nChars, size_t *nActual)
{
	int addr;
	int function;
	const char* paramName;
	
	int status = parseAsynUser(pasynuser, &function, &addr, &paramName);
	
	if (function == SGOutputNames)
	{
		printf("[%d] Named: %s\n", addr, value);
	
		if (addr + 1 > this->outputs_used)    { this->outputs_used = addr + 1; }
	}
	
	return ADDriver::writeOctet(pasynuser, value, nChars, nActual);
}

asynStatus SGSocket::writeFloat64Array(asynUser* pasynuser, epicsFloat64* value, size_t nelm)
{
	int addr;
	int function;
	const char* paramName;
	
	int status = parseAsynUser(pasynuser, &function, &addr, &paramName);
	
	if (function == SGOutputMatrix)
	{
		for (int index = 0; index < nelm; index += 1)
		{
			int offset = addr * 24 + index;
		
			this->output_matrix[offset] = value[index];
		
			printf("output[%d] = %f\n", offset, value[index]);
		}
	}
	
	ADDriver::writeFloat64Array(pasynuser, value, nelm);
	
	callParamCallbacks();
	return (asynStatus) asynSuccess;
}

asynStatus SGSocket::writeInt32(asynUser* pasynuser, epicsInt32 value)
{
	int addr;
	int function;
	const char* paramName;
	
	int status = parseAsynUser(pasynuser, &function, &addr, &paramName);
	
	int adStatus;
	
	getIntegerParam(ADStatus, &adStatus);
	
	setIntegerParam(addr, function, value);
	
	if (function == ADAcquire)
	{
		if (value && (adStatus == ADStatusIdle))
		{
			this->setIntegerParam(ADStatus, ADStatusAcquire);
			this->callParamCallbacks();
			epicsThreadCreate("SGSocket::CollectThread()",
						epicsThreadPriorityLow,
						epicsThreadGetStackSize(epicsThreadStackMedium),
						(EPICSTHREADFUNC)::collect_thread_callback,
						this);
		}
		else if (!value && (adStatus == ADAcquire))
		{
			this->stopAcquireEvent->trigger();
		}
	}
	else
	{
		status = ADDriver::writeInt32(pasynuser, value);
	}
	
	callParamCallbacks();
	return (asynStatus) status;
}

extern "C" int SGSocketConfig(const char* portName, const char* addr, int maxOutputs)
{
	new SGSocket(portName, addr, maxOutputs);
	return asynSuccess;
}


// Code for iocsh registration
static const iocshArg SGSocketConfigArg0 = {"Port name",   iocshArgString};
static const iocshArg SGSocketConfigArg1 = {"IP Addr",     iocshArgString};
static const iocshArg SGSocketConfigArg2 = {"Max Outputs", iocshArgInt};
static const iocshArg * const SGSocketConfigArgs[] = {
    &SGSocketConfigArg0,
    &SGSocketConfigArg1,
    &SGSocketConfigArg2};

static const iocshFuncDef configSGSocket = {"SGSocketConfig", 3, SGSocketConfigArgs};

static void configSGSocketCallFunc(const iocshArgBuf *args)
{
    SGSocketConfig(args[0].sval, args[1].sval, args[2].ival);
}

static void SGSocketRegister(void)
{
    iocshRegister(&configSGSocket, configSGSocketCallFunc);
}

extern "C" {
    epicsExportRegistrar(SGSocketRegister);
}
