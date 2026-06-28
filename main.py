import cv2
import logging
import sys
from pathlib import Path
from datetime import datetime
from eye_tracker import EyeTracker
from call_detector import CallRecordingDetector
from alert_system import AlertSystem

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('eye_focus_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class EyeFocusMonitor:
    """
    Main application class that coordinates eye tracking, call detection, and alerts.
    """
    
    def __init__(self, camera_id: int = 0):
        """
        Initialize the Eye Focus Monitor
        
        Args:
            camera_id: Camera device ID (0 for default camera)
        """
        logger.info("Initializing Eye Focus Monitor...")
        
        self.camera_id = camera_id
        self.cap = cv2.VideoCapture(camera_id)
        
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera {camera_id}")
        
        # Set camera properties
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
        # Initialize components
        self.eye_tracker = EyeTracker(gaze_threshold=0.15)
        self.call_detector = CallRecordingDetector()
        self.alert_system = AlertSystem()
        
        # Statistics
        self.frame_count = 0
        self.alerts_triggered = 0
        self.session_start = datetime.now()
        
        logger.info("Eye Focus Monitor initialized successfully")
    
    def run(self):
        """Main application loop"""
        logger.info("Starting Eye Focus Monitor - Press 'Q' to quit")
        
        try:
            while True:
                ret, frame = self.cap.read()
                
                if not ret:
                    logger.error("Failed to read frame from camera")
                    break
                
                self.frame_count += 1
                
                # Get eye tracking data
                tracking_data = self.eye_tracker.process_frame(frame)
                
                # Get call/recording status
                call_status = self.call_detector.get_status()
                
                # Check for alerts
                alert_data = self.alert_system.check_and_trigger_alert(
                    in_call_or_recording=call_status['any_action'],
                    looking_at_screen=tracking_data['looking_at_screen'],
                    face_detected=tracking_data['face_detected'],
                    call_app=call_status['call_app'],
                    recording_app=call_status['recording_app']
                )
                
                # Trigger alert if needed
                if alert_data['should_alert']:
                    self.alerts_triggered += 1
                    logger.warning(f"ALERT: {alert_data['message']}")
                    self.alert_system.play_alert_sequence(alert_data['alert_type'])
                
                # Draw visualization
                frame = self._draw_visualization(frame, tracking_data, call_status, alert_data)
                
                # Display frame
                cv2.imshow('Eye Focus Monitor', frame)
                
                # Handle keyboard input
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == ord('Q'):
                    logger.info("User requested exit")
                    break
                elif key == ord('s') or key == ord('S'):
                    self._save_screenshot(frame)
                elif key == ord('r') or key == ord('R'):
                    logger.info("Resetting statistics...")
                    self.alert_system.alert_history = []
                    self.alerts_triggered = 0
        
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.shutdown()
    
    def _draw_visualization(self, frame, tracking_data, call_status, alert_data):
        """Draw all visualization elements on frame"""
        h, w = frame.shape[:2]
        
        # Create semi-transparent overlay for UI
        overlay = frame.copy()
        
        # Draw call/recording status (top-left)
        status_text = call_status['status_text']
        status_color = (0, 0, 255) if call_status['any_action'] else (0, 255, 0)
        cv2.putText(overlay, f"Status: {status_text}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        
        # Draw eye tracking status (top-right)
        eye_status = "👀 LOOKING AT SCREEN" if tracking_data['looking_at_screen'] else f"👀 LOOKING {tracking_data['gaze_direction'].upper()}"
        eye_color = (0, 255, 0) if tracking_data['looking_at_screen'] else (0, 0, 255)
        cv2.putText(overlay, eye_status, (w - 350, 30),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, eye_color, 2)
        
        # Draw face detection status
        face_status = "✓ Face detected" if tracking_data['face_detected'] else "✗ NO FACE"
        face_color = (0, 255, 0) if tracking_data['face_detected'] else (0, 0, 255)
        cv2.putText(overlay, face_status, (10, 70),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, face_color, 2)
        
        # Draw frame count and alerts
        cv2.putText(overlay, f"Frame: {self.frame_count}", (10, h - 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(overlay, f"Alerts: {self.alerts_triggered}", (w - 150, h - 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        
        # Draw alert message if active
        if alert_data['should_alert']:
            alert_color = (0, 255, 255) if alert_data['severity'] == 'medium' else (0, 0, 255)
            
            # Draw alert box
            alert_y = h // 2
            text_size = cv2.getTextSize(alert_data['message'], cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]
            box_coords = (w // 2 - text_size[0] // 2 - 10, alert_y - text_size[1] - 20,
                         w // 2 + text_size[0] // 2 + 10, alert_y + 20)
            
            cv2.rectangle(overlay, (box_coords[0], box_coords[1]), 
                         (box_coords[2], box_coords[3]), alert_color, -1)
            cv2.putText(overlay, alert_data['message'], (w // 2 - text_size[0] // 2, alert_y),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        
        # Draw eye tracking overlay
        frame = self.eye_tracker.draw_eye_tracking(overlay, tracking_data)
        
        # Blend overlay
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        
        return frame
    
    def _save_screenshot(self, frame):
        """Save screenshot"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        cv2.imwrite(filename, frame)
        logger.info(f"Screenshot saved: {filename}")
    
    def shutdown(self):
        """Cleanup and shutdown"""
        logger.info("Shutting down Eye Focus Monitor...")
        
        # Print statistics
        self._print_session_stats()
        
        # Release camera
        self.cap.release()
        cv2.destroyAllWindows()
        
        logger.info("Eye Focus Monitor stopped")
    
    def _print_session_stats(self):
        """Print session statistics"""
        session_duration = datetime.now() - self.session_start
        stats = self.alert_system.get_statistics()
        
        logger.info("=" * 50)
        logger.info("SESSION STATISTICS")
        logger.info("=" * 50)
        logger.info(f"Duration: {session_duration}")
        logger.info(f"Frames processed: {self.frame_count}")
        logger.info(f"Total alerts: {self.alerts_triggered}")
        logger.info(f"Alert breakdown: {stats['by_severity']}")
        logger.info(f"Alerts by app: {stats['by_app']}")
        logger.info("=" * 50)


if __name__ == "__main__":
    try:
        monitor = EyeFocusMonitor(camera_id=0)
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
