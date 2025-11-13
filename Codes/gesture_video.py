import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.framework.formats import landmark_pb2
import time
from picamera2 import Picamera2

# Initialize Picamera2 with lower resolution for speed
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (320, 240), "format": "RGB888"})
picam2.configure(config)
picam2.start()
time.sleep(2)  # Warm-up

model_path = "gesture_recognizer.task"
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.GestureRecognizerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,  # Optimized for stream processing
    num_hands=1,
    min_hand_detection_confidence=0.7,
    min_hand_presence_confidence=0.7,
    min_tracking_confidence=0.7
)
recognizer = vision.GestureRecognizer.create_from_options(options)

COUNTER, FPS = 0, 0
START_TIME = time.time()
fps_avg_frame_count = 10

mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles
mp_hands = mp.solutions.hands

try:
    while True:
        # Capture frame as RGB array (no conversion needed for MediaPipe)
        image = picam2.capture_array()
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image)

        # Use VIDEO mode with timestamp for consistency and performance
        timestamp_ms = int(time.time() * 1000)
        result = recognizer.recognize_for_video(mp_image, timestamp_ms)

        # Update FPS calculation
        COUNTER += 1
        if COUNTER % fps_avg_frame_count == 0:
            FPS = fps_avg_frame_count / (time.time() - START_TIME)
            START_TIME = time.time()
        fps_text = f'FPS = {FPS:.1f}'

        # For display, convert to BGR only once
        image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        cv2.putText(image_bgr, fps_text, (24, 50),
                    cv2.FONT_HERSHEY_DUPLEX, 1, (0, 0, 0), 1, cv2.LINE_AA)

        if result and result.hand_landmarks:
            for hand_index, hand_landmarks in enumerate(result.hand_landmarks):
                # Calculate bounding box
                x_min = min(lm.x for lm in hand_landmarks)
                y_min = min(lm.y for lm in hand_landmarks)
                x_max = max(lm.x for lm in hand_landmarks)
                y_max = max(lm.y for lm in hand_landmarks)

                frame_h, frame_w = image_bgr.shape[:2]
                x_min_px = int(x_min * frame_w)
                y_min_px = int(y_min * frame_h)
                y_max_px = int(y_max * frame_h)

                # Extract gesture for this hand safely
                if result.gestures and hand_index < len(result.gestures):
                    gestures_for_hand = result.gestures[hand_index]
                    if gestures_for_hand:
                        gesture = gestures_for_hand[0]
                        category_name = gesture.category_name
                        score = round(gesture.score, 2)
                        label_text = f'{category_name} ({score})'

                        text_size, _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_DUPLEX, 1, 2)
                        text_x = x_min_px
                        text_y = y_min_px - 10
                        if text_y < 0:
                            text_y = y_max_px + text_size[1]

                        cv2.putText(image_bgr, label_text, (text_x, text_y),
                                    cv2.FONT_HERSHEY_DUPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

                # Draw landmarks (can be disabled for extra speed)
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

        # Show annotated frame
        cv2.imshow('gesture_recognition', image_bgr)

        if cv2.waitKey(1) & 0xFF == 27:
            break

finally:
    recognizer.close()
    picam2.stop()
    cv2.destroyAllWindows()
