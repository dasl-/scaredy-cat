#!/usr/bin/env python3

# See https://github.com/dasl-/scaredy-cat/blob/main/docs/issues_weve_seen_before.adoc#blurry-images-autofocus--focus-problems

import libcamera
import time
from picamera2 import Picamera2
picam2 = Picamera2()
picam2.configure(picam2.create_still_configuration())
picam2.start()

for lens_position in range(16):
    picam2.set_controls({"AfMode": libcamera.controls.AfModeEnum.Manual, "LensPosition": lens_position})
    time.sleep(1)
    r = picam2.capture_request()
    filename = "lens-position" + str(lens_position) + ".jpg"
    metadata = r.get_metadata()
    actual_lens_position = metadata["LensPosition"]
    print("Actual LensPosition = {}, file capture in file {}".format(actual_lens_position,filename))
    r.save("main", filename)
    r.release()

picam2.stop()
