import cv2
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional
from camera_source import CameraSourceManager
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
    
    def __init__(
        self,
        camera_id: Optional[int] = None,
        prefer_camera_name: Optional[str] = None,
        exclude_camera_names: Optional[list] = None,
        camera_scan_limit: int = 10,
    ):
        """
        Initialize the Eye Focus Monitor
        
        Args:
            camera_id: Explicit camera device ID. If omitted, the app scans for
                a usable physical, virtual, or shared camera source.
            prefer_camera_name: Optional text to prefer in the discovered source.
            exclude_camera_names: Optional source-name fragments to avoid.
            camera_scan_limit: Highest camera index to scan.
        """
        logger.info("Initializing Eye Focus Monitor...")
        
        self.camera_id = camera_id
        self.prefer_camera_name = prefer_camera_name
        self.exclude_camera_names = exclude_camera_names or []
        self.camera_manager = CameraSourceManager(max_index=camera_scan_limit)
        self.cap, self.camera_device = self.camera_manager.open_preferred(
            camera_id=camera_id,
            prefer_name=prefer_camera_name,
            exclude_names=self.exclude_camera_names,
        )
        self.camera_id = self.camera_device.index
        
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
        
        retry_count = 0
        max_retries = 3
        
        try:
            while True:
                ret, frame = self.cap.read()
                
                if not ret:
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Failed to read frame, retrying... ({retry_count}/{max_retries})")
                        continue  # Retry instead of immediately exiting
                    logger.warning("Camera read failed after retries; scanning for another source")
                    replacement_cap, replacement_device = self.camera_manager.reopen_after_failure(
                        current_index=self.camera_id,
                        prefer_name=self.prefer_camera_name,
                        exclude_names=self.exclude_camera_names,
                    )
                    if replacement_cap is None:
                        logger.error("No replacement camera source is available")
                        break

                    self.cap.release()
                    self.cap = replacement_cap
                    self.camera_device = replacement_device
                    self.camera_id = replacement_device.index
                    retry_count = 0
                    continue
                
                retry_count = 0  # Reset retry counter on successful read
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
        status_text = call_status.get('status_text', 'Unknown')
        status_color = (0, 0, 255) if call_status.get('any_action') else (0, 255, 0)
        cv2.putText(overlay, f"Status: {status_text}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2)
        
        # Draw eye tracking status (top-right)
        if tracking_data.get('face_detected'):
            gaze_dir = tracking_data.get('gaze_direction', 'center').upper()
            eye_status = "👀 LOOKING AT SCREEN" if tracking_data.get('looking_at_screen') else f"👀 LOOKING {gaze_dir}"
            eye_color = (0, 255, 0) if tracking_data.get('looking_at_screen') else (0, 0, 255)
            cv2.putText(overlay, eye_status, (w - 350, 30),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, eye_color, 2)
        
        # Draw face detection status
        face_status = "✓ Face detected" if tracking_data.get('face_detected') else "✗ NO FACE"
        face_color = (0, 255, 0) if tracking_data.get('face_detected') else (0, 0, 255)
        cv2.putText(overlay, face_status, (10, 70),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, face_color, 2)
        
        # Draw frame count and alerts
        cv2.putText(overlay, f"Frame: {self.frame_count}", (10, h - 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        cv2.putText(overlay, f"Alerts: {self.alerts_triggered}", (w - 150, h - 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
        
        # Draw alert message if active
        if alert_data.get('should_alert'):
            alert_severity = alert_data.get('severity', 'low')
            alert_color = (0, 255, 255) if alert_severity == 'medium' else (0, 0, 255)
            alert_message = alert_data.get('message', 'Alert!')
            
            # Draw alert box
            alert_y = h // 2
            text_size = cv2.getTextSize(alert_message, cv2.FONT_HERSHEY_SIMPLEX, 1, 2)[0]
            box_coords = (w // 2 - text_size[0] // 2 - 10, alert_y - text_size[1] - 20,
                         w // 2 + text_size[0] // 2 + 10, alert_y + 20)
            
            cv2.rectangle(overlay, (box_coords[0], box_coords[1]), 
                         (box_coords[2], box_coords[3]), alert_color, -1)
            cv2.putText(overlay, alert_message, (w // 2 - text_size[0] // 2, alert_y),
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
        
        # Close eye tracker resources
        try:
            if hasattr(self, 'eye_tracker'):
                self.eye_tracker.close()
        except Exception as e:
            logger.error(f"Error closing eye tracker: {e}")
        
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


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor gaze during calls and recordings.")
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Use a specific camera index. Omit to auto-select a working source.",
    )
    parser.add_argument(
        "--prefer-name",
        default=None,
        help="Prefer a camera source containing this text, for example 'Logitech' or 'NVIDIA'.",
    )
    parser.add_argument(
        "--exclude-name",
        action="append",
        default=[],
        help="Avoid camera sources containing this text. Can be used multiple times.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=10,
        help="Highest camera index to scan when auto-selecting.",
    )
    parser.add_argument(
        "--list-cameras",
        action="store_true",
        help="List usable OpenCV camera sources and exit.",
    )
    return parser.parse_args()


def list_cameras(scan_limit: int):
    manager = CameraSourceManager(max_index=scan_limit)
    devices = manager.scan()
    if not devices:
        print("No usable camera sources were found.")
        return

    print("Usable camera sources:")
    for device in devices:
        print(
            f"  [{device.index}] {device.name} | {device.backend_name} | "
            f"{device.width}x{device.height} @ {device.fps:.1f} FPS"
        )


if __name__ == "__main__":
    try:
        args = parse_args()
        if args.list_cameras:
            list_cameras(args.scan_limit)
            sys.exit(0)

        monitor = EyeFocusMonitor(
            camera_id=args.camera,
            prefer_camera_name=args.prefer_name,
            exclude_camera_names=args.exclude_name,
            camera_scan_limit=args.scan_limit,
        )
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

