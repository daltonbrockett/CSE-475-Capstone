import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from mediapipe.framework.formats import landmark_pb2
import time
from picamera2 import Picamera2

def create_recognizer(min_det_conf=0.5, min_track_conf=0.5):
    model_path = "gesture_recognizer.task"
    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.GestureRecognizerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=min_det_conf,
        min_hand_presence_confidence=min_det_conf,
        min_tracking_confidence=min_track_conf
    )
    return vision.GestureRecognizer.create_from_options(options)

def main():
    min_det_conf = 0.7
    min_track_conf = 0.7

    print("Starting calibration...")
    print("Controls:")
    print("  Increase detection confidence:     d")
    print("  Decrease detection confidence:     f")
    print("  Increase tracking confidence:      t")
    print("  Decrease tracking confidence:      g")
    print("Press ESC to exit.")

    picam2 = Picamera2()
    config = picam2.create_video_configuration(main={"size": (320, 240), "format": "RGB888"})
    picam2.configure(config)
    picam2.start()
    time.sleep(2)

    recognizer = create_recognizer(min_det_conf, min_track_conf)
    mp_drawing = mp.solutions.drawing_utils
    mp_hands = mp.solutions.hands

    try:
        while True:
            image = picam2.capture_array()
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=image)
            timestamp_ms = int(time.time() * 1000)
            result = recognizer.recognize_for_video(mp_image, timestamp_ms)

            image_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

            # Show detected gestures and scores, draw landmarks
            if result and result.gestures and result.hand_landmarks:
                for hand_idx, hand_landmarks in enumerate(result.hand_landmarks):
                    gestures_for_hand = result.gestures[hand_idx]
                    if gestures_for_hand:
                        gesture = gestures_for_hand[0]
                        category = gesture.category_name
                        score = gesture.score
                        cv2.putText(image_bgr, f'{category}: {score:.2f}', (10, 30 + 30*hand_idx),
                                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 2)

                    # Convert landmarks list to protobuf message for drawing
                    hand_proto = landmark_pb2.NormalizedLandmarkList()
                    hand_proto.landmark.extend(
                        [landmark_pb2.NormalizedLandmark(x=lm.x, y=lm.y, z=lm.z) for lm in hand_landmarks]
                    )
                    mp_drawing.draw_landmarks(
                        image_bgr,
                        hand_proto,
                        mp_hands.HAND_CONNECTIONS)

            # Show current confidence thresholds
            cv2.putText(image_bgr, f'Detect Conf: {min_det_conf:.2f}', (10, 200),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
            cv2.putText(image_bgr, f'Track Conf : {min_track_conf:.2f}', (10, 230),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)

            cv2.imshow("Calibration - Adjust thresholds", image_bgr)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:  # ESC key to quit
                break
            elif key == ord('d'):
                min_det_conf = min(min_det_conf + 0.05, 1.0)
            elif key == ord('f'):
                min_det_conf = max(min_det_conf - 0.05, 0.0)
            elif key == ord('t'):
                min_track_conf = min(min_track_conf + 0.05, 1.0)
            elif key == ord('g'):
                min_track_conf = max(min_track_conf - 0.05, 0.0)
            else:
                continue

            # Recreate recognizer with new confidence values
            recognizer.close()
            recognizer = create_recognizer(min_det_conf, min_track_conf)

    finally:
        recognizer.close()
        picam2.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
