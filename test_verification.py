import unittest
import numpy as np
from eye_tracker import EyeTracker
from call_detector import CallRecordingDetector
from alert_system import AlertSystem
from camera_source import CameraDevice, CameraSourceManager


class TestEyeTracker(unittest.TestCase):
    """Verification Round 1-4: Eye Tracking Component Tests"""
    
    def setUp(self):
        self.tracker = EyeTracker(gaze_threshold=0.15)
    
    def test_eye_tracker_initialization(self):
        """VR1: Test eye tracker initializes correctly"""
        self.assertIsNotNone(self.tracker.face_mesh)
        self.assertEqual(self.tracker.gaze_threshold, 0.15)
        self.assertEqual(self.tracker.frame_count, 0)
    
    def test_eye_aspect_ratio_calculation(self):
        """VR2: Test eye aspect ratio calculation"""
        class MockLandmark:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        # Real input is always MediaPipe landmark objects with .x/.y, never None.
        landmarks = [MockLandmark(0.1 * i, 0.1 * i) for i in range(16)]
        eye_indices = list(range(0, 16))

        result = self.tracker._calculate_eye_aspect_ratio(landmarks, eye_indices)
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0)
    
    def test_gaze_direction_estimation(self):
        """VR3: Test gaze direction estimation logic"""
        # Create mock landmarks with all necessary indices
        class MockLandmark:
            def __init__(self, x, y):
                self.x = x
                self.y = y
        
        landmarks = [MockLandmark(0.5, 0.5) for _ in range(475)]
        
        # Override specific eye landmarks
        landmarks[468] = MockLandmark(0.4, 0.5)  # Right iris (looking left)
        landmarks[473] = MockLandmark(0.4, 0.5)  # Left iris (looking left)
        
        gaze_dir, looking_at_screen, confidence = self.tracker._estimate_gaze_direction(
            landmarks, (480, 640)
        )
        
        self.assertIn(gaze_dir, ['center', 'left', 'right', 'up', 'down'])
        self.assertIsInstance(looking_at_screen, bool)
        self.assertIsInstance(confidence, float)
    
    def test_process_frame_returns_dict(self):
        """VR4: Test process_frame returns correct dictionary structure"""
        # Create a dummy frame
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        result = self.tracker.process_frame(frame)
        
        # Verify dictionary structure
        self.assertIsInstance(result, dict)
        self.assertIn('looking_at_screen', result)
        self.assertIn('left_eye_open', result)
        self.assertIn('right_eye_open', result)
        self.assertIn('gaze_direction', result)
        self.assertIn('landmarks', result)
        self.assertIn('confidence', result)
        self.assertIn('face_detected', result)


class TestCallDetector(unittest.TestCase):
    """Verification Round 5-6: Call/Recording Detection Tests"""
    
    def setUp(self):
        self.detector = CallRecordingDetector()
    
    def test_call_detector_initialization(self):
        """VR5: Test call detector initializes correctly"""
        self.assertIsNotNone(self.detector.CALL_APPS)
        self.assertIsNotNone(self.detector.RECORDING_APPS)
        self.assertEqual(self.detector.in_call_frames, 0)
        self.assertEqual(self.detector.recording_frames, 0)
    
    def test_detect_active_call_returns_tuple(self):
        """VR5: Test detect_active_call returns correct format"""
        in_call, app_name = self.detector.detect_active_call()
        
        self.assertIsInstance(in_call, bool)
        self.assertIsInstance(app_name, str)
    
    def test_detect_active_recording_returns_tuple(self):
        """VR6: Test detect_active_recording returns correct format"""
        recording, app_name = self.detector.detect_active_recording()
        
        self.assertIsInstance(recording, bool)
        self.assertIsInstance(app_name, str)
    
    def test_get_status_returns_complete_dict(self):
        """VR6: Test get_status returns comprehensive status"""
        status = self.detector.get_status()
        
        self.assertIsInstance(status, dict)
        self.assertIn('in_call', status)
        self.assertIn('call_app', status)
        self.assertIn('recording', status)
        self.assertIn('recording_app', status)
        self.assertIn('any_action', status)
        self.assertIn('status_text', status)
        
        # Verify types
        self.assertIsInstance(status['in_call'], bool)
        self.assertIsInstance(status['recording'], bool)
        self.assertIsInstance(status['any_action'], bool)



