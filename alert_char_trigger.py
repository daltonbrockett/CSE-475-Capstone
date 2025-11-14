#!/usr/bin/env python3

import time
 
# 
from ble_peripheral import alertCharacteristic

alert_characteristic = alertCharacteristic()

def alert_detected(gesture_type):
    emergency_contact = "2062221234"
    
    if gesture_type == "ALERT":
        # the prefix should match to the expected format on the receiving side
        message = f"CALL:{emergency_contact}"
        alert_characteristic.send_notification(message)
        print(f"Alert detected, message sent: {message}")



while True:
    gesture = gesture_detected() # gesture type input from the gesture detection side

    if gesture == "ALERT":
        alert_detected(gesture)
        time.sleep(5)