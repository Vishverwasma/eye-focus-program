# Eye Focus Monitor

A real-time desktop application that monitors your eyes during calls and recordings to ensure you're looking at the screen. Uses AI-powered eye tracking to detect gaze direction and alerts you when your eyes drift away during active calls or recordings.

## Features

✨ **Eye Tracking**
- Real-time eye detection using MediaPipe face mesh
- Accurate gaze direction estimation (center, left, right, up, down)
- Sub-second response time

📞 **Call Detection**
- Automatic detection of active calls (Zoom, Teams, Discord, Google Meet, Skype, Slack, etc.)
- Identifies when video recording is active
- Monitors multiple communication platforms simultaneously

🚨 **Smart Alerts**
- Visual alerts when eyes drift from screen
- Audio beeps for persistent drift
- Severity-based notifications (low, medium, high)
- Alert cooldown to avoid notification fatigue

📊 **Monitoring Dashboard**
- Real-time webcam feed with eye tracking overlay
- Call/recording status indicator
- Frame counter and alert counter
- Session statistics and logging

## Installation

### Prerequisites
- Python 3.8 or higher
- Webcam/camera device
- Windows, macOS, or Linux

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/eye_focus_monitor.git
cd eye_focus_monitor
```

2. **Create virtual environment** (recommended)
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

## Usage

### Start the monitor
```bash
python main.py
```

### How it shares the camera (middleware model)

Eye Focus Monitor is **middleware** that sits between your physical webcam and
your conferencing/recording software:

```
Physical webcam ─▶ Eye Focus Monitor (capture → eye tracking → overlay) ─▶ Virtual camera ─▶ Zoom / Teams / Meet / OBS / any app
```

- This app is the one process that reads the **physical** webcam. It opens it
  with DirectShow in **shared** mode, so startup succeeds even if another app
  already has the camera open — it *shares* the device, it never tries to seize
  exclusive control away from another app.
- It processes every frame and republishes the result to a **virtual camera**.
- In Zoom, Teams, Google Meet, OBS, etc., select that virtual camera as your
  "webcam." Those apps then receive the **processed** feed.

On startup the app prints the exact virtual-camera device name to select, e.g.:

```
MIDDLEWARE ACTIVE - sharing your processed camera feed
In Zoom / Teams / Meet / OBS, pick this camera device:
    >>> OBS Virtual Camera <<<
```

> Important: for an app to see the *processed* frames it must read from the
> **virtual** camera. An app pointed straight at the physical webcam still gets
> the raw feed. Publishing requires `pyvirtualcam` plus a virtual-camera backend
> (the OBS Virtual Camera driver is the easiest on Windows).

Use `--no-virtual-camera` if you only want the local monitor window.

#### Check your setup before a call

```bash
python main.py --check-backend      # is a virtual-camera backend installed?
python main.py --list-cameras       # list webcams AND report backend status
```

`--check-backend` prints `OK` (with the device name to select) or `NOT READY`
with the reason, and exits non-zero when not ready — so you catch a missing
driver before you join a meeting instead of during it.

#### Fast startup & resolution

```bash
python main.py --camera 0              # skip the scan, open index 0 directly (fastest)
python main.py --resolution 1280x720  # request HD (adds a few seconds on some webcams)
```

- Without `--camera`, the app scans for a working source, which takes a few
  seconds. If you know your index (see `--list-cameras`), pass it to start
  almost instantly.
- By default the camera's **native** resolution is used (fast). Forcing a
  resolution can cost several extra seconds on some drivers, so HD is opt-in
  via `--resolution`.

> If you get *"No usable camera source could be opened"*, another app is most
> likely already using the camera. Close it (or start Eye Focus Monitor first
> and point the other app at the virtual camera).

### Keyboard Controls
- **Q** - Quit application
- **S** - Save screenshot
- **R** - Reset statistics

### What to Expect

1. Camera feed opens in a window
2. Your face is detected and tracked
3. Eye gaze direction is monitored
4. During calls/recordings:
   - Eyes on screen = Green indicator
   - Eyes away = Red indicator + Alert
5. Alerts increase in intensity if eyes remain off-screen

## How It Works

### 1. Eye Tracking Engine
- Uses MediaPipe's face mesh to detect 468 facial landmarks
- Tracks iris position within eye bounds
- Calculates normalized gaze coordinates
- Determines gaze direction based on configurable threshold

### 2. Call Detection
- Monitors system processes for known communication apps
- Checks window titles for recording indicators
- Provides real-time status updates

### 3. Alert System
- Tracks consecutive frames with eyes away from screen
- Escalates severity based on duration
- Logs all alerts with timestamps
- Plays audio alerts for high severity

## Configuration

Edit the following in `main.py`:

```python
# Camera selection (default: 0)
monitor = EyeFocusMonitor(camera_id=0)

