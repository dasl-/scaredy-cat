import picamera2
import time
import cv2
import libcamera
import os
import traceback

from watchcat.logger import Logger
from watchcat.unixsockethelper import UnixSocketHelper
from watchcat.motor import Motor

class WatchCat:

    __instance = None

    __ASPECT_RATIO = 16 / 9

    # width, height: if both width and height are set, we will set the
    #   dimensions of the captured camera image to these dimensions. The
    #   units are pixels. Using smaller dimensions will speed up face
    #   detection.
    #
    # show_preview: if True, we will send a live feed of the captured
    #   images via SSH X11 forwarding.
    def __init__(self, width=None, height=None, show_preview=False):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting WatchCat...")

        self.__picam2 = picamera2.Picamera2()

        main = {}
        if width is not None and height is not None:
            pass
            main = {"size": (width, height)} #  x
            # main = {}

        display = None # controls which streams will be shown in the preview
        if show_preview:
            self.__picam2.start_preview(picamera2.Preview.QT)
            display = 'main'

            def draw_faces(request):
                (w0, h0) = self.__picam2.stream_configuration("main")["size"]
                (w1, h1) = self.__picam2.stream_configuration("main")["size"]
                self.__logger.info(f"draw_faces dims: {self.__face_locations} {self.__picam2} {w0} {h0} {w1} {h1}")
                with picamera2.MappedArray(request, "main") as m:
                    for f in self.__face_locations:
                        (x, y, w, h) = [c * n // d for c, n, d in zip(f, (w0, h0) * 2, (w1, h1) * 2)]
                        cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0))

            self.__picam2.post_callback = draw_faces

        # raw: ensure we get the full field of view even when using a small viewport. See:
        # * https://github.com/raspberrypi/picamera2/discussions/567
        # * For pi camera v1 and v2 modules, but a similar concept applies for v3 (we use v3):
        #   https://picamera.readthedocs.io/en/release-1.13/fov.html#sensor-modes
        config = self.__picam2.create_still_configuration(main=main, display=display, raw={'size': self.__picam2.sensor_resolution})
        self.__logger.info(f"Using picam config: {config}")

        self.__picam2.configure(config)
        self.__picam2.start()
        self.__picam2.set_controls({"AfMode": libcamera.controls.AfModeEnum.Continuous, "AfRange": libcamera.controls.AfRangeEnum.Full, "AfSpeed":libcamera.controls.AfSpeedEnum.Fast}) # TODO: is this working?

        self.__logger.info("Finished starting WatchCat.")
        self.__face_locations = []

        self.__unix_socket_helper = UnixSocketHelper()
        self.__unix_socket_helper.connect(Motor.UNIX_SOCKET_PATH)

    def run(self):
        face_detector = cv2.CascadeClassifier(f"{os.path.dirname(os.path.dirname(__file__))}/data/haarcascade_frontalface_default.xml")
        while True:
            loop_start = time.time()
            self.__logger.info("Capturing image...")
            # Grab a single frame of video from the RPi camera as a numpy array
            output = self.__picam2.capture_array()
            self.__logger.info(f"Done capturing image. Output shape: {output.shape}")
            metadata = self.__picam2.capture_metadata()
            self.__logger.info(f"metadata: {metadata}")

            face_detect_start = time.time()
            # Find all the faces and face encodings in the current frame of video
            grey = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)

            # detectMultiScale docs:
            # * https://docs.opencv.org/4.7.0/d1/de5/classcv_1_1CascadeClassifier.html#aaf8181cb63968136476ec4204ffca498
            # * https://stackoverflow.com/a/55628240
            # * https://github.com/raspberrypi/picamera2/blob/main/examples/opencv_face_detect.py
            self.__face_locations = face_detector.detectMultiScale(grey, 1.1, 5)
            now = time.time()
            if (len(self.__face_locations) > 0):
                self.__unix_socket_helper.send_msg(Motor.PAUSE_SIGNAL) # TODO: this seems backwards?
            else:
                self.__unix_socket_helper.send_msg(Motor.RUN_SIGNAL)
            self.__logger.info(f"Found {len(self.__face_locations)} faces in image. Face locations: {self.__face_locations}. Loop took " +
                f"{now - loop_start} s. Face detect took {now - face_detect_start} s.")
