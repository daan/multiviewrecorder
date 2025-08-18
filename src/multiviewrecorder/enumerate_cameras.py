import pyudev
import subprocess
import prettytable
import argparse


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

def enumerate_cameras():
    # Ensure you have v4l2-utils installed: sudo apt install v4l2-utils
    parser = argparse.ArgumentParser(description="List available video cameras, with optional filtering.")
    parser.add_argument("--vid", help="Filter by vendor ID (e.g., 046d).")
    parser.add_argument("--pid", help="Filter by product ID (e.g., 082d).")
    args = parser.parse_args()

    available_cameras = get_camera_details(vid_filter=args.vid, pid_filter=args.pid)

    pt = prettytable.PrettyTable()
    pt.field_names = ["id", "Path", "Name", "vid", "pid", "Serial"]   
    pt.align = "l"

    for camera in available_cameras:
        pt.add_row([camera["id"], camera["path"], camera["name"], camera["vid"], camera["pid"], camera["serial"]])

    print(pt)


if __name__ == "__main__":
    enumerate_cameras()


