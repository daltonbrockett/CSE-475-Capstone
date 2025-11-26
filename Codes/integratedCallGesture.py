#!/usr/bin/env python3
"""
open palm gesture triggers emergency call via BLE to the APP
"""

import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.framework.formats import landmark_pb2
import time
from picamera2 import Picamera2
import RPi.GPIO as GPIO
import os
import asyncio
import threading
from bluez_peripheral.gatt.service import Service
from bluez_peripheral.gatt.characteristic import characteristic, CharacteristicFlags as Flags
from bluez_peripheral.util import get_message_bus, Adapter
from bluez_peripheral.advert import Advertisement


SERVICE_UUID = "11111111-2222-3333-4444-56789abcdef0"
CHAR_UUID    = "11111111-2222-3333-4444-56789abcdef1"

class AlertService(Service):
    """BLE alert service"""
    
    def __init__(self):
        super().__init__(SERVICE_UUID, True)
        self._value = b"Ready"
        self._notifying = False
    
    @characteristic(CHAR_UUID, Flags.READ | Flags.NOTIFY)
    def alert_char(self, options):
        return self._value
    
    def send_alert(self, message: str):
        """Send alert to connected device (APP)"""
        if not self._notifying:
            print(f"No device subscribed, cannot send message")
            return False
        
        try:
            data = message.encode('utf-8')
            self._value = data
            self.alert_char.changed(self._value)
            print(f"Alert message sent: {message}")
            return True
        except Exception as e:
            print(f"Failed to send alert: {e}")
            return False

alert_service = None


# Detect headless mode from environment variable
HEADLESS = os.getenv('HEADLESS', '0') == '1'

# GPIO pin mapping for each gesture
GPIO_PINS = {
    'open_palm': 17,
    'thumb_up': 27,
    'thumb_down': 22,
    'closed_fist': 18,
}
ALL_GPIO_PINS = list(GPIO_PINS.values())

# Phone call trigger configuration
EMERGENCY_GESTURE = 'open_palm'
EMERGENCY_CONTACT = "2061112222"
EMERGENCY_HOLD_TIME = 3.0  # hold for 3 seconds to trigger
COOLDOWN_TIME = 10.0  # 10 second cooldown between alerts

# Time tracking
gesture_start_time = None
last_emergency_time = 0
emergency_triggered = False


# ------------------------GPIO ----------------------------------------------------
GPIO.setmode(GPIO.BCM)
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Picamera2: use lower resolution for speed
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (320, 240), "format": "RGB888"})
picam2.configure(config)
picam2.start()
time.sleep(2)

model_path = "gesture_recognizer.task"
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.GestureRecognizerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=1,
    min_hand_detection_confidence=0.4,
    min_hand_presence_confidence=0.4,
    min_tracking_confidence=0.4
)
recognizer = vision.GestureRecognizer.create_from_options(options)

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_hands = mp.solutions.hands


# ------------------------ Emgergency alert setup ---------------------------------------
def trigger_emergency_alert():
    """Trigger emergency call via BLE"""
    global alert_service, last_emergency_time
    
    if alert_service is None:
        print("BLE service not initialized")
        return False
    
    current_time = time.time()
    if current_time - last_emergency_time < COOLDOWN_TIME:
        remaining = COOLDOWN_TIME - (current_time - last_emergency_time)
        return False
    
    # Send emergency alert
    message = f"CALL:{EMERGENCY_CONTACT}"
    success = alert_service.send_alert(message)
    
    if success:
        last_emergency_time = current_time
        print(f"Emergency alert sent successfully!")
        
        # Visual feedback: Flash all LEDs
        for _ in range(3):
            for pin in ALL_GPIO_PINS:
                GPIO.output(pin, GPIO.HIGH)
            time.sleep(0.2)
            for pin in ALL_GPIO_PINS:
                GPIO.output(pin, GPIO.LOW)
            time.sleep(0.2)
    
    return success


def run_ble_server():
    """Run BLE server in async event loop"""
    asyncio.run(ble_server_main())

async def ble_server_main():
    """Main BLE server coroutine"""
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

    try:
        while True:
            await asyncio.sleep(10) # send every 10 seconds
            
    except Exception as e:
        print(f"BLE Server Error: {e}")
        import traceback
        traceback.print_exc()


