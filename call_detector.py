import psutil
import logging
import threading
import time
from typing import Dict, Optional, Set, Tuple

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
    
    def __init__(self, enable_audio_detection: bool = False, scan_interval: float = 1.0):
        """
        Initialize call/recording detector

        Args:
            enable_audio_detection: Also check for audio input device usage (more accurate)
            scan_interval: Minimum seconds between process scans. get_status() is
                called every frame, but enumerating every OS process is expensive
                (~tens to hundreds of ms), so we scan at most once per interval
                and return a cached result in between. Call state changes on the
                order of seconds, not frames, so this is lossless in practice.
        """
        self.enable_audio_detection = enable_audio_detection
        self.scan_interval = scan_interval
        self.in_call_frames = 0
        self.recording_frames = 0
        self._cached_status: Optional[Dict] = None
        self._last_scan_time = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def detect_active_call(self, running: Optional[Set[str]] = None) -> Tuple[bool, str]:
        """
        Check if user is currently in an active call.

        Args:
            running: lower-cased set of running process names. If omitted, it is
                computed here (kept optional for direct/test use).

        Returns:
            (in_call, app_name) - bool indicating if in call and name of app
        """
        if running is None:
            running = self._running_process_names()

        for app_name, processes in self.CALL_APPS.items():
            if any(p.lower() in running for p in processes):
                self.in_call_frames += 1
                if self.in_call_frames > 2:  # Debounce
                    return True, app_name
                return False, ""  # Don't report until debounced

        self.in_call_frames = 0
        return False, ""

    def detect_active_recording(self, running: Optional[Set[str]] = None) -> Tuple[bool, str]:
        """
        Check if user is currently recording

        Returns:
            (recording, app_name) - bool indicating if recording and name of app
        """
        if running is None:
            running = self._running_process_names()

        for app_name, processes in self.RECORDING_APPS.items():
            if any(p.lower() in running for p in processes):
                self.recording_frames += 1
                if self.recording_frames > 2:  # Debounce
                    return True, app_name
                return False, ""  # Don't report until debounced

        # Also check if call app is running (likely has camera recording active)
        for app_name, processes in self.CALL_APPS.items():
            if any(p.lower() in running for p in processes):
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
        Get comprehensive status of call and recording detection.

        Non-blocking: the expensive process scan runs on a background thread, so
        calling this every frame is essentially free (it just returns the latest
        cached snapshot). The very first call does one synchronous scan so there
        is always valid data, then starts the background scanner.

        Returns:
            Dictionary with: in_call, call_app, recording, recording_app,
            any_action (in call OR recording), status_text.
        """
        if self._cached_status is None:
            self._refresh()            # one synchronous scan for initial data
            self._start_background()
        return self._cached_status

    def _refresh(self) -> None:
        """Scan processes once and rebuild the cached status (atomic assign)."""
        running = self._running_process_names()
        in_call, call_app = self.detect_active_call(running)
        recording, recording_app = self.detect_active_recording(running)
        # Dict assignment is atomic under the GIL, so get_status() readers always
        # see a complete dict (old or new), never a half-built one.
        self._cached_status = {
            'in_call': in_call,
            'call_app': call_app,
            'recording': recording,
            'recording_app': recording_app,
            'any_action': in_call or recording,
            'status_text': self._generate_status_text(in_call, call_app, recording, recording_app)
        }
        self._last_scan_time = time.monotonic()

    def _start_background(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._background_loop, name="call-detector", daemon=True
        )
        self._thread.start()

    def _background_loop(self) -> None:
        while not self._stop.wait(self.scan_interval):
            try:
                self._refresh()
            except Exception as e:  # never let the scanner thread die silently
                logger.warning(f"Call detection scan failed: {e}")

    def close(self) -> None:
        """Stop the background scanner thread (called on shutdown)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    @staticmethod
    def _running_process_names() -> Set[str]:
        """Snapshot of all running process names, lower-cased, in one pass."""
        names: Set[str] = set()
        try:
            for proc in psutil.process_iter(['name']):
                try:
                    name = proc.info['name']
                    if name:
                        names.add(name.lower())
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.warning(f"Error listing processes: {e}")
        return names
    
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
