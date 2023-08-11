#!/APSshare/anaconda3/x86_64/bin/python

import time
import socket
import random
import pickle
import asyncio
from pvaccess import *

POSITION = 10.0


# Adding fake data, just do a random walk around a target value
def addEvent(output, next_ID):
	global POSITION
	
	output['numEvents'] += 1
	
	POSITION += ((random.random() - 0.5) / 10.0)
	
	output['positions'].append(POSITION)
	output['eventIDs'].append(int(next_ID))

	
# Buffering 1,000 events per update
def addAllEvents(output):
	data = output.get()
	
	last_event = 0
	
	if len(data['eventIDs']):
		last_event = data['eventIDs'][-1]
		
	data['numEvents'] = 0
	data['eventIDs'] = []
	data['positions'] = []
	
	
	for index in range(1000):
		last_event += 1
		addEvent(data, last_event)
		
	output.set(data)
	

AXIS_TEMPLATE = {
'numEvents'    : ULONG, 
'eventIDs'  : [ ULONG  ],
'positions' : [ DOUBLE ]
}

# Having a PVA output per different axis
pv1 = PvObject(AXIS_TEMPLATE)
pv2 = PvObject(AXIS_TEMPLATE)
pv3 = PvObject(AXIS_TEMPLATE)


# For example, we'll only serve a single axis
xServer = PvaServer('x_axis', pv1)



async def get_data():	
	reader, writer = await asyncio.open_connection('127.0.0.1', 7000)
	
	print("Connected")
	
	while True:
		data = await reader.read(12288)
		
		print("Read data")
		
		if not data:
			print("Closing Connection")
			writer.close()
			await writer.wait_closed()
			return		
			
		addAllEvents(pv1)

asyncio.run(get_data())
