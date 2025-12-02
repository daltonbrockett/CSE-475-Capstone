#!/usr/bin/env python3

"""
Integrated gesture recognition with BLE emergency calling and advanced GPIO control
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
from bluez_peripheral.agent import NoIoAgent

SERVICE_UUID = "11111111-2222-3333-4444-56789abcdef0"
CHAR_UUID = "11111111-2222-3333-4444-56789abcdef1"

class AlertService(Service):
    """BLE alert service"""
    def __init__(self):
        super().__init__(SERVICE_UUID, True)
        self._value = b"Ready"
        self._notifying = True

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

# Constants for the C major scale (octave C4-C5)
SCALE_FREQS = [261, 293, 329, 349, 392, 440, 493, 523]  # C4 D4 E4 F4 G4 A4 B4 C5 (Hz)
SCALE_DURATION = 0.15  # seconds for each note
SCALE_GAP = 0.03       # gap between notes (seconds)
SCALE_PAUSE = 1.0      # pause (seconds) between scale repeats
THUMBS_UP_FREQ = 1046  # Middle C continuous tone

# Gesture hold and blink constants
EMERGENCY_GESTURE = 'pointing_up'  # Changed to pointing_up
EMERGENCY_CONTACT = "2061112222"
EMERGENCY_HOLD_TIME = 3.0          # Hold time for emergency trigger
BLINK_INTERVAL = 0.5               # Blink interval (0.5s on/off)
BLINK_DURATION = 5.0               # Total blink time (5s)
COOLDOWN_TIME = 10.0               # Emergency alert cooldown (seconds)

# GPIO pin mapping for each gesture
GPIO_PINS = {
    'open_palm': 17,
    'thumb_up': 27,    # Passive buzzer pin
    'pointing_up': 22, # Emergency blink LED + gesture
    'closed_fist': 18
}
ALL_GPIO_PINS = list(GPIO_PINS.values())

GPIO.setmode(GPIO.BCM)
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# PWM for buzzer (starts at thumbs_up frequency)
buzzer_pwm = GPIO.PWM(GPIO_PINS['thumb_up'], THUMBS_UP_FREQ)
buzzer_pwm.start(0)

# State variables
toggle_states = {
    'open_palm': False,
    'closed_fist': False
}
last_detected_gesture = None
hand_was_visible = False

# ILoveYou scale state machine
iloveyou_active = False
scale_index = 0
note_start_time = None
sequence_pause_start = None

# Emergency gesture timing and blinking
gesture_start_time = None
last_emergency_time = 0
emergency_triggered = False
blink_start_time = None

# Pointing up hold tracking
pointing_up_start_time = None

# Picamera2 setup
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

def trigger_emergency_alert():
    """Trigger emergency call via BLE"""
    global alert_service, last_emergency_time

    if alert_service is None:
        print("BLE service not initialized")
        return False

    current_time = time.time()
    if current_time - last_emergency_time < COOLDOWN_TIME:
        remaining = COOLDOWN_TIME - (current_time - last_emergency_time)
        print(f"Cooldown active: {remaining:.1f}s remaining")
        return False

    # Send emergency alert
    message = f"CALL:{EMERGENCY_CONTACT}"
    success = alert_service.send_alert(message)

    if success:
        last_emergency_time = current_time
        print(f"Emergency alert sent successfully!")
        return True
    return False

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

    agent = NoIoAgent()
    await agent.register(bus)

    adapter = await Adapter.get_first(bus)

    # register advertisement
    advert = Advertisement("RPi-Gesture", [SERVICE_UUID], appearance=0x0000, timeout=0)
    await advert.register(bus, adapter)

    print("BLE Advertisement started... Waiting for Android app to connect...")

    try:
        while True:
            await asyncio.sleep(10)  # keep alive
    except Exception as e:
        print(f"BLE Server Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    global gesture_start_time, emergency_triggered, last_detected_gesture, hand_was_visible
    global iloveyou_active, scale_index, note_start_time, sequence_pause_start
    global pointing_up_start_time, blink_start_time, toggle_states

    # Start BLE server in background thread
    ble_thread = threading.Thread(target=run_ble_server, daemon=True)
    ble_thread.start()
    print("BLE server thread started")

    # Wait for BLE to initialize
    time.sleep(3)

    COUNTER, FPS = 0, 0
    START_TIME = time.time()
    fps_avg_frame_count = 10

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

            current_time = time.time()
            hand_visible = result and result.gestures and result.hand_landmarks

            # Default: turn off non-toggle pins (thumb_up)
            for gesture, pin in GPIO_PINS.items():
                if gesture not in ['open_palm', 'closed_fist', 'pointing_up']:
                    GPIO.output(pin, GPIO.LOW)

            other_gesture_active = False
            found_iloveyou = False
            found_thumb_up = False
            found_victory = False
            emergency_gesture_detected = False

            if hand_visible:
                hand_was_visible = True

                for hand_index, hand_landmarks in enumerate(result.hand_landmarks):
                    if hand_index < len(result.gestures):
                        gestures_for_hand = result.gestures[hand_index]
                        if gestures_for_hand:
                            gesture = gestures_for_hand[0]
                            category_name = gesture.category_name.lower()
                            score = round(gesture.score, 2)

                            gesture_changed = (last_detected_gesture != category_name) or (not hand_was_visible)

                            # ---------- EMERGENCY GESTURE is pointing_up now ----------
                            if category_name == EMERGENCY_GESTURE:
                                emergency_gesture_detected = True
                                if gesture_start_time is None:
                                    gesture_start_time = current_time
                                    emergency_triggered = False

                                hold_duration = current_time - gesture_start_time
                                if hold_duration >= EMERGENCY_HOLD_TIME and not emergency_triggered:
                                    trigger_emergency_alert()
                                    emergency_triggered = True
                                    blink_start_time = current_time  # start blink feedback

                                # Blink LED while holding for emergency gesture if triggered
                                if emergency_triggered and blink_start_time is not None:
                                    elapsed_blink = current_time - blink_start_time
                                    if elapsed_blink <= BLINK_DURATION:
                                        blink_phase = (elapsed_blink % BLINK_INTERVAL) < (BLINK_INTERVAL / 2)
                                        GPIO.output(GPIO_PINS[EMERGENCY_GESTURE], blink_phase)
                                    else:
                                        GPIO.output(GPIO_PINS[EMERGENCY_GESTURE], GPIO.LOW)
                                else:
                                    GPIO.output(GPIO_PINS[EMERGENCY_GESTURE], GPIO.LOW)

                                other_gesture_active = True

                            elif category_name == 'victory':
                                found_victory = True
                                buzzer_pwm.ChangeFrequency(THUMBS_UP_FREQ)
                                buzzer_pwm.ChangeDutyCycle(50)
                                toggle_states['open_palm'] = True
                                toggle_states['closed_fist'] = True
                                GPIO.output(GPIO_PINS['open_palm'], GPIO.HIGH)
                                GPIO.output(GPIO_PINS['closed_fist'], GPIO.HIGH)
                                other_gesture_active = True
                                # Reset timers related to pointing_up/ emergency
                                pointing_up_start_time = None
                                gesture_start_time = None
                                emergency_triggered = False
                                blink_start_time = None

                            else:
                                # Reset timers on gesture change (other than pointing_up)
                                pointing_up_start_time = None
                                gesture_start_time = None
                                emergency_triggered = False
                                blink_start_time = None
                                GPIO.output(GPIO_PINS['pointing_up'], GPIO.LOW)

                                if category_name == 'thumb_up':
                                    found_thumb_up = True
                                    other_gesture_active = True

                                elif category_name == 'iloveyou':
                                    found_iloveyou = True
                                    other_gesture_active = True

                                elif category_name in ['open_palm', 'closed_fist']:
                                    if gesture_changed:
                                        toggle_states[category_name] = not toggle_states[category_name]
                                    other_gesture_active = True

                            last_detected_gesture = category_name

                            # Draw gesture label
                            label_text = f'{category_name} ({score})'
                            x_min = min(lm.x for lm in hand_landmarks)
                            y_min = min(lm.y for lm in hand_landmarks)
                            frame_h, frame_w = image_bgr.shape[:2]
                            x_min_px = int(x_min * frame_w)
                            y_min_px = int(y_min * frame_h) - 10
                            cv2.putText(image_bgr, label_text, (x_min_px, max(y_min_px, 20)),
                                        cv2.FONT_HERSHEY_DUPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

                            # Hand landmarks drawing
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

            else:
                hand_was_visible = False
                last_detected_gesture = None
                pointing_up_start_time = None
                gesture_start_time = None
                emergency_triggered = False
                blink_start_time = None
                GPIO.output(GPIO_PINS['pointing_up'], GPIO.LOW)

            # Reset emergency gesture timer if not detected
            if not emergency_gesture_detected:
                if gesture_start_time is not None:
                    print(f"Emergency gesture released after {current_time - gesture_start_time:.1f}s")
                    gesture_start_time = None
                    emergency_triggered = False
                    blink_start_time = None
                    GPIO.output(GPIO_PINS['pointing_up'], GPIO.LOW)

            # Apply toggle states for open_palm and closed_fist
            GPIO.output(GPIO_PINS['open_palm'], GPIO.HIGH if toggle_states['open_palm'] else GPIO.LOW)
            GPIO.output(GPIO_PINS['closed_fist'], GPIO.HIGH if toggle_states['closed_fist'] else GPIO.LOW)

            # BUZZER LOGIC - PRIORITIZED (victory > thumbs_up > iloveyou > silence)
            if found_victory:
                pass  # Victory buzzer handled in gesture logic
            elif found_thumb_up:
                buzzer_pwm.ChangeFrequency(THUMBS_UP_FREQ)
                buzzer_pwm.ChangeDutyCycle(50)
            elif found_iloveyou:
                if not iloveyou_active:
                    iloveyou_active = True
                    scale_index = 0
                    note_start_time = current_time
                    sequence_pause_start = None

                if sequence_pause_start is None:
                    if scale_index < len(SCALE_FREQS):
                        buzzer_pwm.ChangeFrequency(SCALE_FREQS[scale_index])
                        buzzer_pwm.ChangeDutyCycle(50)
                        if current_time - note_start_time >= SCALE_DURATION:
                            buzzer_pwm.ChangeDutyCycle(0)
                            scale_index += 1
                            note_start_time = current_time
                    else:
                        buzzer_pwm.ChangeDutyCycle(0)
                        sequence_pause_start = current_time
                else:
                    if current_time - sequence_pause_start >= SCALE_PAUSE:
                        scale_index = 0
                        note_start_time = current_time
                        sequence_pause_start = None
            else:
                iloveyou_active = False
                scale_index = 0
                note_start_time = None
                sequence_pause_start = None
                buzzer_pwm.ChangeDutyCycle(0)

            # Emergency hold progress bar
            if emergency_gesture_detected and gesture_start_time is not None:
                hold_duration = current_time - gesture_start_time
                progress = min(hold_duration / EMERGENCY_HOLD_TIME, 1.0)
                bar_width = 200
                bar_filled = int(bar_width * progress)
                cv2.rectangle(image_bgr, (10, 80), (10 + bar_width, 110), (50, 50, 50), -1)
                cv2.rectangle(image_bgr, (10, 80), (10 + bar_filled, 110), (0, 0, 255), -1)
                cv2.putText(image_bgr, f"HOLD: {hold_duration:.1f}s / {EMERGENCY_HOLD_TIME}s",
                            (15, 102), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            # Display BLE status
            ble_status = "BLE: Connected" if alert_service and alert_service._notifying else "BLE: Waiting..."
            cv2.putText(image_bgr, ble_status, (24, image_bgr.shape[0] - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0) if alert_service and alert_service._notifying else (0, 0, 255), 2)

            if not HEADLESS:
                cv2.imshow('Integrated Gesture + BLE Control', image_bgr)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC to exit
                    break

    finally:
        buzzer_pwm.ChangeDutyCycle(0)
        buzzer_pwm.stop()
        for pin in ALL_GPIO_PINS:
            GPIO.output(pin, GPIO.LOW)
        GPIO.cleanup()
        recognizer.close()
        picam2.stop()
        if not HEADLESS:
            cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
