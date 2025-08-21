#!/usr/bin/env python

import argparse
import glob
import os
import sys
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

def read_yml(path):
    if not os.path.exists(path):
        print(f"Error: File not found at '{path}'", file=sys.stderr)
        return None
    try:
        with open(path, 'r') as f:
            lines = f.readlines()
            if lines and lines[0].startswith('%YAML'):
                lines = lines[1:]
            data = yaml.safe_load("".join(lines))
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file {path}: {e}", file=sys.stderr)
        return None
    return data

def read_cameras(calib_path):
    intri_path = os.path.join(calib_path, 'intri.yml')
    extri_path = os.path.join(calib_path, 'extri.yml')

    intri_data = read_yml(intri_path)
    extri_data = read_yml(extri_path)

    if not intri_data or not extri_data:
        sys.exit(1)

    cameras = {}
    cam_names = intri_data.get('names', [])
    for name in cam_names:
        k_data = intri_data.get(f'K_{name}')
        dist_data = intri_data.get(f'dist_{name}')
        
        rot_data = extri_data.get(f'Rot_{name}')
        t_data = extri_data.get(f'T_{name}')

        if not all([k_data, dist_data, rot_data, t_data]):
            print(f"Warning: Missing camera parameters for {name}", file=sys.stderr)
            continue

        try:
            K = np.array(k_data['data'], dtype=np.float64).reshape(k_data['rows'], k_data['cols'])
            dist = np.array(dist_data['data'], dtype=np.float64).reshape(dist_data['rows'], dist_data['cols'])
            R = np.array(rot_data['data'], dtype=np.float64).reshape(rot_data['rows'], rot_data['cols'])
            T = np.array(t_data['data'], dtype=np.float64).reshape(t_data['rows'], t_data['cols'])
            cameras[name] = {'K': K, 'dist': dist, 'R': R, 'T': T}
        except (KeyError, TypeError) as e:
            print(f"Warning: Malformed matrix data for camera {name}: {e}", file=sys.stderr)
            continue
            
    return cameras

def load_cube(grid_size=1.0):
    min_x, min_y, min_z = (0, 0, 0.)
    max_x, max_y, max_z = (grid_size, grid_size, grid_size)
    points3d = np.array([
        [min_x, min_y, min_z],
        [max_x, min_y, min_z],
        [max_x, max_y, min_z],
        [min_x, max_y, min_z],
        [min_x, min_y, max_z],
        [max_x, min_y, max_z],
        [max_x, max_y, max_z],
        [min_x, max_y, max_z],
    ], dtype=np.float32)
    lines = np.array([
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7]
    ], dtype=int)
    return points3d, lines

def visualize_extrinsics():
    parser = argparse.ArgumentParser(description="Visualize a wireframe cube in camera images using calibration files.")
    parser.add_argument("path", help="Path to the directory containing intri.yml, extri.yml, and images folder.")
    args = parser.parse_args()

    cameras = read_cameras(args.path)
    if not cameras:
        print("Error: Could not read camera parameters.", file=sys.stderr)
        sys.exit(1)
        
    cam_names = sorted(cameras.keys())
    points3d, lines = load_cube(grid_size=1.0)

    images_out = []
    for cam in cam_names:
        camera = cameras[cam]
        
        image_dir = os.path.join(args.path, 'images', cam)
        image_files = []
        for ext in ('*.jpg', '*.png', '*.jpeg', '*.bmp', '*.tiff'):
            image_files.extend(glob.glob(os.path.join(image_dir, ext)))
        
        image_files.sort()

        if not image_files:
            print(f"Warning: No images found for camera '{cam}' in '{image_dir}'. Skipping.", file=sys.stderr)
            continue
        
        img_path = image_files[0]
        img = cv2.imread(img_path)
        if img is None:
            print(f"Warning: Could not read image '{img_path}'. Skipping.", file=sys.stderr)
            continue

        # Project 3D points to 2D image plane (distorted)
        rvec, _ = cv2.Rodrigues(camera['R'])
        tvec = camera['T']
        points2d_dist, _ = cv2.projectPoints(points3d, rvec, tvec, camera['K'], camera['dist'])

        # Undistort image and points
        img_undistorted = cv2.undistort(img, camera['K'], camera['dist'])
        points2d_undist = cv2.undistortPoints(points2d_dist, camera['K'], camera['dist'], P=camera['K'])
        
        points2d = points2d_undist.squeeze().astype(int)
        
        # Draw lines of the cube
        for line in lines:
            p1 = tuple(points2d[line[0]])
            p2 = tuple(points2d[line[1]])
            cv2.line(img_undistorted, p1, p2, (0, 0, 255), 2, cv2.LINE_AA) # Red color, thickness 2
            
        images_out.append(img_undistorted)

    if not images_out:
        print("No images were processed.", file=sys.stderr)
        sys.exit(1)

    # Juxtapose images and display
    final_image = cv2.hconcat(images_out)
    
    # Resize if too large to fit on screen
    max_width = 1920
    if final_image.shape[1] > max_width:
        scale = max_width / final_image.shape[1]
        final_image = cv2.resize(final_image, (0,0), fx=scale, fy=scale)

    cv2.imshow('Projected Cube', final_image)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

if __name__ == "__main__":
    visualize_extrinsics()
