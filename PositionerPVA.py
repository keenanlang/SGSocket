#!/APSshare/anaconda3/x86_64/bin/python

import sys
import configparser
import time
import copy
import h5py
import array
import numpy
import ctypes
import asyncio

from multiprocessing import Manager, Process, Queue, Value, Lock

from pvaccess import *
from epics import caput	

VERSION = "0.1.3"

LOG_LEVEL_DEBUG = 10
LOG_LEVEL_FLOW  = 5
LOG_LEVEL_ERR   = 1
LOG_LEVEL_ALL   = 0

class PositionerServer(PvaServer):
	def __init__(self, config_file="PositionerPVA.cfg"):
		super(PositionerServer, self).__init__()
		
		self.config = configparser.ConfigParser()
		self.config.read(config_file)
		
		self.wait_time = 1.0 / float(self.config["PVA"]["Max-Rate"])
		
		self.manager = Manager()
		
		self.pva_queue = self.manager.Queue()
		self.hf5_queue = Queue()
		
		self.pva_process = None
		self.hf5_process = None
		
		self.status = self.manager.Value(ctypes.c_wchar_p, "Idle")
		self.test = False
				
		self.length_multiple = int(self.config["HDF5"]["Resize-By"])
		
		self.prefix = self.config["PVA"]["Prefix"]
				
		inc = self.config["HDF5"].get("AutoIncrement", "False")
		inc = (inc == "True" or inc == "true")
		
		file = self.config["HDF5"].get("DefaultFile", "./")
		path = self.config["HDF5"].get("DefaultPath", "output.h5")
		
		self.output_file_path = path + file
		
		self.pvs = {
			"reset"         : PvObject({"value" : INT}),
			"start"         : PvObject({"value" : INT}),
			"stop"          : PvObject({"value" : INT}),
			"status"        : PvObject({"value" : STRING},  {"value" : "Idle"}),
			"autoIncrement" : PvObject({"value" : BOOLEAN}, {"value" : inc}),
			"fileNumber"    : PvObject({"value": INT},      {"value" : 0}),
			
			"outputFile"    : PvObject({"filePath" : STRING, "fileName" : STRING}, 
			                           {"filePath" : path,   "fileName" : file}),
			
			"about"         : PvObject({"version" : STRING}, {"version" : VERSION}),
			
			"debug"         : PvObject({"logLevel" : INT, "testParse" : INT},
			                           {"logLevel" : 0,   "testParse" : 0}),
		}
			
		for name, pv in self.pvs.items():
			if hasattr(self, "_" + name):
				self.addRecord(self.prefix + name, pv, getattr(self, "_" + name))
			else:
				self.addRecord(self.prefix + name, pv)
			
		self.loop = asyncio.get_event_loop()
		self.running = False
		
	def log(self, level, info):
		if self.pvs["debug"]["logLevel"] >= level:
			print(info)
		
	async def get_num_words(self):
		self.log(LOG_LEVEL_FLOW, "Getting number of words available from SoftGlue")
		
		self.writer.write(bytes("sendnumw", "utf-8"))
		await self.writer.drain()
		
		output = int(await self.reader.readexactly(10))
		
		self.log(LOG_LEVEL_FLOW, "SoftGlue reports having {:d} words".format(output))
		
		return output
		
	async def get_packet(self):
		num_words = await self.get_num_words()
			
		if num_words < int(self.config["softglue"]["Packet-Size"]):
			return
		else:
			num_words = int(self.config["softglue"]["Packet-Size"])
		
		self.log(LOG_LEVEL_FLOW, "Reading {:d} values from SoftGlue".format(num_words))
			
		self.writer.write(bytes("senddata", "utf-8"))
		await self.writer.drain()

		int_data = numpy.frombuffer(await self.reader.readexactly(4 * num_words), dtype="<u4").copy()
		int_data.flags.writeable = True
		
		self.log(LOG_LEVEL_FLOW, "Received packet from SoftGlue")
		
		return int_data
		
		
	async def do_updates(self):
		while self.running:
			int_data = await self.get_packet()
			
			self.hf5_queue.put(int_data)
			self.pva_queue.put(int_data)
				
			yield
			
		if self.test:
			int_data = await self.get_packet()
		
			offset = 0
			index = 0
			
			while (offset < int(self.config["softglue"]["Packet-Size"])):
				if not int_data[offset] & 0x80000000:
					offset += 1
					continue
						
				if (int_data[offset] & 0xC0000000 == 0xC0000000):
					print("Found 24 word event {:08x} at {:d}".format(int_data[offset], offset))
					offset += 24
					continue
				
				int_data[offset] &= ~0x80000000
				print("Found 8 word event {:08x} at {:d}".format(int_data[offset], offset))
					
				offset += 8
				index += 1
				
			self.test = False
			
	async def run_updates(self):
		ip = self.config["softglue"]["IP"]
		
		self.log(LOG_LEVEL_FLOW, "Connecting to SoftGlue at {:s}:{:d}".format(ip, 8888))
		
		self.reader, self.writer = await asyncio.open_connection(ip, 8888)
		
		self.log(LOG_LEVEL_FLOW, "Connected to SoftGlue")
		
		self.log(LOG_LEVEL_ALL, "Ready to run")
		
		while True:
			async for ignore in self.do_updates():
				pass
			await asyncio.sleep(self.wait_time)
		
			
	def setStatus(self, val):
		self.status.value = val
		self.pvs["status"] = val
		
	def poll(self):
		self.loop.run_until_complete(self.run_updates())
		
	def _debug(self, data):
		if data["testParse"] and not self.running:
			self.test = True
				
		data["testParse"] = 0
		
		
	def _reset(self, data):
		self.log(LOG_LEVEL_FLOW, "Writing to: ", self.config["softglue"]["Prefix"] + "1acquireDma.F")
		caput(self.config["softglue"]["Prefix"] + "1acquireDma.F", 1)
		time.sleep(1.0)
		data["value"] = 0
		
		
	def _start(self, data):
		self._reset(data)
		self.setStatus("Acquiring")
		
		self.log(LOG_LEVEL_ALL, "Starting Communication")
		
		self.hf5_process = Process(target=self.write_h5, args=(self.hf5_queue, self.status))
		self.pva_process = Process(target=self.output_pva, args=(self.pva_queue, self.status))
		self.hf5_process.start()
		self.pva_process.start()
		
		self.running = True
		
		data["value"] = 0
		
		
	def _stop(self, data):
		self.log(LOG_LEVEL_ALL, "Stopping Communication")
		self.running = False
		
		self.setStatus("Stopping")
		
		self.hf5_process.join()
		self.pva_process.join()
		
		self.setStatus("Idle")
		
		data["value"] = 0
		
		
	def _outputFile(self, data):
		if not data["filePath"].endswith("/"):
			data["filePath"] += "/"
		
		self.output_file_path = data["filePath"] + data["fileName"]
		
	
	def write_h5(self, queue, status):
		index = 0
		check_length = self.length_multiple
		
		output_file = self.output_file_path
		
		if self.pvs["autoIncrement"]["value"] == True:
			output_file = self.output_file_path + "_" + str(self.pvs["fileNumber"]["value"])
			self.pvs["fileNumber"]["value"] += 1
		
		output_file = h5py.File(output_file, 'w')
		dsets = {}
		
		for num, label in self.config["events.8word"].items():
			dsets[label] = output_file.create_dataset(self.config["HDF5"]["dataset"] + "/" + label, (self.length_multiple,), 'i', maxshape=(None,), chunks=(self.length_multiple/10,))
			
		while True:
			if queue.empty():
				if status.value != "Acquiring":
					break
				
				time.sleep(self.wait_time)
				continue
				
			transfer = queue.get()
			
			offset = 0
			
			while (offset < int(self.config["softglue"]["Packet-Size"])):
				if not transfer[offset] & 0x80000000:
					offset += 1
					continue
						
				if (transfer[offset] & 0xC0000000 == 0xC0000000):
					self.log(LOG_LEVEL_DEBUG, "Found 24 word event {:08x} at {:d}".format(transfer[offset], offset))
					offset += 24
					continue
				
				transfer[offset] &= ~0x80000000
				
				for i in range(8):
					eventlabel = self.config["events.8word"][str(i+1)]
					dsets[eventlabel][index:index+1] = transfer[offset+i]
					
				offset += 8
				index += 1
			
				if (index >= check_length):
					check_length += self.length_multiple
				
					for item in dsets.values():
						item.resize((check_length,))
					
		output_file[self.config["HDF5"]["dataset"]].attrs["numEvents"] = index
					
		output_file.flush()
		output_file.close()
		
		
		
	def output_pva(self, queue, status):
		pv_template = {"numEvents" : LONG, "streams" : [{ "name" : STRING, "events" : [ ULONG ]}]}
		pv_initial  = {"numEvents" : 0,    "streams" : []}
		
		for num, label in self.config["events.8word"].items():
			pv_initial["streams"].append({"name" : label, "events" : [] })
			
			
		pvstream = PvObject(pv_template, pv_initial)			
		server = PvaServer(self.config["PVA"]["Prefix"] + self.config["PVA"]["PV"], pvstream)
		
		while True:
			if queue.empty():
				if status.value != "Acquiring":
					break
				
				time.sleep(self.wait_time)
				continue
				
			
			transfer = queue.get()
			
			output = {"streams" : [] }
			for num, label in self.config["events.8word"].items():
				output["streams"].append({"name" : label, "events" : [] })
			
			index = 0
			events = 0
			
			while (index < int(self.config["softglue"]["Packet-Size"])):
				if not transfer[index] & 0x80000000:
					index += 1
					continue
						
				if (transfer[index] & 0xC0000000 == 0xC0000000):
					self.log(LOG_LEVEL_DEBUG, "Found 24 word event {:08x} at {:d}".format(transfer[index], index))
					index += 24
					continue
				
				events += 1
				transfer[index] &= ~0x80000000
				
				for i in range(8):
					output["streams"][i]["events"].append(int(transfer[index + i]))
					
				index += 8
		
			output["numEvents"] = events
			
			pvstream.set(output)
		
		server.stop()
		
				
		
				
if __name__ == '__main__':
	if len(sys.argv) == 2:
		my_handler = PositionerServer(sys.argv[1])
		my_handler.poll()
	else:
		my_handler = PositionerServer()
		my_handler.poll()
