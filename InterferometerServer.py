#!/usr/bin/env python

import time
import pickle
import asyncio


async def handle_connection(reader, writer):
	
	UPDATE_FREQUENCY_HZ = 10

	# Number of pieces of data we will send every update
	NUM_SAMPLES = 1_024

	# Use a fixed frame size to make communication easier on both sides of the socket
	# Need 8bytes per sample, plus some buffer space for python pickling convention
	FRAME_SIZE = (NUM_SAMPLES * 8) + 4_096

	# Fake an amount of data to be sent across the socket
	# This will eventually be received from the interferometer and have some metadata
	output_data = [x for x in range(NUM_SAMPLES)]

	
	print("Connection Received")
	
	# On a new connection, just start sending frames until something goes wrong

	while True:
		print("Sending Data")
		
		# Build a '\0' filled frame
		store = bytearray(FRAME_SIZE)
		
		
		# Then copy the pickled data into the beginning
		pickled = pickle.dumps(output_data)
		store[0 : len(pickled)] = pickled
		
		# Send it out
		writer.write(store)
		await writer.drain()
		
		
		# Rate limiting
		time.sleep(1.0 / UPDATE_FREQUENCY_HZ)


async def main():	
	print("Starting Server on port 7000")
	server = await asyncio.start_server( handle_connection, '127.0.0.1', 7000 )

	print("Waiting for connections...")
	async with server:
		await server.serve_forever()

		
asyncio.run(main())
