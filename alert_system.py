import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List

logger = logging.getLogger(__name__)


class AlertSystem:
    """
    Manages visual and audio alerts when user's eyes drift away during calls/recording.
    """
    
    def __init__(self, log_dir: str = "logs"):
        """
        Initialize alert system
        
        Args:
            log_dir: Directory to store activity logs
        """
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        
        self.alert_history: List[Dict] = []
        self.consecutive_drift_frames = 0
        self.alert_threshold = 3  # Number of consecutive drift frames before alerting
        self.alert_cooldown_until = datetime.now()  # Time-based cooldown
    
    def check_and_trigger_alert(self, 
                               in_call_or_recording: bool,
                               looking_at_screen: bool,
                               face_detected: bool,
                               call_app: str = "",
                               recording_app: str = "") -> Dict:
        """
        Check if alert should trigger based on call status and eye tracking
        
        Args:
            in_call_or_recording: Whether user is in call or recording
            looking_at_screen: Whether user's eyes are on screen
            face_detected: Whether face is visible in camera
            call_app: Name of active call app
            recording_app: Name of recording app
            
        Returns:
            Dictionary with:
                - should_alert: bool
                - alert_type: str ('visual', 'audio', 'both', 'none')
                - message: str
                - severity: str ('low', 'medium', 'high')
        """
        result = {
            'should_alert': False,
            'alert_type': 'none',
            'message': '',
            'severity': 'low',
            'frame_count': self.consecutive_drift_frames
        }
        
        # No alert if not in call/recording
        if not in_call_or_recording:
            self.consecutive_drift_frames = 0
            return result
        
        # No face detected - high priority alert
        if not face_detected:
            # Check cooldown before alerting
            if datetime.now() >= self.alert_cooldown_until:
                result['should_alert'] = True
                result['alert_type'] = 'both'
                result['message'] = "⚠️ FACE NOT DETECTED - Camera may be blocked!"
                result['severity'] = 'high'
                self.alert_cooldown_until = datetime.now() + timedelta(seconds=1)
                self._log_alert(result, call_app or recording_app)
            return result
        
        # Check for eyes looking away
        if not looking_at_screen:
            self.consecutive_drift_frames += 1
        else:
            self.consecutive_drift_frames = 0
            return result
        
        # Trigger alert based on consecutive drift frames
        if datetime.now() >= self.alert_cooldown_until and self.consecutive_drift_frames >= self.alert_threshold:
            result['should_alert'] = True
            result['alert_type'] = self._determine_alert_type(self.consecutive_drift_frames)
            result['message'] = self._generate_alert_message(self.consecutive_drift_frames)
            result['severity'] = self._calculate_severity(self.consecutive_drift_frames)
            
            self.alert_history.append({
                'timestamp': datetime.now(),
                'type': result['alert_type'],
                'app': call_app or recording_app,
                'severity': result['severity']
            })
            
            self._log_alert(result, call_app or recording_app)
            self.alert_cooldown_until = datetime.now() + timedelta(seconds=1)  # 1 second cooldown
        
        return result
    
    @staticmethod
    def _determine_alert_type(consecutive_frames: int) -> str:
        """Determine alert type based on how long eyes have been away"""
        if consecutive_frames < 5:
            return 'visual'  # Just a visual cue
        elif consecutive_frames < 10:
            return 'visual'  # Stronger visual
        else:
            return 'both'  # Visual + audio
    
    @staticmethod
    def _generate_alert_message(consecutive_frames: int) -> str:
        """Generate contextual alert message"""
        seconds_away = consecutive_frames / 30  # Assuming 30fps
        
        if consecutive_frames < 5:
            return "👀 Eyes detected away from screen"
        elif consecutive_frames < 10:
            return f"⚠️ Eyes away for {seconds_away:.1f}s - Look at camera!"
        elif consecutive_frames < 20:
            return f"⚠️⚠️ EYES AWAY for {seconds_away:.1f}s - LOOK AT SCREEN NOW!"
        else:
            return f"🔴 CRITICAL: Eyes away for {seconds_away:.1f}s - LOOK AT CAMERA IMMEDIATELY!"
    
    @staticmethod
    def _calculate_severity(consecutive_frames: int) -> str:
        """Calculate alert severity"""
        if consecutive_frames < 5:
            return 'low'
        elif consecutive_frames < 15:
            return 'medium'
        else:
            return 'high'
    
    def generate_beep(self, frequency: int = 1000, duration: float = 0.2):
        """
        Generate and play a simple beep sound
        
        Args:
            frequency: Frequency in Hz
            duration: Duration in seconds
        """
        try:
            import winsound
            # Calculate milliseconds
            ms = int(duration * 1000)
            winsound.Beep(frequency, ms)
        except ImportError:
            logger.warning("winsound not available - audio alerts disabled")
        except Exception as e:
            logger.error(f"Error generating beep: {e}")
    
    def play_alert_sequence(self, alert_type: str):
        """Play appropriate alert sequence based on type"""
        if alert_type in ['audio', 'both']:
            # Double beep for alert
            self.generate_beep(1000, 0.15)
            self.generate_beep(1200, 0.15)
    
    def _log_alert(self, alert_data: Dict, app_name: str):
        """Log alert to file"""
        try:
            log_file = os.path.join(self.log_dir, f"alerts_{datetime.now().date()}.txt")
            # encoding must be explicit: alert messages contain emojis and the
            # Windows default (cp1252) cannot encode them, which would raise.
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"App: {app_name} | "
                    f"Type: {alert_data['alert_type']} | "
                    f"Severity: {alert_data['severity']} | "
                    f"Message: {alert_data['message']}\n"
                )
        except Exception as e:
            logger.error(f"Error logging alert: {e}")
    
    def get_statistics(self) -> Dict:
        """Get alert statistics for current session"""
        if not self.alert_history:
            return {
                'total_alerts': 0,
                'by_severity': {},
                'by_app': {},
                'average_frames_to_alert': 0
            }
        
        severity_counts = {}
        app_counts = {}
        
        for alert in self.alert_history:
            severity_counts[alert['severity']] = severity_counts.get(alert['severity'], 0) + 1
            app_counts[alert['app']] = app_counts.get(alert['app'], 0) + 1
        
        return {
            'total_alerts': len(self.alert_history),
            'by_severity': severity_counts,
            'by_app': app_counts,
            'alert_history': self.alert_history[-10:]  # Last 10 alerts
        }
