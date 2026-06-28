import logging
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
    Discovers and opens OpenCV camera sources.

    OpenCV cannot read another application's private camera stream directly. This
    manager treats physical cameras, virtual cameras, capture cards, and shared
    camera drivers as interchangeable sources and avoids hardcoding camera 0.
    """

    DEFAULT_BACKENDS = (
        cv2.CAP_DSHOW,
        cv2.CAP_MSMF,
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
        frame_width: int = 1280,
        frame_height: int = 720,
        fps: int = 30,
    ):
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
                cap = self._open_capture(index, backend)
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
        devices = self.scan()
        if not devices:
            raise RuntimeError("No usable camera sources were found")

        selected = self._select_device(devices, camera_id, prefer_name, exclude_names)
        cap = self._open_capture(selected.index, selected.backend)
        if not cap.isOpened():
            raise RuntimeError(
                f"Selected camera {selected.index} ({selected.backend_name}) could not be opened"
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

    def reopen_after_failure(
        self,
        current_index: int,
        prefer_name: Optional[str] = None,
        exclude_names: Optional[Iterable[str]] = None,
    ):
        """Try to recover from a dropped/locked camera by selecting another source."""
        devices = [device for device in self.scan() if device.index != current_index]
        if not devices:
            return None, None

        selected = self._select_device(devices, None, prefer_name, exclude_names)
        cap = self._open_capture(selected.index, selected.backend)
        if not cap.isOpened():
            return None, None

        logger.warning(
            "Switched camera source from index %s to index %s via %s",
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

    def _open_capture(self, index: int, backend: int):
        cap = cv2.VideoCapture(index, backend)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        return cap

    @classmethod
    def backend_name(cls, backend: int) -> str:
        return cls.BACKEND_NAMES.get(backend, str(backend))

    @staticmethod
    def _device_name(cap, index: int) -> str:
        backend = cap.getBackendName() if hasattr(cap, "getBackendName") else "OpenCV"
        return f"Camera {index} ({backend})"
