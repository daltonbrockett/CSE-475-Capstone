#!/usr/bin/env python3

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
    """BLE alert service with notify characteristic"""
    def __init__(self):
        super().__init__(SERVICE_UUID, True)
        self._value = b"Ready"
        self._notifying = True

    @characteristic(CHAR_UUID, Flags.READ | Flags.NOTIFY)
    def alert_char(self, options):
        return self._value

    def send_alert(self, message: str):
        # Send alert message to connected BLE device
        if not self._notifying:
            return False
        try:
            data = message.encode('utf-8')
            self._value = data
            self.alert_char.changed(self._value)
            return True
        except Exception:
            return False

alert_service = None
HEADLESS = os.getenv('HEADLESS', '0') == '1'

# Sound constants for buzzer notes and emergency tone
SCALE_FREQS = [261, 293, 329, 349, 392, 440, 493, 523]
SCALE_DURATION = 0.15
SCALE_PAUSE = 1.0
THUMBS_UP_FREQ = 1046

# Gesture and timing constants
EMERGENCY_GESTURE = 'pointing_up'
EMERGENCY_CONTACT = "2068254849"
EMERGENCY_HOLD_TIME = 3.0
BLINK_INTERVAL = 0.5
BLINK_DURATION = 5.0
COOLDOWN_TIME = 10.0

# GPIO pins for LEDs/buzzer based on gestures
GPIO_PINS = {
    'open_palm': 17,
    'thumb_up': 27,
    'pointing_up': 22,
    'closed_fist': 18
}
# Light-dependent resistor (LDR) pins
LDR_IN_PIN = 23
LDR_OUT_PIN = 24
LDR_LED_PIN = 4
LDR_THRESHOLD = 3

ALL_GPIO_PINS = list(GPIO_PINS.values()) + [LDR_IN_PIN, LDR_OUT_PIN, LDR_LED_PIN]

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)

# Setup all GPIO output pins
for pin in GPIO_PINS.values():
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)

# Setup GPIO pins for LDR sensor
GPIO.setup(LDR_IN_PIN, GPIO.OUT)
GPIO.setup(LDR_OUT_PIN, GPIO.IN)
GPIO.setup(LDR_LED_PIN, GPIO.OUT)
GPIO.output(LDR_IN_PIN, GPIO.HIGH)
GPIO.output(LDR_LED_PIN, GPIO.HIGH)

# Variables for LDR charging and measurement state
ldr_charging = True
ldr_charge_start = time.time()
ldr_measuring = False
ldr_start_time = None
ldr_reset_charge_needed = True
ldr_timeout_cooldown = 5.0
ldr_last_timeout = 0.0

buzzer_pwm = GPIO.PWM(GPIO_PINS['thumb_up'], THUMBS_UP_FREQ)
buzzer_pwm.start(0)

# Gesture and buzzer state variables
toggle_states = {'open_palm': False, 'closed_fist': False}
last_detected_gesture = None
hand_was_visible = False
iloveyou_active = False
scale_index = 0
note_start_time = None
sequence_pause_start = None
gesture_start_time = None
last_emergency_time = 0
emergency_triggered = False
blink_start_time = None
pointing_up_start_time = None

# Initialize camera and gesture recognizer
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
    # Sends emergency call message via BLE with cooldown
    global alert_service, last_emergency_time
    if alert_service is None:
        return False
    current_time = time.time()
    if current_time - last_emergency_time < COOLDOWN_TIME:
        return False
    message = f"CALL:{EMERGENCY_CONTACT}"
    success = alert_service.send_alert(message)
    if success:
        last_emergency_time = current_time
        return True
    return False

def run_ble_server():
    asyncio.run(ble_server_main())

async def ble_server_main():
    # Coroutine to register BLE service and advertise
    global alert_service
    bus = await get_message_bus()
    alert_service = AlertService()
    await alert_service.register(bus)
    agent = NoIoAgent()
    await agent.register(bus)
    adapter = await Adapter.get_first(bus)
    advert = Advertisement("RPi-Gesture", [SERVICE_UUID], appearance=0x0000, timeout=0)
    await advert.register(bus, adapter)
    try:
        while True:
            await asyncio.sleep(10)
    except Exception:
        pass

