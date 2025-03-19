#ifndef INC_SGSOCKET_H
#define INC_SGSOCKET_H

#include <vector>
#include <deque>

#include "osiSock.h"
#include "osiUnistd.h"

#include "epicsEvent.h"

#include "ADDriver.h"
#include "epicsExport.h"


static const double SHORT_TIME = 0.000025;
static const double LONG_TIME  = 5.0;

static const int PACKET_SIZE = 100000;

class epicsShareClass SGSocket: public ADDriver
{
protected:
	virtual void init();
	virtual bool tryConnect();
	virtual bool tryDisconnect();
	
	virtual void pullSettings();
	virtual void pushSettings();
	
	
public:	
	SGSocket(const char* portName, const char* ipAddr, int maxOutputs);

	void     pushFrame(NDArray* frame);
	NDArray* pullFrame();
	
	void incrementValue(int param);
   	void decrementValue(int param);
	
	void collectThread();
	void exportFrameThread();
	void tryConnectThread();
	void tryDisconnectThread();
	
	virtual asynStatus writeInt32(asynUser *pasynUser, epicsInt32 value);
	virtual asynStatus writeFloat64Array(asynUser *pasynUser, epicsFloat64* value, size_t nelm);
	virtual asynStatus writeOctet(asynUser *pasynUser, const char *value, size_t nChars, size_t *nActual);
	
private:
	void connect();
	void disconnect();
	
	bool connected;
	
	std::deque<NDArray*> export_queue;
	std::vector<epicsFloat64> output_matrix;
	
	epicsMutex* dequeLock;
	
	epicsEvent* stopAcquireEvent;
	
	osiSockAddr addr;
	SOCKET socket;
	
	NDArray* pImage = NULL;
	
	int outputs_used;
	
	int SGOutputMatrix;
	int SGOutputNames;
};

#endif
