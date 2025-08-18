import cv2
import numpy as np
from enumerate_cameras import get_camera_details
import argparse

def main(vid_filter=None, pid_filter=None, save_video=False, resolution="1280x720", framerate=60, max_width=None, checkerboard=None):
    """
    Captures video from all connected cameras and displays them in a single, juxtaposed window.
    Optionally saves each stream to a separate MP4 file.
    """
    try:
        req_width, req_height = map(int, resolution.split('x'))
    except ValueError:
        print(f"Invalid resolution format: {resolution}. Using default 1280x720.")
        req_width, req_height = 1280, 720

    checkerboard_pattern = None
    if checkerboard:
        try:
            pattern_cols, pattern_rows = map(int, checkerboard.split('x'))
            checkerboard_pattern = (pattern_cols, pattern_rows)
            print(f"Will search for a {checkerboard} checkerboard pattern.")
        except (ValueError, TypeError):
            print(f"Warning: Invalid checkerboard pattern '{checkerboard}'. Should be 'colsxrows' e.g., '7x6'. Disabling checkerboard detection.")
            checkerboard_pattern = None

    print("Finding connected cameras...")
    cameras = get_camera_details(vid_filter=vid_filter, pid_filter=pid_filter)
    if not cameras:
        print("No cameras found.")
        return

    # Sort cameras by serial number to ensure a consistent order.
    cameras.sort(key=lambda c: c['serial'])

    print(f"Found {len(cameras)} cameras. Opening streams...")
    captures = []
    for camera in cameras:
        cap = cv2.VideoCapture(camera['path'], cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, req_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, req_height)
            cap.set(cv2.CAP_PROP_FPS, framerate)
            cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
            cap.set(cv2.CAP_PROP_FOCUS, 25)
            # Set the capture codec to MJPG to reduce USB bandwidth
            fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            if not cap.set(cv2.CAP_PROP_FOURCC, fourcc):
                print(f"Warning: Could not set MJPG format for {camera['path']}. Using default.")

            # Try to read one frame to "prime" the camera and check if it's working.
            # This can help with timing issues on some systems/cameras.
            ret, _ = cap.read()
            if ret:
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                
                video_writer = None
                if save_video:
                    # Using cap.get(cv2.CAP_PROP_FPS) can be unreliable, so we use the requested framerate.
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v') # For .mp4 files
                    filename = f"out_{camera['serial']}.mp4"
                    video_writer = cv2.VideoWriter(filename, fourcc, framerate, (width, height))
                    if video_writer.isOpened():
                        print(f"Saving video for {camera['path']} to {filename}")
                    else:
                        print(f"Error: Could not open video writer for {filename}")
                        video_writer = None # Ensure it's None if creation fails
                
                captures.append({'capture': cap, 'path': camera['path'], 'width': width, 'height': height, 'writer': video_writer})
                print(f"Successfully opened and primed {camera['path']} ({width}x{height})")
            else:
                print(f"Warning: Could not read frame from camera {camera['path']} during initialization.")
                cap.release()
        else:
            print(f"Warning: Could not open camera {camera['path']}")
    
    if not captures:
        print("Could not open any camera streams.")
        return

    window_title = 'All Cameras - Press Esc to quit'

    # Determine a common height for resizing, using the smallest height among all cameras
    # This ensures all frames can be stacked horizontally
    min_height = min(c['height'] for c in captures if c['height'] > 0)

    try:
        while True:
            frames = []
            for cap_info in captures:
                ret, frame = cap_info['capture'].read()

                # If saving is enabled, write the original frame before any resizing.
                if ret and cap_info.get('writer'):
                    cap_info['writer'].write(frame)

                if not ret:
                    print(f"Error: Can't receive frame from {cap_info['path']}. Creating a black frame.")
                    # Create a black frame with the camera's native resolution
                    frame = np.zeros((cap_info['height'], cap_info['width'], 3), dtype=np.uint8)
                    # Add text to indicate error
                    cv2.putText(frame, f"No Signal: {cap_info['path']}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                
                frames.append(frame)

            if checkerboard_pattern:
                for frame in frames:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    # Find the chess board corners
                    ret, corners = cv2.findChessboardCorners(gray, checkerboard_pattern, None, cv2.CALIB_CB_FAST_CHECK)
                    # If found, draw the corners
                    if ret:
                        cv2.drawChessboardCorners(frame, checkerboard_pattern, corners, ret)

            # Resize all frames to the minimum common height while maintaining aspect ratio
            resized_frames = []
            for frame in frames:
                h, w, _ = frame.shape
                # If height is not the minimum, resize it
                if h != min_height:
                    scale = min_height / h
                    new_w = int(w * scale)
                    resized_frame = cv2.resize(frame, (new_w, min_height))
                else:
                    resized_frame = frame
                resized_frames.append(resized_frame)

            # Juxtapose frames horizontally
            if resized_frames:
                combined_frame = np.hstack(resized_frames)

                # Resize the combined frame for display if it exceeds max_width
                if max_width and combined_frame.shape[1] > max_width:
                    h, w, _ = combined_frame.shape
                    scale = max_width / w
                    new_h = int(h * scale)
                    combined_frame = cv2.resize(combined_frame, (max_width, new_h))

                cv2.imshow(window_title, combined_frame)

            # Exit on 'Esc' key press (ASCII code 27)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        print("Releasing camera resources...")
        for cap_info in captures:
            cap_info['capture'].release()
            if cap_info.get('writer'):
                cap_info['writer'].release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    # Ensure you have the necessary dependencies:
    # pip install opencv-python numpy pyudev prettytable
    parser = argparse.ArgumentParser(description="Display video from all connected cameras, with optional filtering.")
    parser.add_argument("--vid", help="Filter by vendor ID (e.g., 046d).")
    parser.add_argument("--pid", help="Filter by product ID (e.g., 082d).")
    parser.add_argument("--save", action="store_true", help="Save video streams to out_{serial}.mp4 files.")
    parser.add_argument("--resolution", default="1280x720", help="Set camera resolution (e.g., 1280x720).")
    parser.add_argument("--framerate", type=int, default=60, help="Set camera framerate.")
    parser.add_argument("--max_width", type=int, help="Maximum width of the displayed juxtaposed video.")
    parser.add_argument("--checkerboard", help="Find and visualize a checkerboard of the given pattern (e.g., 7x6).")
    args = parser.parse_args()

    main(vid_filter=args.vid, pid_filter=args.pid, save_video=args.save, resolution=args.resolution, framerate=args.framerate, max_width=args.max_width, checkerboard=args.checkerboard)
