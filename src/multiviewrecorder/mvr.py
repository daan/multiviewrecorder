import sys
import argparse
import tomli
import subprocess
import av
from av import FFmpegError
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QSizePolicy
)
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from multiviewrecorder.enumerate_cameras import get_camera_details


class AspectLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pixmap = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        self.updatePixmap()

    def setText(self, text):
        self._pixmap = QPixmap() # Clear the stored pixmap
        super().setText(text)

    def updatePixmap(self):
        if self._pixmap.isNull():
            return
        
        scaled_pixmap = self._pixmap.scaled(
            self.size(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        super().setPixmap(scaled_pixmap)

    def resizeEvent(self, event):
        self.updatePixmap()
        super().resizeEvent(event)


class VideoWorker(QThread):
    frameReady = Signal(QImage)
    finished = Signal()
    error = Signal(str)

    def __init__(self, device, options, parent=None):
        super().__init__(parent)
        self.device = device
        self.options = options
        self.running = True
        self._is_recording = False
        self._output_file = None
        self.output_container = None
        self.out_stream = None

    def run(self):
        input_container = None
        try:
            input_container = av.open(file=self.device, format='v4l2', options=self.options)
        except FFmpegError as e:
            self.error.emit(f"Error opening device {self.device}: {e}\nPlease check if the device exists, is not in use, and if you have permissions.")
            return

        in_stream = input_container.streams.video[0]

        try:
            for packet in input_container.demux(in_stream):
                if not self.running:
                    break

                # Decode for preview
                try:
                    for frame in packet.decode():
                        # Convert frame to QImage
                        rgb_frame = frame.reformat(format='rgb24')
                        qimage = QImage(
                            bytes(rgb_frame.planes[0]),
                            rgb_frame.width,
                            rgb_frame.height,
                            rgb_frame.planes[0].line_size,
                            QImage.Format_RGB888
                        )
                        self.frameReady.emit(qimage)
                except FFmpegError:
                    # Ignore decode errors, common at stream start
                    pass

                # Handle recording state changes
                if self._is_recording and not self.output_container:
                    # Start recording
                    try:
                        self.output_container = av.open(self._output_file, mode='w')
                        self.out_stream = self.output_container.add_stream(in_stream.codec.name, rate=int(self.options['framerate']))
                        self.out_stream.width = in_stream.width
                        self.out_stream.height = in_stream.height
                        self.out_stream.pix_fmt = in_stream.pix_fmt
                        self.out_stream.time_base = in_stream.time_base
                    except FFmpegError as e:
                        self.error.emit(f"Error starting recording: {e}")
                        self._is_recording = False
                        if self.output_container:
                            self.output_container.close()
                            self.output_container = None

                if not self._is_recording and self.output_container:
                    # Stop recording
                    self.output_container.close()
                    self.output_container = None
                    self.out_stream = None

                # Mux the packet to the output file for recording
                if self._is_recording and self.output_container:
                    try:
                        packet.stream = self.out_stream
                        self.output_container.mux(packet)
                    except FFmpegError as e:
                        self.error.emit(f"Error during muxing: {e}")

        except Exception as e:
            self.error.emit(f"An error occurred during capture: {e}")
        finally:
            if self.output_container:
                self.output_container.close()
            if input_container:
                input_container.close()
            self.finished.emit()

    def stop(self):
        self.running = False

    def start_recording(self, output_file):
        self._output_file = output_file
        self._is_recording = True

    def stop_recording(self):
        self._is_recording = False

class MainWindow(QMainWindow):
    def __init__(self, cameras, options):
        super().__init__()
        self.setWindowTitle("Multi-Webcam Recorder")

        self.video_labels = {}
        self.workers = {}
        self.cameras = cameras

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        video_layout = QHBoxLayout()
        main_layout.addLayout(video_layout)

        for camera in self.cameras:
            path = camera['path']
            label = AspectLabel(f"Starting {path}...")
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.video_labels[path] = label
            video_layout.addWidget(label)

            worker = VideoWorker(path, options)
            self.workers[path] = worker

            worker.frameReady.connect(lambda image, p=path: self.update_frame(p, image))
            worker.error.connect(lambda msg, p=path: self.on_error(p, msg))
            worker.finished.connect(lambda p=path: self.capture_finished(p))
            worker.start()

        self.start_button = QPushButton("Start Recording")
        self.stop_button = QPushButton("Stop Recording")
        self.stop_button.setEnabled(False)

        self.start_button.clicked.connect(self.start_recording)
        self.stop_button.clicked.connect(self.stop_recording)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        main_layout.addLayout(button_layout)

        # Set initial size
        if self.cameras:
            video_w, video_h = map(int, options['video_size'].split('x'))
            aspect_ratio = video_h / video_w
            num_cameras = len(self.cameras)

            screen = QApplication.primaryScreen()
            if screen:
                screen_geometry = screen.availableGeometry()
                initial_width = min(1920, screen_geometry.width())
            else:
                initial_width = 1920

            view_width = initial_width / num_cameras
            # also account for some vertical space for buttons
            initial_height = view_width * aspect_ratio + 50
            self.resize(initial_width, int(initial_height))

    def update_frame(self, path, image):
        self.video_labels[path].setPixmap(QPixmap.fromImage(image))

    def on_error(self, path, error_message):
        print(f"Error on {path}: {error_message}", file=sys.stderr)
        self.video_labels[path].setText(error_message)

    def start_recording(self):
        for camera in self.cameras:
            path = camera['path']
            # Use mapped_name for filename if available, otherwise fall back to serial
            filename_base = camera.get('mapped_name', camera['serial'])
            output_file = f"{filename_base}.mkv"
            if path in self.workers:
                self.workers[path].start_recording(output_file)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

    def stop_recording(self):
        for worker in self.workers.values():
            worker.stop_recording()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def capture_finished(self, path):
        self.video_labels[path].setText(f"Camera feed stopped for {path}.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
            worker.wait()
        super().closeEvent(event)

def mvr():
    parser = argparse.ArgumentParser(description="Record from multiple v4l2 cameras, displaying previews.")
    parser.add_argument("--config", help="Path to a TOML configuration file.")
    parser.add_argument("--vid", help="Filter by vendor ID (e.g., 046d).")
    parser.add_argument("--pid", help="Filter by product ID (e.g., 082d).")
    parser.add_argument("--resolution", help="Video resolution (e.g., 1280x720). Overrides config file.")
    parser.add_argument("--framerate", help="Video framerate (e.g., 30). Overrides config file.")
    parser.add_argument("--input_format", help="Input format (e.g., mjpeg). Overrides config file.")
    args = parser.parse_args()

    config = {}
    if args.config:
        try:
            with open(args.config, "rb") as f:
                config = tomli.load(f)
        except FileNotFoundError:
            print(f"Error: Config file not found at {args.config}", file=sys.stderr)
            sys.exit(1)
        except tomli.TOMLDecodeError as e:
            print(f"Error parsing TOML file {args.config}: {e}", file=sys.stderr)
            sys.exit(1)

    # Determine options, giving precedence to CLI args > config file > defaults
    options = {
        'video_size': args.resolution or config.get('resolution', '1280x720'),
        'framerate': args.framerate or config.get('framerate', '30'),
        'input_format': args.input_format or config.get('input_format', 'mjpeg')
    }

    print("Searching for cameras...")
    all_cameras = get_camera_details(vid_filter=args.vid, pid_filter=args.pid)
    
    if not all_cameras:
        print("No cameras found.")
        sys.exit(1)

    cameras_to_use = []
    if 'cameras' in config:
        config_cameras = {cam['serial']: cam for cam in config.get('cameras', [])}
        for cam in all_cameras:
            if cam['serial'] in config_cameras:
                cam_config = config_cameras[cam['serial']]
                cam['mapped_name'] = cam_config['name']
                cameras_to_use.append(cam)
        
        # Sort by the new mapped name
        cameras_to_use.sort(key=lambda x: x['mapped_name'])
    else:
        # No config, use all found cameras
        cameras_to_use = all_cameras
        # Sort by serial number to ensure a consistent order
        cameras_to_use.sort(key=lambda x: x['serial'])

    if not cameras_to_use:
        print("No cameras found matching the criteria in the config file.")
        sys.exit(1)

    print(f"Found {len(cameras_to_use)} cameras to use:")
    for cam in cameras_to_use:
        details = f"  - Path: {cam['path']}, Name: {cam['name']}, Serial: {cam['serial']}"
        if 'mapped_name' in cam:
            details += f", Mapped Name: {cam['mapped_name']}"
        print(details)

    print(f"Found {len(cameras_to_use)} cameras. Setting focus to manual...")
    for camera in cameras_to_use:
        device = camera['path']
        try:
            # Disable autofocus
            subprocess.run(['v4l2-ctl', '-d', device, '--set-ctrl=focus_automatic_continuous=0'], check=False)
            # Set focus to infinity (0)
            subprocess.run(['v4l2-ctl', '-d', device, '--set-ctrl=focus_absolute=0'], check=False)
        except FileNotFoundError:
            print("Warning: 'v4l2-ctl' command not found. Please install 'v4l-utils'. Autofocus could not be disabled.", file=sys.stderr)
            break

    app = QApplication(sys.argv)
    main_window = MainWindow(cameras_to_use, options)
    main_window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    mvr()
