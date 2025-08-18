import pyudev
import subprocess
import prettytable
import argparse
import re
from collections import defaultdict


def get_camera_details(vid_filter=None, pid_filter=None):
    """
    Finds all physical cameras and returns their details, using the robust
    v4l2-ctl method to verify the video capture device path.
    Can optionally filter by vendor ID and product ID.
    """
    camera_list = []
    context = pyudev.Context()

    physical_devices = {}
    for device in context.list_devices(subsystem='video4linux'):
        usb_device = device.find_parent('usb', 'usb_device')
        if usb_device != None:
            if usb_device.device_path not in physical_devices:
                physical_devices[usb_device.device_path] = {
                    "nodes": [],
                    "name": usb_device.attributes.get('product'),
                    "vid": usb_device.attributes.get('idVendor'),
                    "pid": usb_device.attributes.get('idProduct'),
                    "serial": usb_device.attributes.get('serial')
                }
            physical_devices[usb_device.device_path]["nodes"].append(device.device_node)

    for device_info in physical_devices.values():
        # Apply VID/PID filters if provided
        if vid_filter and device_info.get("vid", b'').decode("utf-8") != vid_filter:
            continue
        if pid_filter and device_info.get("pid", b'').decode("utf-8") != pid_filter:
            continue

        for node_path in sorted(device_info["nodes"]):
            if is_video_capture_device(node_path):
                camera_list.append({
                    "id": node_path[10:], # ASSUMING /dev/videoX format
                    "path": node_path,
                    "name": device_info["name"].decode("utf-8") if device_info["name"] else "",
                    "vid": device_info["vid"].decode("utf-8") if device_info["vid"] else "",
                    "pid": device_info["pid"].decode("utf-8") if device_info["pid"] else "",
                    "serial": device_info["serial"].decode("utf-8") if device_info["serial"] else ""
                })
                break
    
    return camera_list

def is_video_capture_device(path):
    """
    Checks if a device supports video capture by calling 'v4l2-ctl --all'.
    This is compatible with older and newer versions of v4l2-ctl.
    """
    try:
        # The --all flag provides a comprehensive report
        command = ['v4l2-ctl', '-d', path, '--all']
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        # We parse the output for the "Video Capture" capability text
        return 'Video Capture' in result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        # A CalledProcessError might occur if the device is a metadata-only node
        # that doesn't support the --all query well. We treat this as not a video device.
        return False

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

def enumerate_cameras():
    # Ensure you have v4l2-utils installed: sudo apt install v4l2-utils
    parser = argparse.ArgumentParser(description="List available video cameras, with optional filtering and capability listing.")
    parser.add_argument("--vid", help="Filter by vendor ID (e.g., 046d).")
    parser.add_argument("--pid", help="Filter by product ID (e.g., 082d).")
    parser.add_argument("-l", "--list-capabilities", action="store_true", help="List detailed capabilities for each camera.")
    args = parser.parse_args()

    available_cameras = get_camera_details(vid_filter=args.vid, pid_filter=args.pid)

    if not args.list_capabilities:
        pt = prettytable.PrettyTable()
        pt.field_names = ["id", "Path", "Name", "vid", "pid", "Serial"]
        pt.align = "l"

        for camera in available_cameras:
            pt.add_row([camera["id"], camera["path"], camera["name"], camera["vid"], camera["pid"], camera["serial"]])

        print(pt)
    else:
        if not available_cameras:
            print("No cameras found.")
            return

        # Group cameras by (vid, pid) to cluster similar models
        grouped_cameras = defaultdict(list)
        for cam in available_cameras:
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

            table = prettytable.PrettyTable()
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
    enumerate_cameras()


