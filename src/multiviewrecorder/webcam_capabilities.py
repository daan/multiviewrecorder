import argparse
import subprocess
import re
from collections import defaultdict
from enumerate_cameras import get_camera_details

try:
    from prettytable import PrettyTable
except ImportError:
    print("Error: prettytable is not installed. Please install it using 'pip install prettytable'")
    exit(1)

def get_webcam_capabilities(device):
    """
    Queries a V4L2 device for its capabilities and returns them in a structured format.
    """
    try:
        # v4l2-ctl is part of v4l-utils
        result = subprocess.run(
            ['v4l2-ctl', '--list-formats-ext', '-d', device],
            capture_output=True, text=True, check=True, timeout=10
        )
    except FileNotFoundError:
        print(f"Error: 'v4l2-ctl' command not found. Please install 'v4l-utils'.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error querying {device}: {e.stderr.strip()}")
        return None
    except subprocess.TimeoutExpired:
        print(f"Error: command timed out for device {device}.")
        return None

    capabilities = defaultdict(lambda: defaultdict(list))
    current_format = None
    current_resolution = None

    for line in result.stdout.splitlines():
        line = line.strip()

        # Match format like: [0]: 'MJPG' (Motion-JPEG, compressed)
        format_match = re.match(r"\[\d+\]:\s+'(\w+)'", line)
        if format_match:
            current_format = format_match.group(1)
            current_resolution = None  # Reset resolution on new format
            continue

        # Match resolution like: Size: Discrete 1280x720
        resolution_match = re.match(r"Size: Discrete (\d+x\d+)", line)
        if resolution_match:
            current_resolution = resolution_match.group(1)
            continue

        # Match framerate like: Interval: Discrete 0.017s (60.0 fps)
        framerate_match = re.match(r"Interval: Discrete .* \((\d+\.?\d*)\s*fps\)", line)
        if framerate_match and current_format and current_resolution:
            fps = float(framerate_match.group(1))
            if fps not in capabilities[current_format][current_resolution]:
                capabilities[current_format][current_resolution].append(fps)

    return capabilities

def main():
    """
    Main function to parse arguments and display webcam capabilities.
    """
    parser = argparse.ArgumentParser(description="Display capabilities of V4L2 devices.")
    parser.add_argument('devices', nargs='*', help="Path to video device(s) (e.g., /dev/video0). If not provided, all cameras are probed.")
    args = parser.parse_args()

    all_cameras = get_camera_details()
    if not all_cameras:
        print("No cameras found.")
        return

    target_cameras = []
    if args.devices:
        all_camera_details_map = {cam['path']: cam for cam in all_cameras}
        for device_path in args.devices:
            if device_path in all_camera_details_map:
                target_cameras.append(all_camera_details_map[device_path])
            else:
                print(f"Warning: Device {device_path} not found or is not a camera. Skipping.")
    else:
        target_cameras = all_cameras

    if not target_cameras:
        print("No applicable cameras found to display.")
        return

    # Group cameras by (vid, pid) to cluster similar models
    grouped_cameras = defaultdict(list)
    for cam in target_cameras:
        grouped_cameras[(cam['vid'], cam['pid'])].append(cam)

    # Process each group of cameras
    for (vid, pid), cameras in grouped_cameras.items():
        representative_camera = cameras[0]
        device = representative_camera['path']
        name = representative_camera['name']

        device_details = ", ".join(sorted([f"{c['path']} (sn: {c['serial']})" for c in cameras]))

        print(f"\nCapabilities for {name} (vid: {vid}, pid: {pid})")
        print(f"  Devices: {device_details}")

        capabilities = get_webcam_capabilities(device)
        if not capabilities:
            print(f"  Could not retrieve capabilities for this group (probed {device}).")
            continue

        table = PrettyTable()
        table.field_names = ["Input Format", "Resolution", "Framerates"]
        table.align["Input Format"] = "l"
        table.align["Resolution"] = "l"
        table.align["Framerates"] = "l"

        # Sort formats alphabetically
        sorted_formats = sorted(capabilities.keys())

        for i, fmt in enumerate(sorted_formats):
            resolutions = capabilities[fmt]
            # Sort resolutions by total pixels (width * height)
            sorted_resolutions = sorted(
                resolutions.keys(),
                key=lambda r: int(r.split('x')[0]) * int(r.split('x')[1])
            )

            num_resolutions = len(sorted_resolutions)
            for j, res in enumerate(sorted_resolutions):
                framerates = sorted(resolutions[res])
                framerates_str = ", ".join(map(str, framerates))
                # Add a divider after the last resolution of a format, but not for the last format
                add_divider = (j == num_resolutions - 1) and (i < len(sorted_formats) - 1)
                table.add_row([fmt, res, framerates_str], divider=add_divider)

        print(table)


if __name__ == "__main__":
    main()
