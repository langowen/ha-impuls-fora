import asyncio
import importlib.util
from pathlib import Path
import unittest
import ast
import json

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'custom_components/impuls_fora'
spec = importlib.util.spec_from_file_location('protocol', COMP / 'protocol.py')
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)

class Response:
    def __init__(self, registers=None, bits=None, error=False):
        self.registers = registers
        self.bits = bits
        self.error = error
    def isError(self):
        return self.error

class Client:
    connected = False
    fail = False
    short = False
    connect_ok = True
    def __init__(self):
        self.calls = []
    async def connect(self):
        self.connected = self.connect_ok
        return self.connect_ok
    async def read_input_registers(self, address, *, count, device_id):
        self.calls.append((4, address, count, device_id))
        await asyncio.sleep(0)
        return Response(registers=list(range(address, address + count - int(self.short))), error=self.fail)
    async def read_discrete_inputs(self, address, *, count, device_id):
        self.calls.append((2, address, count, device_id))
        return Response(bits=[bool(i % 2) for i in range(count)])

class LegacyClient(Client):
    async def read_input_registers(self, address, *, count, slave):
        return await super().read_input_registers(address, count=count, device_id=slave)
    async def read_discrete_inputs(self, address, *, count, slave):
        return await super().read_discrete_inputs(address, count=count, device_id=slave)

class Tests(unittest.IsolatedAsyncioTestCase):
    def test_scaling_and_signed(self):
        for raw, dtype, scale, expected in [(2351,'uint16',.1,235.1),
            (4999,'uint16',.01,49.99),(1000,'uint16',.1,100),
            (279,'uint16',.1,27.9),(65526,'int16',.1,-1),
            (32768,'int16',1,-32768),(65535,'uint16',1,65535)]:
            self.assertEqual(protocol.decode(raw,dtype,scale),expected)

    async def test_addresses_units_snapshot(self):
        c = Client()
        data = await protocol.Reader(c, 1).snapshot()
        self.assertEqual(c.calls, [(4,0,3,1),(4,44,63,1),(2,0,23,1)])
        self.assertEqual(data['registers'][106],106)
        self.assertEqual(len(data['registers']),66)
        self.assertTrue(data['bits'][15])

    async def test_legacy_keyword(self):
        c = LegacyClient()
        await protocol.Reader(c,7).snapshot()
        self.assertTrue(all(call[3] == 7 for call in c.calls))

    async def test_short_reply(self):
        c = Client()
        c.short = True
        with self.assertRaises(protocol.ReadError):
            await protocol.Reader(c,1).snapshot()

    async def test_exception_reply(self):
        c = Client()
        c.fail = True
        with self.assertRaises(protocol.ReadError):
            await protocol.Reader(c,1).snapshot()

    async def test_disconnected_and_recovery(self):
        c = Client()
        c.connect_ok = False
        r = protocol.Reader(c,1)
        with self.assertRaises(protocol.ReadError):
            await r.snapshot()
        self.assertEqual(c.calls, [])
        c.connect_ok = True
        self.assertEqual(len((await r.snapshot())['registers']),66)

    async def test_serialization(self):
        c = Client()
        r = protocol.Reader(c,1)
        await asyncio.gather(r.snapshot(),r.snapshot())
        expected = [(4,0,3,1),(4,44,63,1),(2,0,23,1)]
        self.assertEqual(c.calls, expected + expected)

    def test_sources_compile_and_map(self):
        for p in COMP.glob('*.py'):
            ast.parse(p.read_text(), filename=str(p))
        data = json.loads((COMP/'registers.json').read_text())
        self.assertEqual(len({r['address'] for r in data}),66)
        mapping = {r['address']:r for r in data}
        self.assertEqual(mapping[99]['dtype'],'int16')
        self.assertEqual(mapping[101]['scale'],.1)
        self.assertEqual(mapping[102]['unit'],'мин.')
        alarms = json.loads((COMP/'alarms.json').read_text())
        self.assertEqual(alarms[15]['name'],'АКБ разряжается')

if __name__ == '__main__':
    unittest.main()
