#!/APSshare/anaconda3/x86_64/bin/python3

import json
import time
import epics
import pickle
import asyncio
import numpy


async def handle_connection(reader, writer, STREAM_DATA):
	
	print("Connection Received")

	UPDATE_FREQUENCY_HZ = 10

	# Number of pieces of data we will send every update
	NUM_SAMPLES = 300

	# Use a fixed frame size to make communication easier on both sides of the socket
	# Need 8bytes per sample, plus some buffer space for python pickling convention
	FRAME_SIZE = (NUM_SAMPLES * 8) + 4_096

	# Fake an amount of data to be sent across the socket
	# This will eventually be received from the interferometer and have some metadata
	output_data = []
	
	# On a new connection, just start sending frames until something goes wrong

	NUM_VALS = 0
	
	while True:
		vals = epics.caget_many(STREAM_DATA)
		
		NUM_VALS += len(vals)
		
		output_data.append(vals)
		
		print("Loading data... {:d} / {:d}\r".format(NUM_VALS, NUM_SAMPLES), end='')
		
		
		if NUM_VALS >= NUM_SAMPLES:			
			# Build a '\0' filled frame
			store = bytearray(FRAME_SIZE)
			
			# Then copy the pickled data into the beginning
			pickled = pickle.dumps(numpy.transpose(output_data))
			store[0 : len(pickled)] = pickled
			
			print("")
			print("Sending Data")
		
			# # Send it out
			writer.write(store)
			await writer.drain()
			
			output_data = []
			NUM_VALS = 0
			
		else:
			# Rate limiting
			time.sleep(1.0 / UPDATE_FREQUENCY_HZ)
		


async def main():
	STREAM_DATA = []
	
	with open("InterferometerConfig.json") as config:
		STREAM_DATA = json.load(config)
		NUM_STREAMS = len(STREAM_DATA)
	
	
	print("Starting Server on port 7000")
	server = await asyncio.start_server( lambda x, y: handle_connection(x, y, STREAM_DATA), '127.0.0.1', 7000 )

	print("Waiting for connections...")
	async with server:
		await server.serve_forever()

		
asyncio.run(main())


	
