import time
import cv2
import mediapipe as mp
from picamera2 import Picamera2

# Global FPS variables
COUNTER, FPS = 0, 0
START_TIME = time.time()

# Initialize MediaPipe Hands modules
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
mp_drawing_styles = mp.solutions.drawing_styles

# Initialize Picamera2 with RGB888 format for proper color channels
picam2 = Picamera2()
config = picam2.create_video_configuration(main={"size": (640, 480), "format": "RGB888"})
picam2.configure(config)
picam2.start()
time.sleep(2)  # Camera warm-up time

# Visualization params
fps_avg_frame_count = 10
text_color = (0, 0, 0)  # black for text
font_size = 1
font_thickness = 1
row_size = 50
left_margin = 24

with mp_hands.Hands(
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
    max_num_hands=1
) as hands:

    while True:
        # Capture frame as RGB array
        frame = picam2.capture_array()

        # Convert RGB to BGR for OpenCV processing and MediaPipe drawing
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        frame_bgr = cv2.flip(frame_bgr, 1)  # flip horizontally for mirror effect

        # Convert BGR to RGB for MediaPipe processing
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Process with MediaPipe Hands
        results = hands.process(rgb_frame)

        # Update and calculate FPS
        COUNTER += 1
        if COUNTER % fps_avg_frame_count == 0:
            FPS = fps_avg_frame_count / (time.time() - START_TIME)
            START_TIME = time.time()

        # Put FPS text on image
        fps_text = f'FPS = {FPS:.1f}'
        cv2.putText(frame_bgr, fps_text, (left_margin, row_size),
                    cv2.FONT_HERSHEY_DUPLEX, font_size,
                    text_color, font_thickness, cv2.LINE_AA)

        # Draw hand landmarks if detected
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(
                    frame_bgr,
                    hand_landmarks,
                    mp_hands.HAND_CONNECTIONS,
                    mp_drawing_styles.get_default_hand_landmarks_style(),
                    mp_drawing_styles.get_default_hand_connections_style()
                )

        # Show the annotated frame in a window
        cv2.imshow('MediaPipe Hand Landmarks', frame_bgr)

        # Exit on ESC key
        if cv2.waitKey(1) & 0xFF == 27:
            break

# Cleanup
cv2.destroyAllWindows()
picam2.stop()