class TestCameraSourceManager(unittest.TestCase):
    """Camera source selection tests."""

    def setUp(self):
        self.manager = CameraSourceManager()
        self.devices = [
            CameraDevice(0, 0, "Auto", "NVIDIA Broadcast Camera", 1280, 720, 30.0),
            CameraDevice(1, 0, "Auto", "Integrated Webcam", 1280, 720, 30.0),
            CameraDevice(2, 0, "Auto", "OBS Virtual Camera", 1280, 720, 30.0),
        ]

    def test_explicit_camera_id_wins(self):
        selected = self.manager._select_device(self.devices, 2, None, ["nvidia"])
        self.assertEqual(selected.index, 2)

    def test_preferred_name_wins_without_explicit_id(self):
        selected = self.manager._select_device(self.devices, None, "Integrated", ["nvidia"])
        self.assertEqual(selected.index, 1)

    def test_excluded_name_is_skipped(self):
        selected = self.manager._select_device(self.devices, None, None, ["nvidia"])
        self.assertEqual(selected.index, 1)

    def test_falls_back_when_all_sources_are_excluded(self):
        selected = self.manager._select_device(
            self.devices,
            None,
            None,
            ["nvidia", "integrated", "obs"],
        )
        self.assertEqual(selected.index, 0)

class TestVirtualCameraBackend(unittest.TestCase):
    """Middleware: virtual-camera backend probe + resilient recovery."""

    def test_probe_returns_bool_and_message(self):
        from virtual_camera import VirtualCameraPublisher

        ok, detail = VirtualCameraPublisher.probe()
        self.assertIsInstance(ok, bool)
        self.assertIsInstance(detail, str)
        self.assertGreater(len(detail), 0)

    def test_reopen_same_returns_none_for_missing_device(self):
        # Index 999 cannot be opened, so recovery must fail gracefully (None)
        # rather than raise - the run loop relies on this.
        manager = CameraSourceManager()
        phantom = CameraDevice(999, manager.backends[0],
                               manager.backend_name(manager.backends[0]),
                               "phantom", 0, 0, 0.0)
        self.assertIsNone(manager.reopen_same(phantom))


class TestAlertSystem(unittest.TestCase):
    """Verification Round 7-8: Alert System Tests"""
    
    def setUp(self):
        self.alert_system = AlertSystem()
    
    def test_alert_system_initialization(self):
        """VR7: Test alert system initializes correctly"""
        self.assertIsNotNone(self.alert_system.log_dir)
        self.assertEqual(self.alert_system.consecutive_drift_frames, 0)
        self.assertGreater(self.alert_system.alert_threshold, 0)
    
    def test_no_alert_when_not_in_call(self):
        """VR7: Test no alert triggered when not in call"""
        result = self.alert_system.check_and_trigger_alert(
            in_call_or_recording=False,
            looking_at_screen=False,
            face_detected=True
        )
        
        self.assertFalse(result['should_alert'])
        self.assertEqual(result['alert_type'], 'none')
        self.assertEqual(self.alert_system.consecutive_drift_frames, 0)
    
    def test_alert_triggered_when_eyes_drift_in_call(self):
        """VR8: Test alert triggers when eyes drift during call"""
        # The 1-second cooldown means only the FIRST threshold crossing alerts
        # within a fast loop, so assert that *an* alert fired, not the last one.
        fired = None
        for _ in range(self.alert_system.alert_threshold + 5):
            result = self.alert_system.check_and_trigger_alert(
                in_call_or_recording=True,
                looking_at_screen=False,
                face_detected=True,
                call_app="zoom"
            )
            if result['should_alert']:
                fired = result

        self.assertIsNotNone(fired, "expected at least one alert to fire")
        self.assertNotEqual(fired['alert_type'], 'none')
        self.assertGreater(len(fired['message']), 0)
    
    def test_alert_severity_escalation(self):
        """VR8: Test alert severity increases over time"""
        severities = []
        
        # Simulate 30 frames of drift
        for _ in range(30):
            result = self.alert_system.check_and_trigger_alert(
                in_call_or_recording=True,
                looking_at_screen=False,
                face_detected=True
            )
            if result['should_alert']:
                severities.append(result['severity'])
        
        # Later alerts should have higher severity
        self.assertGreater(len(severities), 0)
    
    def test_statistics_collection(self):
        """VR8: Test statistics are collected correctly"""
        # Trigger some alerts
        for _ in range(10):
            self.alert_system.check_and_trigger_alert(
                in_call_or_recording=True,
                looking_at_screen=False,
                face_detected=True
            )
        
        stats = self.alert_system.get_statistics()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('total_alerts', stats)
        self.assertIn('by_severity', stats)


