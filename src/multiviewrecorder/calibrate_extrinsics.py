#!/usr/bin/env python

import argparse
import glob
import os
import sys
import json
import cv2
import numpy as np
try:
    import yaml
except ImportError:
    print("This script requires the PyYAML package.")
    print("Please install it using: pip install pyyaml")
    sys.exit(1)


# Add a constructor for the !!opencv-matrix tag, treating it as a regular mapping.
def opencv_matrix_constructor(loader, node):
    return loader.construct_mapping(node, deep=True)

yaml.SafeLoader.add_constructor('tag:yaml.org,2002:opencv-matrix', opencv_matrix_constructor)


def read_intrinsics(intri_path):
    """
    Reads an OpenCV-style YAML file with camera intrinsic parameters.
    """
    if not os.path.exists(intri_path):
        print(f"Error: Intrinsic file not found at '{intri_path}'", file=sys.stderr)
        return None
    try:
        with open(intri_path, 'r') as f:
            # PyYAML doesn't like the OpenCV header, so we read lines and skip it
            lines = f.readlines()
            if lines and lines[0].startswith('%YAML'):
                lines = lines[1:]
            data = yaml.safe_load("".join(lines))
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file {intri_path}: {e}", file=sys.stderr)
        return None

    intrinsics = {}
    cam_names = data.get('names', [])
    for name in cam_names:
        k_data = data.get(f'K_{name}')
        dist_data = data.get(f'dist_{name}')

        if not k_data or not dist_data:
            print(f"Warning: Missing K_{name} or dist_{name} in {intri_path}", file=sys.stderr)
            continue

        try:
            K = np.array(k_data['data'], dtype=np.float64).reshape(k_data['rows'], k_data['cols'])
            dist = np.array(dist_data['data'], dtype=np.float64).reshape(dist_data['rows'], dist_data['cols'])
            intrinsics[name] = {'K': K, 'dist': dist}
        except (KeyError, TypeError) as e:
            print(f"Warning: Malformed matrix data for camera {name} in {intri_path}: {e}", file=sys.stderr)
            continue
            
    return intrinsics

def write_extrinsics(output_path, extrinsics, cam_names):
    """
    Writes extrinsic parameters to a YAML file in OpenCV format.
    """
    try:
        with open(output_path, 'w') as f:
            f.write("%YAML:1.0\n---\n")
            f.write("names:\n")
            for name in cam_names:
                f.write(f'  - "{name}"\n')

            for name in sorted(extrinsics.keys()):
                ext = extrinsics[name]
                rvec, rot, tvec = ext['Rvec'], ext['Rot'], ext['T']

                for key, matrix in [('R', rvec), ('Rot', rot), ('T', tvec)]:
                    f.write(f"{key}_{name}: !!opencv-matrix\n")
                    f.write(f"  rows: {matrix.shape[0]}\n")
                    f.write(f"  cols: {matrix.shape[1] if len(matrix.shape) > 1 else 1}\n")
                    f.write("  dt: d\n")
                    data_str = ", ".join([f"{x:.6f}" for x in matrix.flatten()])
                    f.write(f"  data: [{data_str}]\n")
        print(f"Extrinsic parameters successfully written to {output_path}")
    except IOError as e:
        print(f"Error writing to file {output_path}: {e}", file=sys.stderr)

def calibrate_extrinsics():
    parser = argparse.ArgumentParser(description="Perform extrinsic camera calibration using chessboard corners.")
    parser.add_argument("path", help="Root directory containing the 'chessboard' folder.")
    parser.add_argument("--intri", required=True, help="Path to the intrinsic calibration file (intri.yml).")
    parser.add_argument('--image_id', type=int, default=0, help="Index of the JSON file to use for calibration (default: 0).")
    parser.add_argument("--output", help="Path to the output extrinsic file. Defaults to 'extri.yml' in the root path.")
    args = parser.parse_args()

    intrinsics = read_intrinsics(args.intri)
    if not intrinsics:
        sys.exit(1)

    cam_names = sorted(intrinsics.keys())
    extrinsics = {}

    for cam in cam_names:
        cam_chessboard_dir = os.path.join(args.path, 'chessboard', cam)
        json_files = sorted(glob.glob(os.path.join(cam_chessboard_dir, '*.json')))

        if not json_files:
            print(f"Warning: No JSON files found for camera '{cam}' in '{cam_chessboard_dir}'. Skipping.", file=sys.stderr)
            continue

        if args.image_id >= len(json_files):
            print(f"Warning: --image_id {args.image_id} is out of bounds for camera '{cam}' (found {len(json_files)} files). Skipping.", file=sys.stderr)
            continue

        json_path = json_files[args.image_id]

        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            k3d = np.array(data['keypoints3d'], dtype=np.float32)
            k2d = np.array(data['keypoints2d'], dtype=np.float32)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: Could not read or parse '{json_path}': {e}. Skipping camera '{cam}'.", file=sys.stderr)
            continue

        K = intrinsics[cam]['K']
        dist = intrinsics[cam]['dist']

        # Use only valid points (where the 3rd element of k2d, often confidence, is > 0)
        valid_indices = k2d[:, 2] > 0
        k3d_valid = k3d[valid_indices]
        k2d_valid = k2d[valid_indices, :2]

        if len(k3d_valid) < 4:
            print(f"Warning: Not enough valid points (<4) for camera '{cam}'. Skipping.", file=sys.stderr)
            continue

        ret, rvec, tvec = cv2.solvePnP(k3d_valid, k2d_valid, K, dist, flags=cv2.SOLVEPNP_ITERATIVE)

        if ret:
            rot, _ = cv2.Rodrigues(rvec)
            extrinsics[cam] = {'Rvec': rvec, 'Rot': rot, 'T': tvec}
            
            # Calculate and print reprojection error
            reprojected_pts, _ = cv2.projectPoints(k3d_valid, rvec, tvec, K, dist)
            err = np.linalg.norm(reprojected_pts.squeeze() - k2d_valid, axis=1).mean()
            center = -rot.T @ tvec
            print(f"Camera '{cam}': Reprojection error = {err:.3f}px, Camera center = {center.squeeze()}")
        else:
            print(f"Warning: solvePnP failed for camera '{cam}'.", file=sys.stderr)
    
    if not extrinsics:
        print("Error: Extrinsic calibration failed for all cameras.", file=sys.stderr)
        sys.exit(1)

    output_file = args.output if args.output else os.path.join(args.path, 'extri.yml')
    write_extrinsics(output_file, extrinsics, cam_names)

if __name__ == "__main__":
    calibrate_extrinsics()
