import logging
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

import cv2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraDevice:
    """A camera source OpenCV can open."""

    index: int
    backend: int
    backend_name: str
    name: str
    width: int
    height: int
    fps: float


class CameraSourceManager:
    """
    Discovers and opens the physical camera that this middleware will share.

    Eye Focus Monitor sits between the webcam and your conferencing/recording
    software: it is the one process that reads the physical camera, processes
    each frame, and republishes the result to a virtual camera that other apps
    consume. To make that role robust this manager:

    * Tries Media Foundation (MSMF) first, then DirectShow. MSMF is the modern
      Windows backend; on many machines it both works and allows the camera to
      be opened in *shared* mode (so capture can succeed even when another app
      already has the same physical camera open - we share it, we never seize
      exclusive ownership). DirectShow is kept as a fallback because on some
      systems it is unavailable for capture-by-index and takes several seconds
      to fail, so it must not be tried first.
    * Treats physical cameras, capture cards, and shared camera drivers as
      interchangeable sources and avoids hardcoding camera 0.

    Note: another app reading the physical camera directly still sees the RAW
    feed. For an app to receive the *processed* frames it must select the
    virtual camera published by virtual_camera.VirtualCameraPublisher.
    """

    # MSMF first: it is the modern Windows backend, opens quickly, and on many
    # webcams allows shared access. DirectShow is a fallback only - on some
    # machines it cannot capture by index and takes ~9s to fail, so trying it
    # first would make startup needlessly slow.
    DEFAULT_BACKENDS = (
        cv2.CAP_MSMF,
        cv2.CAP_DSHOW,
        cv2.CAP_ANY,
    )

    BACKEND_NAMES = {
        cv2.CAP_DSHOW: "DirectShow",
        cv2.CAP_MSMF: "Media Foundation",
        cv2.CAP_ANY: "Auto",
    }

    def __init__(
        self,
        max_index: int = 10,
        backends: Optional[Sequence[int]] = None,
        frame_width: Optional[int] = None,
        frame_height: Optional[int] = None,
        fps: Optional[int] = None,
    ):
        # frame_width/height/fps default to None = use the camera's native mode.
        # Forcing a resolution can cost several seconds on some drivers (MSMF),
        # so it's opt-in via --resolution rather than a hidden default.
        self.max_index = max_index
        self.backends = tuple(backends or self.DEFAULT_BACKENDS)
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.fps = fps

    def scan(self) -> List[CameraDevice]:
        """Return all camera indexes/backends that can capture a frame."""
        devices: List[CameraDevice] = []

        for index in range(self.max_index + 1):
            for backend in self.backends:
                # Don't apply resolution/fps while probing - on some drivers
                # setting the resolution costs several seconds per device, which
                # would make scanning every index painfully slow. We only need
                # to know the device can deliver a frame here.
                cap = self._open_capture(index, backend, configure=False)
                try:
                    if not cap.isOpened():
                        continue

                    ret, _ = cap.read()
                    if not ret:
                        continue

                    device = CameraDevice(
                        index=index,
                        backend=backend,
                        backend_name=self.backend_name(backend),
                        name=self._device_name(cap, index),
                        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
                        height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
                        fps=float(cap.get(cv2.CAP_PROP_FPS) or 0),
                    )
                    devices.append(device)
                    break
                finally:
                    cap.release()

        return devices

    def open_preferred(
        self,
        camera_id: Optional[int] = None,
        prefer_name: Optional[str] = None,
        exclude_names: Optional[Iterable[str]] = None,
    ):
        """
        Open the best available source.

        Selection order:
        1. explicit camera_id
        2. first source matching prefer_name
        3. first source not matching excluded names
        4. first available source
        """
        # Fast path: an explicit index opens directly, skipping the full scan
        # (which probes every index/backend and can take many seconds, and on
        # machines where DirectShow can't capture it just wastes time).
        if camera_id is not None:
            direct = self._open_index_directly(camera_id)
            if direct is not None:
                cap, selected = direct
                logger.info(
                    "Using camera index %s via %s (%sx%s @ %.1f FPS)",
                    selected.index, selected.backend_name,
                    selected.width, selected.height, selected.fps,
                )
                return cap, selected
            raise RuntimeError(
                f"Camera index {camera_id} could not be opened on any backend. "
                "It may not exist, or another app is holding it exclusively. "
                "Omit --camera to auto-scan, or close the other app."
            )

        devices = self.scan()
        if not devices:
            raise RuntimeError(
                "No usable camera source could be opened. Either no camera is "
                "connected, or another application is holding it with an "
                "EXCLUSIVE lock that the OS will not let any other process share "
                "(this is an OS/driver limit, not something code can override). "
                "Fix: start Eye Focus Monitor first, then point your other apps "
                "at the virtual camera it publishes."
            )

        selected = self._select_device(devices, camera_id, prefer_name, exclude_names)
        # scan() opened then released this device a moment ago; under contention
        # (another app sharing the camera) the re-opened handle can take longer to
        # start delivering frames, so be patient (~4s) and retry once.
        cap = None
        for _ in range(2):
            candidate = self._open_capture(selected.index, selected.backend)
            if candidate.isOpened() and self._capture_first_frame(candidate, attempts=80):
                cap = candidate
                break
            candidate.release()
        if cap is None:
            raise RuntimeError(
                f"Selected camera {selected.index} ({selected.backend_name}) "
                "opened but did not deliver frames. Another app (often the Windows "
                "Camera app) is holding the camera. Close it - you don't need it: "
                "this app shows its own preview window, and other apps should select "
                "the virtual camera, not the physical one."
            )

        logger.info(
            "Using camera index %s via %s (%sx%s @ %.1f FPS)",
            selected.index,
            selected.backend_name,
            selected.width,
            selected.height,
            selected.fps,
        )
        return cap, selected

    def reopen_same(self, device: CameraDevice):
        """
        Re-open the SAME physical camera after a transient read failure.

        A dropped frame usually means the device hiccuped or another app just
        grabbed/released it - not that we should abandon it. We stay on the
        same device (and same shared-access backend) so the middleware keeps
        publishing the camera the user actually pointed their apps at.
        Returns an opened VideoCapture or None if the device is truly gone.
        """
        cap = self._open_capture(device.index, device.backend)
        if not cap.isOpened():
            return None

        if not self._capture_first_frame(cap):
            cap.release()
            return None

        logger.info(
            "Re-opened camera index %s via %s (shared)",
            device.index,
            device.backend_name,
        )
        return cap

    def reopen_after_failure(
        self,
        current_index: int,
        prefer_name: Optional[str] = None,
        exclude_names: Optional[Iterable[str]] = None,
    ):
        """
        Last-resort recovery: the original device is gone, so find any other
        usable source. Prefer reopen_same() first; only fall back here when
        the physical camera has genuinely disappeared (unplugged/removed).
        """
        devices = [device for device in self.scan() if device.index != current_index]
        if not devices:
            return None, None

        selected = self._select_device(devices, None, prefer_name, exclude_names)
        cap = self._open_capture(selected.index, selected.backend)
        if not cap.isOpened():
            return None, None

        logger.warning(
            "Camera index %s vanished; falling back to index %s via %s",
            current_index,
            selected.index,
            selected.backend_name,
        )
        return cap, selected

    def _select_device(
        self,
        devices: Sequence[CameraDevice],
        camera_id: Optional[int],
        prefer_name: Optional[str],
        exclude_names: Optional[Iterable[str]],
    ) -> CameraDevice:
        if camera_id is not None:
            for device in devices:
                if device.index == camera_id:
                    return device
            available = ", ".join(str(device.index) for device in devices)
            raise RuntimeError(f"Camera {camera_id} is not available. Available: {available}")

        if prefer_name:
            prefer_name_lower = prefer_name.lower()
            for device in devices:
                haystack = f"{device.name} {device.backend_name}".lower()
                if prefer_name_lower in haystack:
                    return device

        excluded = [name.lower() for name in (exclude_names or []) if name]
        for device in devices:
            haystack = f"{device.name} {device.backend_name}".lower()
            if not any(name in haystack for name in excluded):
                return device

        return devices[0]

    def _open_index_directly(self, index: int):
        """
        Open a specific camera index, trying each backend, and return an
        already-open (cap, CameraDevice) the caller can use directly - or None
        if no backend can capture from it. Used for the explicit --camera path.
        """
        for backend in self.backends:
            cap = self._open_capture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue
            if not self._capture_first_frame(cap):
                cap.release()
                continue
            device = CameraDevice(
                index=index,
                backend=backend,
                backend_name=self.backend_name(backend),
                name=self._device_name(cap, index),
                width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
                height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
                fps=float(cap.get(cv2.CAP_PROP_FPS) or 0),
            )
            return cap, device
        return None

    def _capture_first_frame(self, cap, attempts: int = 40, delay: float = 0.05) -> bool:
        """
        Read until the camera delivers a real frame.

        MSMF (and a just-reopened device) often returns False for the first
        reads while the stream spins up - up to a second or two. We retry with a
        small delay so a perfectly good camera isn't rejected for being slow to
        warm up. ~40 x 50ms = up to 2s.
        """
        for _ in range(attempts):
            ret, frame = cap.read()
            if ret and frame is not None:
                return True
            time.sleep(delay)
        return False

    def _open_capture(self, index: int, backend: int, configure: bool = True):
        cap = cv2.VideoCapture(index, backend)
        if configure:
            # Keep only the latest frame queued so reads return the freshest
            # frame instead of a stale buffered one (reduces perceived lag).
            # Harmless if the backend ignores it.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Only set what was explicitly requested; each set() can be slow.
            if self.frame_width:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
            if self.frame_height:
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            if self.fps:
                cap.set(cv2.CAP_PROP_FPS, self.fps)
        return cap

    @classmethod
    def backend_name(cls, backend: int) -> str:
        return cls.BACKEND_NAMES.get(backend, str(backend))

    @staticmethod
    def _device_name(cap, index: int) -> str:
        backend = cap.getBackendName() if hasattr(cap, "getBackendName") else "OpenCV"
        return f"Camera {index} ({backend})"