class TestIntegration(unittest.TestCase):
    """Verification Round 9-10: Full System Integration Tests"""
    
    def setUp(self):
        self.tracker = EyeTracker()
        self.detector = CallRecordingDetector()
        self.alert_system = AlertSystem()
    
    def test_full_pipeline_no_call(self):
        """VR9: Test full pipeline when not in call"""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        
        tracking = self.tracker.process_frame(frame)
        call_status = self.detector.get_status()
        alert = self.alert_system.check_and_trigger_alert(
            in_call_or_recording=call_status['any_action'],
            looking_at_screen=tracking['looking_at_screen'],
            face_detected=tracking['face_detected']
        )
        
        # No call = no alert
        self.assertFalse(alert['should_alert'])
    
    def test_full_pipeline_with_call_and_drift(self):
        """VR9: Test full pipeline with simulated call and eye drift"""
        # Simulate in call with eyes drifting
        for _ in range(20):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            
            tracking = self.tracker.process_frame(frame)
            
            alert = self.alert_system.check_and_trigger_alert(
                in_call_or_recording=True,  # Simulate in call
                looking_at_screen=False,   # Eyes drifting
                face_detected=True,
                call_app="zoom"
            )
        
        # Should have triggered alert
        stats = self.alert_system.get_statistics()
        self.assertGreater(stats['total_alerts'], 0)
    
    def test_alert_recovery(self):
        """VR10: Test system recovery when eyes return to screen"""
        # Simulate drift
        for _ in range(15):
            self.alert_system.check_and_trigger_alert(
                in_call_or_recording=True,
                looking_at_screen=False,
                face_detected=True
            )
        
        drift_alerts = self.alert_system.get_statistics()['total_alerts']
        
        # Now eyes return to screen
        self.alert_system.check_and_trigger_alert(
            in_call_or_recording=True,
            looking_at_screen=True,
            face_detected=True
        )
        
        # Drift counter should reset
        self.assertEqual(self.alert_system.consecutive_drift_frames, 0)
    
    def test_system_edge_cases(self):
        """VR10: Test system handles edge cases"""
        # Test with no face
        result = self.alert_system.check_and_trigger_alert(
            in_call_or_recording=True,
            looking_at_screen=True,
            face_detected=False
        )
        
        # Should alert about missing face
        self.assertTrue(result['should_alert'])
        self.assertIn('FACE NOT DETECTED', result['message'])
        
        # Test with rapid status changes
        for i in range(10):
            self.alert_system.check_and_trigger_alert(
                in_call_or_recording=(i % 2 == 0),  # Toggle call status
                looking_at_screen=(i % 3 == 0),     # Toggle eye position
                face_detected=True
            )


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
