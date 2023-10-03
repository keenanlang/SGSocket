#!/APSshare/anaconda3/x86_64/bin/python

import json
import time
import numpy
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
def addAllEvents(output, data):
	last_data = output.get()
	temp_data = {}
	
	for axis in data.keys():
		last_event = -1
		temp_data[axis] = {}
		
		if len(last_data[axis]['eventIDs']):
			last_event = last_data[axis]['eventIDs'][-1]
			
		temp_data[axis]['numEvents'] = len(data[axis])
		temp_data[axis]['eventIDs'] = [ int(x) for x in range(int(last_event + 1), int(last_event + len(data[axis]) + 1)) ]
		temp_data[axis]['positions'] = data[axis]
		
	output.set(temp_data)

AXIS_TEMPLATE = {
'numEvents'    : ULONG, 
'eventIDs'  : [ ULONG ],
'positions' : [ LONG ]
}

# Having a PVA output per different axis
#pv1 = PvObject(AXIS_TEMPLATE)
#pv2 = PvObject(AXIS_TEMPLATE)
#pv3 = PvObject(AXIS_TEMPLATE)

async def get_data():
	config_data = None
	
	with open("PositionerConfig.json") as config:
		config_data = json.load(config)
		
	pv_template = {}
	
	for axis in config_data.keys():
		pv_template[axis] = AXIS_TEMPLATE
		
	pv1 = PvObject(pv_template)
	
	# For example, we'll only serve a single axis
	xServer = PvaServer('Positions', pv1)
		
	reader, writer = await asyncio.open_connection('127.0.0.1', 7000)
	
	print("Connected")
	
	while True:
		data = await reader.read(6496)
		
		print("Read data")
		
		if not data:
			print("Closing Connection")
			writer.close()
			await writer.wait_closed()
			return		
			
		vals = pickle.loads(data) 
		
		test = {}
		my_func = numpy.vectorize(lambda x,y : x+y)
		
		
		for axis in config_data.keys():
			my_func = numpy.vectorize(lambda A,B : eval(config_data[axis]["calc"]))
			
			streams = config_data[axis]["streams"]
			
			stream1 = vals[streams[0]]
			stream2 = vals[streams[1]]
			
			out_data = my_func(stream1, stream2)
			test[axis] = out_data
			
		addAllEvents(pv1, test)

asyncio.run(get_data())
