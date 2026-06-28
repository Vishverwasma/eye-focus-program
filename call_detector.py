import psutil
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


class CallRecordingDetector:
    """
    Detects if user is currently in a call or recording using process monitoring.
    Supports: Zoom, MS Teams, Discord, Google Meet, Skype, OBS, etc.
    """
    
    # Known call/conferencing application process names
    CALL_APPS = {
        'zoom': ['zoom.exe', 'zoomus.exe'],
        'teams': ['teams.exe', 'msedge.exe'],  # Removed chrome.exe - too broad
        'discord': ['discord.exe'],
        'skype': ['skype.exe'],
        'google_meet': ['google-chrome.exe', 'chrome.exe'],  # Kept but use window validation
        'slack': ['slack.exe'],
        'whatsapp': ['whatsapp.exe'],
        'telegram': ['telegram.exe']
    }
    
    # Recording applications
    RECORDING_APPS = {
        'obs': ['obs64.exe', 'obs32.exe'],
        'streamlabs': ['streamlabs obs.exe'],
        'nvidia_replay': ['nvcontainer.exe'],
        'windows_record': ['ScreenClipX.exe'],
        'bandicam': ['bandicam.exe'],
        'fraps': ['fraps.exe'],
        'action_cam': ['ACEPlayer.exe']
    }
    
    def __init__(self, enable_audio_detection: bool = False):
        """
        Initialize call/recording detector
        
        Args:
            enable_audio_detection: Also check for audio input device usage (more accurate)
        """
        self.enable_audio_detection = enable_audio_detection
        self.in_call_frames = 0
        self.recording_frames = 0
    
    def detect_active_call(self) -> Tuple[bool, str]:
        """
        Check if user is currently in an active call
        
        Returns:
            (in_call, app_name) - bool indicating if in call and name of app
        """
        for app_name, processes in self.CALL_APPS.items():
            if self._is_process_running(processes):
                self.in_call_frames += 1
                if self.in_call_frames > 2:  # Debounce with 2 frames
                    return True, app_name
                return False, ""  # Don't report until debounced
        
        self.in_call_frames = 0
        return False, ""
    
    def detect_active_recording(self) -> Tuple[bool, str]:
        """
        Check if user is currently recording
        
        Returns:
            (recording, app_name) - bool indicating if recording and name of app
        """
        for app_name, processes in self.RECORDING_APPS.items():
            if self._is_process_running(processes):
                self.recording_frames += 1
                if self.recording_frames > 2:  # Debounce with 2 frames
                    return True, app_name
                return False, ""  # Don't report until debounced
        
        # Also check if call app is running (likely has camera recording active)
        for app_name, processes in self.CALL_APPS.items():
            if self._is_process_running(processes):
                # Double check for window title containing "recording" or similar
                if self._check_window_title_for_recording():
                    self.recording_frames += 1
                    if self.recording_frames > 2:
                        return True, f"{app_name}_recording"
                    return False, ""
        
        self.recording_frames = 0
        return False, ""
    
    def get_status(self) -> Dict:
        """
        Get comprehensive status of call and recording detection
        
        Returns:
            Dictionary with:
                - in_call: bool
                - call_app: str
                - recording: bool
                - recording_app: str
                - any_action: bool (True if in call OR recording)
        """
        in_call, call_app = self.detect_active_call()
        recording, recording_app = self.detect_active_recording()
        
        return {
            'in_call': in_call,
            'call_app': call_app,
            'recording': recording,
            'recording_app': recording_app,
            'any_action': in_call or recording,
            'status_text': self._generate_status_text(in_call, call_app, recording, recording_app)
        }
    
    @staticmethod
    def _is_process_running(process_names: list) -> bool:
        """Check if any process from the list is running"""
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'].lower() in [p.lower() for p in process_names]:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.warning(f"Error checking processes: {e}")
        
        return False
    
    @staticmethod
    def _check_window_title_for_recording() -> bool:
        """Check active window title for recording indicators"""
        try:
            import pygetwindow
            active_window = pygetwindow.getActiveWindow()
            if active_window and active_window.title:
                title_lower = active_window.title.lower()
                recording_keywords = ['recording', 'record', 'live', 'stream', 'streaming']
                return any(keyword in title_lower for keyword in recording_keywords)
        except ImportError:
            logger.debug("pygetwindow not available for window title detection")
        
        return False
    
    @staticmethod
    def _generate_status_text(in_call: bool, call_app: str, recording: bool, recording_app: str) -> str:
        """Generate human-readable status text"""
        statuses = []
        
        if in_call:
            statuses.append(f"📞 In call ({call_app})")
        
        if recording:
            statuses.append(f"🔴 Recording ({recording_app})")
        
        if not statuses:
            return "Idle"
        
        return " + ".join(statuses)
