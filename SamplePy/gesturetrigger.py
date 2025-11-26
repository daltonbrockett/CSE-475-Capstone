#!/usr/bin/env python3
 
import time
import asyncio
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as Flags
from bluez_peripheral.util import get_message_bus, Adapter
from bluez_peripheral.advert import Advertisement

# should always match!!
SERVICE_UUID = "11111111-2222-3333-4444-56789abcdef0"
CHAR_UUID    = "11111111-2222-3333-4444-56789abcdef1"

class AlertService(Service):
    """BLE Service for emergency alerts"""
    
    def __init__(self):
        super().__init__(SERVICE_UUID, True)
        self._value = b"Ready"  # Initial value
    
    @characteristic(CHAR_UUID, Flags.READ | Flags.NOTIFY)
    def alert_char(self, options):
        return self._value
    
    def send_alert(self, message: str):
        data = message.encode('utf-8')
        self._value = data
        self.alert_char.changed(self._value)
        print(f"Sent notification: {message}")

alert_service = None

def on_gesture_detected(gesture_type: str):
    """ Called when Pi detects a gesture """
    
    global alert_service
    
    emergency_contact = "2062221234"
    
    if gesture_type == "ALERT":
        # the prefix should match to the expected format on the receiving side
        message = f"CALL:{emergency_contact}"
        alert_service.send_alert(message)
        print(f"Alert detected, message sent: {message}")




async def main():
    global alert_service
    
    bus = await get_message_bus()
     
    # register service
    alert_service = AlertService()
    await alert_service.register(bus)
     
    adapter = await Adapter.get_first(bus)
     
    # register advertisement
    advert = Advertisement("RPi", [SERVICE_UUID], appearance=0x0000, timeout=0)
    await advert.register(bus, adapter)
    print("Advertisement started... Waiting for Android app to connect...")
 
    
    # simulate gesture detection for testing
    test_messages = "CALL:2061112222"

    while True:
        alert_service.send_alert(test_messages)
        print(f"Manual test to send : '{test_messages}'")

        await asyncio.sleep(100)  # send every 100 seconds

    
