import cv2
import argparse
import logging
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from camera_source import CameraSourceManager
from virtual_camera import VirtualCameraPublisher
from eye_tracker import EyeTracker
from call_detector import CallRecordingDetector
from alert_system import AlertSystem

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('eye_focus_monitor.log', encoding='utf-8'),
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
        enable_virtual_camera: bool = True,
        frame_width: Optional[int] = None,
        frame_height: Optional[int] = None,
    ):
        """
        Initialize the Eye Focus Monitor
        
        Args:
            camera_id: Explicit camera device ID. If omitted, the app scans for
                a usable physical, virtual, or shared camera source.
            prefer_camera_name: Optional text to prefer in the discovered source.
            exclude_camera_names: Optional source-name fragments to avoid.
            camera_scan_limit: Highest camera index to scan.
            enable_virtual_camera: Publish processed frames to a virtual camera if available.
        """
        logger.info("Initializing Eye Focus Monitor...")
        
        self.camera_id = camera_id
        self.prefer_camera_name = prefer_camera_name
        self.exclude_camera_names = exclude_camera_names or []
        self.camera_manager = CameraSourceManager(
            max_index=camera_scan_limit,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        self.cap, self.camera_device = self.camera_manager.open_preferred(
            camera_id=camera_id,
            prefer_name=prefer_camera_name,
            exclude_names=self.exclude_camera_names,
        )
        self.camera_id = self.camera_device.index
        self.enable_virtual_camera = enable_virtual_camera
        self.virtual_camera = None
        self._initialize_virtual_camera()
        
        # Initialize components
        self.eye_tracker = EyeTracker(gaze_threshold=0.15)
        self.call_detector = CallRecordingDetector()
        self.alert_system = AlertSystem()
        
        # Statistics
        self.frame_count = 0
        self.alerts_triggered = 0
        self.session_start = datetime.now()

        # Gaze logging state (so we log events, not every frame)
        self._was_looking_away = False
        self._last_gaze_direction = None
        self._look_away_count = 0
        
        logger.info("Eye Focus Monitor initialized successfully")
    
    def _initialize_virtual_camera(self):
        """Create a virtual camera publisher when the dependency is available."""
        if not self.enable_virtual_camera:
            return

        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or self.camera_device.width or 1280
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or self.camera_device.height or 720
        fps = int(self.cap.get(cv2.CAP_PROP_FPS) or 0) or int(self.camera_device.fps or 30) or 30

        try:
            self.virtual_camera = VirtualCameraPublisher(width=width, height=height, fps=fps)
            logger.info("=" * 60)
            logger.info("MIDDLEWARE ACTIVE - sharing your processed camera feed")
            logger.info("In Zoom / Teams / Meet / OBS, pick this camera device:")
            logger.info("    >>> %s <<<", self.virtual_camera.device)
            logger.info("Those apps will then receive the PROCESSED feed.")
            logger.info("=" * 60)
        except Exception as e:
            self.virtual_camera = None
            logger.warning(
                "Virtual camera output disabled: %s. "
                "Install a virtual-camera backend (e.g. OBS Virtual Camera) so apps "
                "can consume the processed feed. The local monitor window still works.",
                e,
            )

    def _log_gaze(self, tracking_data):
        """
        Console-log gaze events: when the user looks away (and in which
        direction), when the direction changes, and when they return.
        Logged on transitions only - not every frame - to avoid flooding.
        """
        if not tracking_data.get('face_detected'):
            return

        looking_at_screen = tracking_data.get('looking_at_screen', True)
        direction = (tracking_data.get('gaze_direction') or 'center').upper()

        if not looking_at_screen:
            new_event = not self._was_looking_away
            changed_direction = direction != self._last_gaze_direction
            if new_event or changed_direction:
                if new_event:
                    self._look_away_count += 1
                logger.info(
                    "[GAZE] Looking AWAY -> %s (event #%d)",
                    direction, self._look_away_count,
                )
            self._was_looking_away = True
            self._last_gaze_direction = direction
        else:
            if self._was_looking_away:
                logger.info("[GAZE] Back ON screen")
            self._was_looking_away = False
            self._last_gaze_direction = None

    def _publish_virtual_camera(self, frame):
        """Send the processed frame to the virtual camera if one is available."""
        if self.virtual_camera is None:
            return

        try:
            self.virtual_camera.publish(frame)
        except Exception as e:
            logger.error(f"Virtual camera publish failed: {e}")
            self.virtual_camera = None

    def run(self):
        """Main application loop"""
        logger.info("Starting Eye Focus Monitor - Press 'Q' to quit")
        
        retry_count = 0
        max_retries = 10

        try:
            while True:
                ret, frame = self.cap.read()

                if not ret:
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Failed to read frame, retrying... ({retry_count}/{max_retries})")
                        time.sleep(0.05)  # let the camera deliver the next frame
                        continue  # Retry instead of immediately exiting
                    logger.warning("Camera read failed after retries; re-opening the same device (shared)")
                    self.cap.release()

                    # Stay on the SAME physical camera - a hiccup or another app
                    # briefly touching it should not make us abandon the device
                    # the user pointed their apps at.
                    same_cap = self.camera_manager.reopen_same(self.camera_device)
                    if same_cap is not None:
                        self.cap = same_cap
                        retry_count = 0
                        continue

                    # Only if the device is genuinely gone (unplugged) do we
                    # fall back to any other usable source.
                    logger.warning("Same device unavailable; looking for any other usable camera")
                    replacement_cap, replacement_device = self.camera_manager.reopen_after_failure(
                        current_index=self.camera_id,
                        prefer_name=self.prefer_camera_name,
                        exclude_names=self.exclude_camera_names,
                    )
                    if replacement_cap is None:
                        logger.error("No replacement camera source is available")
                        break

                    self.cap = replacement_cap
                    self.camera_device = replacement_device
                    self.camera_id = replacement_device.index
                    retry_count = 0
                    continue
                
                retry_count = 0  # Reset retry counter on successful read
                self.frame_count += 1
                
                # Get eye tracking data
                tracking_data = self.eye_tracker.process_frame(frame)

                # Console-log look-away events and direction
                self._log_gaze(tracking_data)

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
                self._publish_virtual_camera(frame)
                
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

        # Stop the background call-detection thread
        try:
            if hasattr(self, 'call_detector'):
                self.call_detector.close()
        except Exception as e:
            logger.error(f"Error closing call detector: {e}")
        
        # Release virtual camera
        try:
            if self.virtual_camera is not None:
                self.virtual_camera.close()
        except Exception as e:
            logger.error(f"Error closing virtual camera: {e}")

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
    parser.add_argument(
        "--check-backend",
        action="store_true",
        help="Check whether a virtual-camera backend is installed and exit.",
    )
    parser.add_argument(
        "--no-virtual-camera",
        dest="virtual_camera",
        action="store_false",
        help="Disable publishing processed frames to a virtual camera.",
    )
    parser.add_argument(
        "--resolution",
        default=None,
        metavar="WIDTHxHEIGHT",
        help="Request a capture resolution, e.g. 1280x720. Omit to use the "
             "camera's native mode (faster startup; forcing a resolution can "
             "add several seconds on some webcams).",
    )
    parser.set_defaults(virtual_camera=True)
    return parser.parse_args()


def parse_resolution(value):
    """Parse 'WIDTHxHEIGHT' into (width, height), or (None, None) if unset."""
    if not value:
        return None, None
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        raise SystemExit(f"Invalid --resolution '{value}'. Use e.g. 1280x720.")


def check_backend() -> bool:
    """Report whether the virtual-camera backend is ready. Returns True if ok."""
    ok, detail = VirtualCameraPublisher.probe()
    if ok:
        print(f"Virtual-camera backend: OK -> apps should select '{detail}'")
    else:
        print(f"Virtual-camera backend: NOT READY -> {detail}")
    return ok


def list_cameras(scan_limit: int):
    manager = CameraSourceManager(max_index=scan_limit)
    devices = manager.scan()
    if not devices:
        print("No usable camera sources were found.")
    else:
        print("Usable camera sources:")
        for device in devices:
            print(
                f"  [{device.index}] {device.name} | {device.backend_name} | "
                f"{device.width}x{device.height} @ {device.fps:.1f} FPS"
            )

    print()
    check_backend()


if __name__ == "__main__":
    try:
        args = parse_args()
        if args.check_backend:
            sys.exit(0 if check_backend() else 1)
        if args.list_cameras:
            list_cameras(args.scan_limit)
            sys.exit(0)

        # Pre-flight: the whole point of this app is to publish a processed feed
        # to a virtual camera. If that's requested but no backend is installed,
        # refuse to launch with a clear message instead of silently starting in
        # a local-only mode the user did not ask for.
        if args.virtual_camera:
            backend_ok, backend_detail = VirtualCameraPublisher.probe()
            if not backend_ok:
                print("Cannot start: virtual-camera backend is not ready.")
                print(f"  Reason: {backend_detail}")
                print("  Fix:    install a virtual-camera driver (the OBS Virtual Camera")
                print("          that ships with OBS Studio is the easiest on Windows),")
                print("          or re-run with --no-virtual-camera for a local-only window.")
                sys.exit(2)

        frame_width, frame_height = parse_resolution(args.resolution)
        monitor = EyeFocusMonitor(
            camera_id=args.camera,
            prefer_camera_name=args.prefer_name,
            exclude_camera_names=args.exclude_name,
            camera_scan_limit=args.scan_limit,
            enable_virtual_camera=args.virtual_camera,
            frame_width=frame_width,
            frame_height=frame_height,
        )
        monitor.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
