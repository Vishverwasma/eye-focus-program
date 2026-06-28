import logging

import cv2

try:
    import pyvirtualcam
except ImportError:  # pragma: no cover - optional dependency
    pyvirtualcam = None

logger = logging.getLogger(__name__)


class VirtualCameraPublisher:
    """Publish processed BGR frames to a virtual camera device."""

    def __init__(self, width: int, height: int, fps: int):
        if pyvirtualcam is None:
            raise RuntimeError(
                "pyvirtualcam is not installed. Install the optional dependency and a virtual camera driver."
            )

        self.width = width
        self.height = height
        self.fps = fps
        self._camera = pyvirtualcam.Camera(width=width, height=height, fps=fps)
        logger.info("Virtual camera ready: %s", self._camera.device)

    @property
    def device(self) -> str:
        return str(self._camera.device)

    def publish(self, frame_bgr) -> None:
        # pyvirtualcam requires every frame to match the camera's exact
        # dimensions. Real webcams often deliver a different resolution than
        # was requested (or change it mid-stream), so resize defensively -
        # otherwise a single mismatched frame would raise and kill the feed.
        h, w = frame_bgr.shape[:2]
        if w != self.width or h != self.height:
            frame_bgr = cv2.resize(frame_bgr, (self.width, self.height))
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        self._camera.send(frame_rgb)
        self._camera.sleep_until_next_frame()

    def close(self) -> None:
        if getattr(self, "_camera", None) is not None:
            self._camera.close()
            self._camera = None

    @staticmethod
    def probe(width: int = 640, height: int = 480, fps: int = 30):
        """
        Check whether a virtual-camera backend is actually usable.

        Returns (ok, detail):
        * (False, reason) if pyvirtualcam is missing or no backend/driver is
          installed (e.g. the OBS Virtual Camera driver is not present).
        * (True, device_name) if a virtual camera can be opened. The probe
          camera is opened and immediately closed - nothing is published.
        """
        if pyvirtualcam is None:
            return False, (
                "pyvirtualcam is not installed (pip install pyvirtualcam)"
            )

        try:
            cam = pyvirtualcam.Camera(width=width, height=height, fps=fps)
        except Exception as e:  # no driver / device busy / unsupported
            return False, (
                f"{e}. Install a virtual-camera backend - on Windows the "
                "easiest is the OBS Virtual Camera driver (ships with OBS Studio)."
            )

        try:
            return True, str(cam.device)
        finally:
            cam.close()
