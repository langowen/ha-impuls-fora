"""Test physical arithmetic, gap handling and persistence boundaries."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

COMP = Path(__file__).resolve().parents[1] / 'custom_components/impuls_fora'
pkg = types.ModuleType('fora_energy_test')
pkg.__path__ = [str(COMP)]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location('fora_energy_test.energy', COMP / 'energy.py')
energy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(energy)

def registers(state=451, positive=100, negative=100):
    return {2: state, 97: 2700, 98: 2800, 99: positive, 100: negative,
            88: 39, 89: 4, 90: 43}

class Calculations(unittest.TestCase):
    def test_requires_explicit_enable(self):
        self.assertIsNone(energy.battery_power(registers()))

    def test_independent_branches_no_double_count(self):
        self.assertEqual(energy.battery_power(registers(), 'status'), (5500, 0))
        self.assertEqual(energy.battery_power(registers(), 'status', 'positive'), (2700, 0))
        self.assertEqual(energy.battery_power(registers(), 'status', 'negative'), (2800, 0))

    def test_signed_charge_discharge(self):
        r = registers(positive=65526, negative=65516)  # -1 A and -2 A
        self.assertEqual(energy.battery_power(r, 'positive_discharge'), (830, 0))
        self.assertEqual(energy.battery_power(r, 'positive_charge'), (0, 830))
        r = registers(positive=10, negative=65526)
        self.assertEqual(energy.battery_power(r, 'positive_charge'), (270, 280))

    def test_direction_by_documented_status(self):
        for state in (451, 331):
            self.assertEqual(energy.battery_power(registers(state), 'status'), (5500, 0))
        self.assertEqual(energy.battery_power(registers(326), 'status'), (0, 5500))
        self.assertIsNone(energy.battery_power(registers(999), 'status'))
        self.assertIsNone(energy.battery_power(registers(538), 'status'))
        self.assertEqual(energy.battery_power(registers(538, 0, 0), 'status'), (0, 0))

    def test_invalid_voltage_is_not_power(self):
        r = registers()
        r[97] = 65535
        self.assertIsNone(energy.battery_power(r, 'status'))
        r[97] = 0
        self.assertIsNone(energy.battery_power(r, 'status'))

    def test_one_kwh_and_transition(self):
        c = energy.EnergyCounter(4000)
        c.update(0, (1000, 0))
        c.update(3600, (0, 2000))
        self.assertEqual(c.totals, dict(charge_energy=1, discharge_energy=0))
        c.update(5400, (0, 0))
        self.assertEqual(c.totals, dict(charge_energy=1, discharge_energy=1))

    def test_failed_and_long_gaps_not_integrated(self):
        c = energy.EnergyCounter(25)
        c.update(0, (3600, 0))
        c.update(10, (3600, 0))
        self.assertAlmostEqual(c.totals['charge_energy'], .01)
        c.break_interval()
        c.update(100, (3600, 0))
        c.update(1000, (3600, 0))
        self.assertAlmostEqual(c.totals['charge_energy'], .01)
        c.update(1010, None)
        c.update(1020, (3600, 0))
        self.assertAlmostEqual(c.totals['charge_energy'], .01)

    def test_restore_does_not_bridge_downtime(self):
        c = energy.EnergyCounter(25, dict(charge_energy=12.5, discharge_energy=9))
        c.update(10000, (1000, 0))
        self.assertEqual(c.totals, dict(charge_energy=12.5, discharge_energy=9))
        c.update(10010, (0, 0))
        self.assertAlmostEqual(c.totals['charge_energy'],12.5 + 10/3600)

    def test_corrupt_restore_rejected(self):
        for bad in (-1, float('nan'), float('inf'), '2', True):
            with self.assertRaises(ValueError):
                energy.EnergyCounter(25, dict(charge_energy=bad, discharge_energy=0))


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    """Exercise real coordinator orchestration with in-memory HA/Modbus adapters."""
    async def asyncSetUp(self):
        modules = {}
        def module(name, **attrs):
            result = types.ModuleType(name)
            result.__dict__.update(attrs)
            modules[name] = result
        class UpdateFailed(Exception):
            pass
        class ModbusException(Exception):
            pass
        class Base:
            def __init__(self, *args, **kwargs):
                pass
        class Client:
            def __init__(self, *args, **kwargs):
                pass
            def close(self):
                pass
        class Store:
            stored = None
            def __init__(self, *args):
                self.saves = []
            async def async_load(self):
                return self.stored
            async def async_save(self, data):
                self.saves.append(dict(data))
        module('pymodbus.client', AsyncModbusTcpClient=Client)
        module('pymodbus.exceptions', ModbusException=ModbusException)
        module('homeassistant.helpers.update_coordinator', DataUpdateCoordinator=Base, UpdateFailed=UpdateFailed)
        module('homeassistant.helpers.storage', Store=Store)
        self.modules = patch.dict(sys.modules, modules)
        self.modules.start()
        spec = importlib.util.spec_from_file_location('fora_energy_test.coordinator', COMP / 'coordinator.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        entry = types.SimpleNamespace(entry_id='test', data=dict(host='localhost', port=1502,
            unit_id=1, scan_interval=10), options=dict(battery_mode='status', battery_channels='both'))
        self.c = self.mod.ForaCoordinator(None, entry)
        self.addCleanup(self.modules.stop)

    async def snapshot(self, fail=False):
        async def read():
            if fail:
                raise self.mod.ReadError('offline')
            return {'registers':registers(), 'bits':{}}
        self.c.reader.snapshot = read
        return await self.c._async_update_data()

    async def test_persist_before_publishing_and_restore(self):
        with patch.object(self.mod, 'monotonic', side_effect=[0, 10]):
            await self.snapshot()
            result = await self.snapshot()
        self.assertEqual(result['calculated']['output_power'],8600)
        self.assertAlmostEqual(result['calculated']['charge_energy'],5500 * 10 / 3600000)
        self.assertEqual(self.c.energy_store.saves[-1],self.c.energy.totals)
        self.c.energy_store.stored = dict(charge_energy=4, discharge_energy=3)
        await self.c.async_load_energy()
        self.assertEqual(self.c.energy.totals,dict(charge_energy=4,discharge_energy=3))
        self.assertIsNone(self.c.energy.previous)

    async def test_failed_cycle_breaks_energy_interval(self):
        with patch.object(self.mod,'monotonic',side_effect=[0,20]):
            await self.snapshot()
            with self.assertRaises(self.mod.UpdateFailed):
                await self.snapshot(fail=True)
            result = await self.snapshot()
        self.assertEqual(result['calculated']['charge_energy'],0)

    async def test_disabled_battery_keeps_output_sensor(self):
        self.c.entry.options = {}
        result = await self.snapshot()
        self.assertEqual(result['calculated'],{'output_power':8600})
        self.assertEqual(self.c.energy_store.saves,[])

    async def test_storage_failure_does_not_publish(self):
        async def fail_save(data):
            raise OSError('disk full')
        self.c.energy_store.async_save = fail_save
        with self.assertRaises(self.mod.UpdateFailed):
            await self.snapshot()
        self.assertIsNone(self.c.energy.previous)

if __name__ == '__main__':
    unittest.main()
