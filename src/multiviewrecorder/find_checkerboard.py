#!/usr/bin/env python

import argparse
import cv2
import json
import os
import sys

def find_checkerboard():
    """
    Main function to find checkerboard corners and write them to a JSON file.
    """
    parser = argparse.ArgumentParser(
        description="Find checkerboard corners in an image and save to a JSON file in the specified format.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("image", help="Path to the input image.")
    parser.add_argument(
        "--dimensions",
        required=True,
        help="Checkerboard inner corners dimensions as WxH, e.g., '4x5'. W is number of inner corners per row (width), H is number of inner corners per column (height)."
    )
    parser.add_argument(
        "--grid",
        required=True,
        type=float,
        help="Size of the checkerboard grid squares (e.g., in meters)."
    )
    parser.add_argument(
        "--output",
        help="Path to the output JSON file. If not provided, it's derived from the image name (e.g., 'my_image.json' for 'my_image.png')."
    )
    args = parser.parse_args()

    try:
        w, h = map(int, args.dimensions.split('x'))
        pattern_size = (w, h)
    except ValueError:
        print(f"Error: --dimensions must be in WxH format, e.g., '4x5'. Got '{args.dimensions}'.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.image):
        print(f"Error: Image file not found at '{args.image}'", file=sys.stderr)
        sys.exit(1)

    img = cv2.imread(args.image)
    if img is None:
        print(f"Error: Could not read image at '{args.image}'", file=sys.stderr)
        sys.exit(1)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Find the chess board corners
    ret, corners = cv2.findChessboardCorners(gray, pattern_size, None)

    if not ret:
        print("Checkerboard not found in the image.", file=sys.stderr)
        sys.exit(1)

    # Refine corner positions to sub-pixel accuracy
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners_subpix = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)

    # Generate 3D keypoints in object space.
    # The example JSON file (000177.json) has 3D points in column-major order.
    # We generate them here to match that format, assuming findChessboardCorners
    # returns 2D points in the same order.
    keypoints3d = []
    for i in range(pattern_size[0]):  # width (cols)
        for j in range(pattern_size[1]):  # height (rows)
            keypoints3d.append([i * args.grid, j * args.grid, 0.0])

    # Format 2D keypoints
    keypoints2d = []
    for corner in corners_subpix:
        keypoints2d.append([float(corner[0][0]), float(corner[0][1]), 1.0])

    # Prepare data for JSON output, matching the example format
    output_data = {
        "keypoints3d": keypoints3d,
        "keypoints2d": keypoints2d,
        "pattern": [pattern_size[1], pattern_size[0]],  # As per example: [H, W]
        "grid_size": args.grid,
        "visited": True
    }

    # Determine output file path
    if args.output:
        output_path = args.output
    else:
        base_name = os.path.basename(args.image)
        name_without_ext = os.path.splitext(base_name)[0]
        output_path = f"{name_without_ext}.json"

    # Write data to JSON file
    try:
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=4)
        print(f"Successfully found checkerboard. Output written to {output_path}")
    except IOError as e:
        print(f"Error writing to file {output_path}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    find_checkerboard()
