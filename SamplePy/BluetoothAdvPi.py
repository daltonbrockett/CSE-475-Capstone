import asyncio
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as Flags
from bluez_peripheral.util import get_message_bus, Adapter
from bluez_peripheral.advert import Advertisement

SERVICE_UUID = "11111111-2222-3333-4444-56789abcdef0"
CHAR_UUID    = "11111111-2222-3333-4444-56789abcdef1"

class DemoService(Service):
    def __init__(self):
        super().__init__(SERVICE_UUID, True)
        self._value = b"Hello Android!"

    @characteristic(CHAR_UUID, Flags.READ | Flags.NOTIFY)
    def demo_char(self, options):
        return self._value

    def notify(self, data: bytes):
        self._value = data
        self.demo_char.changed(self._value)

async def main():
    bus = await get_message_bus()
    svc = DemoService()
    await svc.register(bus)

    adapter = await Adapter.get_first(bus)
    advert = Advertisement("PiBLE", [SERVICE_UUID], appearance=0x0000, timeout=0)
    await advert.register(bus, adapter)

    i = 0
    while True:
        svc.notify(f"Ping {i}".encode())
        i += 1
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