# Gaze threshold (lower = stricter)
self.eye_tracker = EyeTracker(gaze_threshold=0.15)

# Alert threshold (frames before alerting)
self.alert_system.alert_threshold = 3
```

## Supported Apps

### Call/Conference Apps
- Zoom
- Microsoft Teams
- Discord
- Google Meet
- Skype
- Slack
- Telegram
- WhatsApp

### Recording Apps
- OBS Studio
- Streamlabs OBS
- NVIDIA Replay
- Bandicam
- FRAPS

## Logs and Statistics

- Daily alert logs saved in `logs/` directory
- Session statistics printed on exit
- Formatted: `alerts_YYYY-MM-DD.txt`

## Performance

- **CPU Usage**: 10-20% (depends on resolution)
- **Memory Usage**: 150-300MB
- **Frame Rate**: 30 FPS
- **Latency**: <100ms eye tracking response

## Troubleshooting

### Camera not detected
```bash
# Check available cameras
python -c "import cv2; print(cv2.CAP_PROP_FRAME_COUNT)"
```

### Face not detected
- Ensure adequate lighting
- Position camera to capture full face
- Adjust `min_detection_confidence` in `eye_tracker.py`

### `module 'mediapipe' has no attribute 'solutions'`
A too-new mediapipe build (e.g. 0.10.35) dropped the legacy `solutions` API the
eye tracker uses. Install the pinned version:
```bash
pip install "mediapipe==0.10.14"
```
Do not loosen the mediapipe pin in `requirements.txt` without re-testing.

### False alerts
- Increase `gaze_threshold` value
- Increase `alert_threshold` in alert system
- Calibrate lighting conditions

## Privacy & Security

✅ **All processing is local** - No data sent to cloud
✅ **No recordings** - Only real-time processing
✅ **No audio recording** - Visual monitoring only
✅ **Open source** - Full transparency of code

## Development

### Project Structure
```
eye_focus_monitor/
├── main.py                 # Main application
├── eye_tracker.py          # Eye tracking engine
├── call_detector.py        # Call/recording detection
├── alert_system.py         # Alert management
├── requirements.txt        # Dependencies
├── README.md              # This file
└── logs/                  # Session logs
```

### Running Tests
```bash
python -m pytest tests/
```

## Known Limitations

1. **Low light environments** - Eye detection accuracy decreases
2. **Glasses/sunglasses** - May interfere with iris detection
3. **Wide angle faces** - Less accurate than direct camera angle
4. **Multi-monitor setups** - Assumes single primary screen

## Future Improvements

- [ ] Multi-face support
- [ ] Calibration wizard for first-time setup
- [ ] Custom alert sounds
- [ ] Focus time statistics
- [ ] Integration with calendar for call detection
- [ ] Mobile app companion
- [ ] Web dashboard for session history
- [ ] Machine learning model for improved accuracy

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check existing documentation
- Review troubleshooting section

## Acknowledgments

- MediaPipe for face detection and eye tracking
- OpenCV for computer vision framework
- PyQt5 for UI components
- psutil for system monitoring

## Disclaimer

This application is provided as-is. Use at your own discretion. While it aims to help maintain focus during calls, users are responsible for their own professional conduct and call etiquette.

---

**Made with ❤️ for better call focus and professional presence**