def main():
    global gesture_start_time, emergency_triggered, last_detected_gesture, hand_was_visible
    global iloveyou_active, scale_index, note_start_time, sequence_pause_start
    global pointing_up_start_time, blink_start_time, toggle_states
    global ldr_charging, ldr_charge_start, ldr_measuring, ldr_start_time
    global ldr_reset_charge_needed, ldr_timeout_cooldown, ldr_last_timeout

    # Start BLE in background thread
    ble_thread = threading.Thread(target=run_ble_server, daemon=True)
    ble_thread.start()
    time.sleep(3)

    COUNTER, FPS = 0, 0
    START_TIME = time.time()
    fps_avg_frame_count = 10

    try:
        while True:
            current_time = time.time()

            # LDR: Charge/discharge cycle to detect ambient light level
            if ldr_charging:
                charge_duration = 4.0 if ldr_reset_charge_needed else 2.0
                if (current_time - ldr_charge_start) >= charge_duration:
                    if GPIO.input(LDR_OUT_PIN) == GPIO.HIGH:
                        GPIO.output(LDR_IN_PIN, GPIO.LOW)
                        ldr_charging = False
                        ldr_measuring = True
                        ldr_start_time = current_time
                        ldr_reset_charge_needed = False
                    else:
                        ldr_charge_start = current_time
                else:
                    GPIO.output(LDR_IN_PIN, GPIO.HIGH)

            elif ldr_measuring:
                discharge_elapsed = current_time - ldr_start_time
                if (current_time - ldr_last_timeout) < ldr_timeout_cooldown:
                    GPIO.output(LDR_LED_PIN, GPIO.HIGH)
                else:
                    if GPIO.input(LDR_OUT_PIN) == GPIO.LOW:
                        discharge_time = discharge_elapsed
                        GPIO.output(LDR_LED_PIN, GPIO.HIGH if discharge_time > LDR_THRESHOLD else GPIO.LOW)
                        ldr_reset_charge_needed = True
                        ldr_charging = True
                        ldr_charge_start = current_time
                        ldr_measuring = False
                        ldr_start_time = None
                    elif discharge_elapsed > 4.0:
                        GPIO.output(LDR_LED_PIN, GPIO.HIGH)
                        ldr_last_timeout = current_time
                        ldr_reset_charge_needed = True
                        ldr_charging = True
                        ldr_charge_start = current_time
                        ldr_measuring = False
                        ldr_start_time = None

            # Capture camera frame and run gesture recognition
            image = picam2.capture_array()
            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image)
            timestamp_ms = int(time.time() * 1000)
            result = recognizer.recognize_for_video(mp_image, timestamp_ms)
            COUNTER += 1

            # Display average FPS on image
            if COUNTER % fps_avg_frame_count == 0:
                FPS = fps_avg_frame_count / (time.time() - START_TIME)
                START_TIME = time.time()
                fps_text = f'FPS = {FPS:.1f}'
                cv2.putText(image_bgr, fps_text, (24, 50),
                           cv2.FONT_HERSHEY_DUPLEX, 1, (0, 0, 0), 1, cv2.LINE_AA)

            hand_visible = result and result.gestures and result.hand_landmarks

            # Turn off non-toggle pins by default
            for gesture, pin in GPIO_PINS.items():
                if gesture not in ['open_palm', 'closed_fist', 'pointing_up']:
                    GPIO.output(pin, GPIO.LOW)

            # Gesture status flags
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

                            # Handle emergency gesture with hold timer and blink feedback
                            if category_name == EMERGENCY_GESTURE:
                                emergency_gesture_detected = True
                                if gesture_start_time is None:
                                    gesture_start_time = current_time
                                    emergency_triggered = False
                                hold_duration = current_time - gesture_start_time
                                if hold_duration >= EMERGENCY_HOLD_TIME and not emergency_triggered:
                                    trigger_emergency_alert()
                                    emergency_triggered = True
                                    blink_start_time = current_time

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
                                pointing_up_start_time = None
                                gesture_start_time = None
                                emergency_triggered = False
                                blink_start_time = None

                            else:
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

                            # Draw gesture label and hand landmarks
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
            else:
                hand_was_visible = False
                last_detected_gesture = None
                pointing_up_start_time = None
                gesture_start_time = None
                emergency_triggered = False
                blink_start_time = None
                GPIO.output(GPIO_PINS['pointing_up'], GPIO.LOW)

            if not emergency_gesture_detected:
                gesture_start_time = None
                emergency_triggered = False
                blink_start_time = None
                GPIO.output(GPIO_PINS['pointing_up'], GPIO.LOW)

            # Update GPIO output for toggle gestures
            GPIO.output(GPIO_PINS['open_palm'], GPIO.HIGH if toggle_states['open_palm'] else GPIO.LOW)
            GPIO.output(GPIO_PINS['closed_fist'], GPIO.HIGH if toggle_states['closed_fist'] else GPIO.LOW)

            # Buzzer control prioritization
            if found_victory:
                pass
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
            else:
                buzzer_pwm.ChangeDutyCycle(0)

            if not HEADLESS:
                cv2.imshow('Integrated Gesture + BLE Control + LDR', image_bgr)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    finally:
        # Reset and cleanup GPIO and peripherals safely
        buzzer_pwm.ChangeDutyCycle(0)
        buzzer_pwm.stop()
        output_pins = [p for p in ALL_GPIO_PINS if p != LDR_OUT_PIN]
        for pin in output_pins:
            try:
                GPIO.output(pin, GPIO.LOW)
            except:
                pass
        GPIO.cleanup()
        recognizer.close()
        picam2.stop()
        if not HEADLESS:
            cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
