# multi view recorder
concurrent recording of multiple webcams on linux using v4l2. 


## install

```
uv add git+https://github.com/daan/multiviewrecorder
```

## usage

```
usage: mvr.py [-h] [--config CONFIG] [--vid VID] [--pid PID] [--resolution RESOLUTION] [--framerate FRAMERATE] [--input_format INPUT_FORMAT]

Record from multiple v4l2 cameras, displaying previews.

optional arguments:
  -h, --help            show this help message and exit
  --config CONFIG       Path to a TOML configuration file.
  --vid VID             Filter by vendor ID (e.g., 046d).
  --pid PID             Filter by product ID (e.g., 082d).
  --resolution RESOLUTION
                        Video resolution (e.g., 1280x720). Overrides config file.
  --framerate FRAMERATE
                        Video framerate (e.g., 30). Overrides config file.
  --input_format INPUT_FORMAT
                        Input format (e.g., mjpeg). Overrides config file.
```

```
# cameras.toml                                                                                                                                                                           
resolution = "1920x1080"                                                                                                                                                                 
framerate = "30"                                                                                                                                                                         
input_format = "mjpeg"                                                                                                                                                                   
                                                                                                                                                                                         
[[cameras]]                                                                                                                                                                              
serial = "SERIAL_OF_LEFT_CAMERA"                                                                                                                                                         
name = "01_left"                                                                                                                                                                         
                                                                                                                                                                                         
[[cameras]]                                                                                                                                                                              
serial = "SERIAL_OF_RIGHT_CAMERA"                                                                                                                                                        
name = "02_right"     
```

## about

Made in Umeå with ♥ and mostly vibe coding.