def main():
    global gesture_start_time, emergency_triggered
    
    # Start BLE server in background thread
    ble_thread = threading.Thread(target=run_ble_server, daemon=True)
    ble_thread.start()
    print("BLE server thread started")
    
    # Wait for BLE to initialize
    time.sleep(3)
    
    COUNTER, FPS = 0, 0
    START_TIME = time.time()
    fps_avg_frame_count = 10
    
    # Variables for pointing_up blink alternation
    pointing_up_active = False
    last_toggle_time = 0
    toggle_state = False  # False: GPIO 18 & 22 ON; True: GPIO 17 & 27 ON
    TOGGLE_INTERVAL = 0.5  # seconds
        
    try:
        while True:
            image = picam2.capture_array()
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image)
            timestamp_ms = int(time.time() * 1000)
            result = recognizer.recognize_for_video(mp_image, timestamp_ms)
            
            COUNTER += 1
            if COUNTER % fps_avg_frame_count == 0:
                FPS = fps_avg_frame_count / (time.time() - START_TIME)
                START_TIME = time.time()
            fps_text = f'FPS = {FPS:.1f}'
            
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            cv2.putText(image_bgr, fps_text, (24, 50),
                        cv2.FONT_HERSHEY_DUPLEX, 1, (0, 0, 0), 1, cv2.LINE_AA)
            
            # Default: turn off all LEDs
            for pin in ALL_GPIO_PINS:
                GPIO.output(pin, GPIO.LOW)
            
            # Reset detection flags every loop
            pointing_up_detected = False
            other_gesture_active = False
            emergency_gesture_detected = False
        
            if result and result.gestures and result.hand_landmarks:
                for hand_index, hand_landmarks in enumerate(result.hand_landmarks):
                    if hand_index < len(result.gestures):
                        gestures_for_hand = result.gestures[hand_index]
                        if gestures_for_hand:
                            gesture = gestures_for_hand[0]
                            category_name = gesture.category_name.lower()
                            score = round(gesture.score, 2)
                            
                            # ---------- Gesture: call triggering ----------
                            if category_name == EMERGENCY_GESTURE:
                                emergency_gesture_detected = True
                                
                                # Start timer on first detection
                                if gesture_start_time is None:
                                    gesture_start_time = time.time()
                                    emergency_triggered = False
                                
                                hold_duration = time.time() - gesture_start_time
                                
                                if hold_duration >= EMERGENCY_HOLD_TIME and not emergency_triggered:
                                    trigger_emergency_alert()
                                    emergency_triggered = True
                                
                                # Blink LED while holding for emergency gesture
                                if int(time.time() * 4) % 2 == 0:
                                    GPIO.output(GPIO_PINS[EMERGENCY_GESTURE], GPIO.HIGH)
                                
                                # Progress bar display
                                progress = min(hold_duration / EMERGENCY_HOLD_TIME, 1.0)
                                bar_width = 200
                                bar_filled = int(bar_width * progress)
                                cv2.rectangle(image_bgr, (10, 80), (10 + bar_width, 110), (50, 50, 50), -1)
                                cv2.rectangle(image_bgr, (10, 80), (10 + bar_filled, 110), (0, 0, 255), -1)
                                cv2.putText(image_bgr, f"HOLD: {hold_duration:.1f}s / {EMERGENCY_HOLD_TIME}s",
                                           (15, 102), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                            elif category_name == 'victory':
                                for pin in ALL_GPIO_PINS:
                                    GPIO.output(pin, GPIO.HIGH)
                                other_gesture_active = True
                            
                            elif category_name == 'pointing_up':
                                pointing_up_detected = True
                            
                            elif category_name in GPIO_PINS:
                                GPIO.output(GPIO_PINS[category_name], GPIO.HIGH)
                                other_gesture_active = True
                            
                            label_text = f'{category_name} ({score})'
                            x_min = min(lm.x for lm in hand_landmarks)
                            y_min = min(lm.y for lm in hand_landmarks)
                            frame_h, frame_w = image_bgr.shape[:2]
                            x_min_px = int(x_min * frame_w)
                            y_min_px = int(y_min * frame_h) - 10
                            
                            cv2.putText(image_bgr, label_text, (x_min_px, max(y_min_px, 20)),
                                       cv2.FONT_HERSHEY_DUPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)
                            
                    hand_proto = landmark_pb2.NormalizedLandmarkList()
                    hand_proto.landmark.extend(
                        [landmark_pb2.NormalizedLandmark(x=lm.x, y=lm.y, z=lm.z) for lm in hand_landmarks]
                    )
                    mp_drawing.draw_landmarks(
                        image_bgr,
                        hand_proto,
                        mp_hands.HAND_CONNECTIONS,
                        mp_drawing_styles.get_default_hand_landmarks_style(),
                        mp_drawing_styles.get_default_hand_connections_style()
                    )
            
            # Reset emergency gesture timer if not detected
            if not emergency_gesture_detected:
                if gesture_start_time is not None:
                    print(f"Gesture released after {time.time() - gesture_start_time:.1f}s")
                gesture_start_time = None
                emergency_triggered = False
            
            # Handle pointing_up toggle logic only if no other gesture (like victory) is active
            current_time = time.time()
            if pointing_up_detected and not other_gesture_active:
                if not pointing_up_active:
                    pointing_up_active = True
                    last_toggle_time = current_time
                    toggle_state = False # Start with gpio18&22 ON
                
                if current_time - last_toggle_time >= TOGGLE_INTERVAL:
                    toggle_state = not toggle_state
                    last_toggle_time = current_time
                
                if toggle_state:
                    GPIO.output(GPIO_PINS['open_palm'], GPIO.HIGH)  # GPIO17
                    GPIO.output(GPIO_PINS['thumb_up'], GPIO.HIGH)   # GPIO27
                else:
                    GPIO.output(GPIO_PINS['closed_fist'], GPIO.HIGH) # GPIO18
                    GPIO.output(GPIO_PINS['thumb_down'], GPIO.HIGH) # GPIO22
            else:
                pointing_up_active = False
            
            # Display BLE status
            ble_status = "BLE: Connected" if alert_service and alert_service._notifying else "BLE: Waiting..."
            cv2.putText(image_bgr, ble_status, (24, image_bgr.shape[0] - 20),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0) if alert_service and alert_service._notifying else (0, 0, 255), 2)
            
            if not HEADLESS:
                cv2.imshow('Emergency Gesture Detection', image_bgr)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC to exit
                    break
    
    finally:
        for pin in ALL_GPIO_PINS:
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()
        recognizer.close()
        picam2.stop()
        if not HEADLESS:
            cv2.destroyAllWindows()

if __name__ == "__main__":
    main()