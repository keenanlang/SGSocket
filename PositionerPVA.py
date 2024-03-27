#!/APSshare/anaconda3/x86_64/bin/python

import sys
import configparser
import time
import copy
import h5py
import array
import ctypes
import asyncio

from multiprocessing import Manager, Process, Queue, Value, Lock

from pvaccess import *
from epics import caput	

class PositionerServer(PvaServer):
	def __init__(self, config_file="PositionerPVA.cfg"):
		super(PositionerServer, self).__init__()
		
		self.config = configparser.ConfigParser()
		self.config.read(config_file)
		
		self.wait_time = 1.0 / float(self.config["PVA"]["Max-Rate"])
		self.output_file_path = "./output.h5"
				
		self.pva_queue = Queue()
		self.hf5_queue = Queue()
		
		self.pva_process = None
		self.hf5_process = None
		
		self.manager = Manager()
		
		self.status = self.manager.Value(ctypes.c_wchar_p, "Idle")
				
		self.length_multiple = int(self.config["HDF5"]["Resize-By"])
		
		
		self.prefix = self.config["PVA"]["Prefix"]
		
		self.addRecord(
			self.prefix + "reset", 
			PvObject({"value" : INT}), 
			self._reset)
			
		self.addRecord(
			self.prefix + "start", 
			PvObject({"value" : INT}), 
			self._start)
			
		self.addRecord(
			self.prefix + "stop",  
			PvObject({"value" : INT}), 
			self._stop)
			
		self.addRecord(
			self.prefix + "status",
			PvObject({"value" : STRING}, {"value" : "Idle"}))
			
		self.addRecord(
			self.prefix + "outputFile",
			PvObject({"filePath" : STRING, "fileName" : STRING}, 
			         {"filePath" : "./",   "fileName" : "output.h5"}),
			self._update_file)
			
		self.loop = asyncio.get_event_loop()
		self.running = False
		
		
	async def do_updates(self):
		
		while self.running:
			self.writer.write(bytes("sendnumw", "utf-8"))
			await self.writer.drain()
			
			num_words = int(await self.reader.readexactly(10))
			
			#print("SoftGlue has {:d} values buffered".format(num_words))
			
			if num_words < int(self.config["softglue"]["Packet-Size"]):
				#print("SoftGlue has too few values buffered, waiting for more")
				return
			else:
				num_words = int(self.config["softglue"]["Packet-Size"])
				
			print("Reading {:d} values from SoftGlue".format(num_words))
		
			
			self.writer.write(bytes("senddata", "utf-8"))
			await self.writer.drain()

			bytes_data = await self.reader.readexactly(4 * num_words)
			int_data = array.array('I')
			
			for i in range(num_words):
				int_data.append(int.from_bytes(bytes_data[4*i:4*i+4], byteorder='little'))
			
			index = 0
			
			while (index < 10000):
				if not int_data[index] & 0x80000000:
					index += 1
					continue
						
				if (int_data[4] & 0xC0000000 == 0xC0000000):
					print("Found 24 word event {:08x} at {:d}".format(int_data[index], index))
					index += 24
					continue
				
						
				int_data[index] &= ~0x80000000
				self.hf5_queue.put(copy.copy(int_data[index:index+8]))
				#self.pva_queue.append(copy.copy(int_data[index:index+8]))
					
				index += 8
				
			yield
			
	async def run_updates(self):
		ip = self.config["softglue"]["IP"]
		self.reader, self.writer = await asyncio.open_connection(ip, 8888)
				
		print("Connected to SoftGlue")
		
		while True:
			async for ignore in self.do_updates():
				pass
			await asyncio.sleep(self.wait_time)
		
	def setStatus(self, val):
		self.status.value = val
		self.update(self.prefix + "status", PvObject({"value" : STRING}, {"value" : val}))
			
		
	def poll(self):
		self.loop.run_until_complete(self.run_updates())
		
		
	def _reset(self, data):
		print("Writing to: ", self.config["softglue"]["Prefix"] + "1acquireDma.F")
		caput(self.config["softglue"]["Prefix"] + "1acquireDma.F", 1)
		data["value"] = 0
		
		
	def _start(self, data):
		self._reset(data)
		self.setStatus("Acquiring")
		
		print("Starting Communication")
		
		self.hf5_process = Process(target=self.write_h5, args=(self.hf5_queue, self.status))
		self.hf5_process.start()
		
		self.running = True
		
		data["value"] = 0
		
		
	def _stop(self, data):
		print("Stopping Communication")
		self.running = False
		
		self.setStatus("Stopping")
		
		self.hf5_process.join()
		
		#with self.status.get_lock():
		self.setStatus("Idle")
		
		data["value"] = 0
		
		
	def _update_file(self, data):
		if not data["filePath"]["value"].endswith("/"):
			data["filePath"]["value"] += "/"
		
		self.output_file_path = data["filePath"] + data["fileName"]
		
	
	def write_h5(self, queue, status):
		
		index = 0
		check_length = self.length_multiple
		
		output_file = h5py.File(self.output_file_path, 'w')
		dsets = {}
		
		for num, label in self.config["events.8word"].items():
			dsets[label] = output_file.create_dataset(self.config["HDF5"]["dataset"] + "/" + label, (self.length_multiple,), 'i', maxshape=(None,), chunks=(self.length_multiple/10,))
			
		while True:
			if queue.empty():
				if status.value != "Acquiring":
					break
				
				time.sleep(self.wait_time)
				continue
				
			packet = queue.get()
			
			for i in range(8):
				eventlabel = self.config["events.8word"][str(i+1)]
				dsets[eventlabel][index:index+1] = packet[i]
				
			index += 1
			
			if (index >= check_length):
				check_length += self.length_multiple
				
				for item in dsets.values():
					item.resize((check_length,))
					
		output_file[self.config["HDF5"]["dataset"]].attrs["numEvents"] = index
					
		output_file.flush()
		output_file.close()
			
				
		
				
if __name__ == '__main__':
	if len(sys.argv) == 2:
		my_handler = PositionerServer(sys.argv[1])
		my_handler.poll()
	else:
		my_handler = PositionerServer()
		my_handler.poll()
