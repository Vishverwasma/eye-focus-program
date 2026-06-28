import cv2
import mediapipe as mp
import numpy as np
from typing import Tuple, Dict
import logging

logger = logging.getLogger(__name__)


class EyeTracker:
    """
    Handles eye detection and gaze direction estimation using MediaPipe.
    Determines if user is looking at screen or looking away.
    """
    
    def __init__(self, gaze_threshold: float = 0.15):
        """
        Initialize eye tracker with MediaPipe Face Mesh
        
        Args:
            gaze_threshold: Threshold for detecting eyes looking away (0-1)
                           Higher = more lenient, lower = stricter
        """
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        self.gaze_threshold = gaze_threshold
        
        # Eye landmark indices
        self.RIGHT_EYE = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398]
        self.LEFT_EYE = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246]
        
        self.frame_count = 0
        self.eyes_off_screen_count = 0
    
    def __del__(self):
        """Cleanup MediaPipe resources on deletion"""
        try:
            if hasattr(self, 'face_mesh') and self.face_mesh:
                self.face_mesh.close()
                logger.debug("MediaPipe FaceMesh closed")
        except Exception as e:
            logger.warning(f"Error closing FaceMesh: {e}")
    
    def close(self):
        """Explicitly close MediaPipe resources"""
        try:
            if self.face_mesh:
                self.face_mesh.close()
                self.face_mesh = None
                logger.info("Eye tracker resources released")
        except Exception as e:
            logger.error(f"Error releasing resources: {e}")
    
    def process_frame(self, frame: np.ndarray) -> Dict:
        """
        Process a frame to detect eyes and estimate gaze direction
        
        Args:
            frame: Input video frame (BGR format)
            
        Returns:
            Dictionary containing:
                - looking_at_screen: bool
                - left_eye_open: bool
                - right_eye_open: bool
                - gaze_direction: str ('center', 'left', 'right', 'up', 'down')
                - landmarks: face landmarks or None
                - confidence: float (0-1)
                - face_detected: bool
        """
        self.frame_count += 1
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        results = self.face_mesh.process(frame_rgb)
        frame_rgb.flags.writeable = True
        
        result = {
            'looking_at_screen': True,
            'left_eye_open': False,
            'right_eye_open': False,
            'gaze_direction': 'center',
            'landmarks': None,
            'confidence': 0.0,
            'face_detected': False
        }
        
        if not results.multi_face_landmarks:
            self.eyes_off_screen_count += 1
            if self.eyes_off_screen_count > 5:
                result['looking_at_screen'] = False
            return result
        
        # Reset counter when face is detected
        self.eyes_off_screen_count = 0
        landmarks = results.multi_face_landmarks[0]
        result['landmarks'] = landmarks
        result['face_detected'] = True
        
        # Extract eye aspect ratio and gaze direction
        h, w = frame.shape[:2]
        left_eye_aspect = self._calculate_eye_aspect_ratio(landmarks.landmark, self.LEFT_EYE)
        right_eye_aspect = self._calculate_eye_aspect_ratio(landmarks.landmark, self.RIGHT_EYE)
        
        result['left_eye_open'] = left_eye_aspect > 0.1
        result['right_eye_open'] = right_eye_aspect > 0.1
        
        # Estimate gaze direction
        gaze_direction, looking_at_screen, confidence = self._estimate_gaze_direction(
            landmarks.landmark, 
            frame.shape
        )
        
        result['gaze_direction'] = gaze_direction
        result['looking_at_screen'] = looking_at_screen
        result['confidence'] = confidence
        
        return result
    
    def _calculate_eye_aspect_ratio(self, landmarks, eye_indices: list) -> float:
        """Calculate aspect ratio of eye to detect if open or closed"""
        points = np.array([[landmarks[i].x, landmarks[i].y] for i in eye_indices])
        
        # Calculate vertical distances
        A = np.linalg.norm(points[1] - points[5])
        B = np.linalg.norm(points[2] - points[4])
        
        # Calculate horizontal distance
        C = np.linalg.norm(points[0] - points[3])
        
        # Aspect ratio
        ear = (A + B) / (2.0 * C) if C != 0 else 0
        return ear
    
    def _estimate_gaze_direction(self, landmarks, frame_shape: Tuple) -> Tuple[str, bool, float]:
        """
        Estimate where user is looking using iris position relative to eye bounds
        
        Returns:
            (gaze_direction, looking_at_screen, confidence)
        """
        h, w = frame_shape[:2]
        
        # Get iris center (using landmark 468 - right iris, 473 - left iris)
        right_iris = np.array([landmarks[468].x, landmarks[468].y])
        left_iris = np.array([landmarks[473].x, landmarks[473].y])
        
        # Get eye bounds
        right_eye_right = np.array([landmarks[362].x, landmarks[362].y])
        right_eye_left = np.array([landmarks[263].x, landmarks[263].y])
        right_eye_top = np.array([landmarks[386].x, landmarks[386].y])
        right_eye_bottom = np.array([landmarks[374].x, landmarks[374].y])
        
        left_eye_right = np.array([landmarks[33].x, landmarks[33].y])
        left_eye_left = np.array([landmarks[133].x, landmarks[133].y])
        left_eye_top = np.array([landmarks[159].x, landmarks[159].y])
        left_eye_bottom = np.array([landmarks[145].x, landmarks[145].y])
        
        # Calculate normalized iris position within eye (0-1, where 0.5 is center)
        right_h_ratio = (right_iris[0] - right_eye_left[0]) / (right_eye_right[0] - right_eye_left[0]) if right_eye_right[0] != right_eye_left[0] else 0.5
        right_v_ratio = (right_iris[1] - right_eye_top[1]) / (right_eye_bottom[1] - right_eye_top[1]) if right_eye_bottom[1] != right_eye_top[1] else 0.5
        
        left_h_ratio = (left_iris[0] - left_eye_left[0]) / (left_eye_right[0] - left_eye_left[0]) if left_eye_right[0] != left_eye_left[0] else 0.5
        left_v_ratio = (left_iris[1] - left_eye_top[1]) / (left_eye_bottom[1] - left_eye_top[1]) if left_eye_bottom[1] != left_eye_top[1] else 0.5
        
        # Average both eyes
        avg_h_ratio = (right_h_ratio + left_h_ratio) / 2
        avg_v_ratio = (right_v_ratio + left_v_ratio) / 2
        
        # Determine gaze direction
        gaze_direction = 'center'
        looking_at_screen = True
        
        if avg_h_ratio < (0.5 - self.gaze_threshold):
            gaze_direction = 'left'
            looking_at_screen = False
        elif avg_h_ratio > (0.5 + self.gaze_threshold):
            gaze_direction = 'right'
            looking_at_screen = False
        elif avg_v_ratio < (0.5 - self.gaze_threshold):
            gaze_direction = 'up'
            looking_at_screen = False
        elif avg_v_ratio > (0.5 + self.gaze_threshold):
            gaze_direction = 'down'
            looking_at_screen = False
        
        # Confidence is based on how extreme the gaze is
        confidence = max(abs(avg_h_ratio - 0.5), abs(avg_v_ratio - 0.5))
        
        return gaze_direction, looking_at_screen, confidence
    
    def draw_eye_tracking(self, frame: np.ndarray, tracking_data: Dict) -> np.ndarray:
        """Draw eye tracking visualization on frame"""
        h, w = frame.shape[:2]
        
        if tracking_data.get('landmarks'):
            landmarks = tracking_data['landmarks'].landmark
            
            # Draw eye circles
            for eye_indices in [self.LEFT_EYE, self.RIGHT_EYE]:
                points = np.array([[int(landmarks[i].x * w), int(landmarks[i].y * h)] for i in eye_indices])
                cv2.polylines(frame, [points], True, (0, 255, 0), 2)
        
        # Draw status text
        if tracking_data.get('face_detected'):
            status_text = "Looking at screen" if tracking_data['looking_at_screen'] else f"Looking {tracking_data['gaze_direction']}"
            color = (0, 255, 0) if tracking_data['looking_at_screen'] else (0, 0, 255)
            cv2.putText(frame, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
        else:
            cv2.putText(frame, "No face detected", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        return frame
