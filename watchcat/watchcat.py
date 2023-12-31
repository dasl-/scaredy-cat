import picamera2
import time
import cv2
import libcamera
import os
import traceback

from watchcat.logger import Logger
from watchcat.unixsockethelper import UnixSocketHelper
from watchcat.tickcontroller import TickController

# See specs for raspberry pi camera module 3:
# https://www.raspberrypi.com/documentation/accessories/camera.html#hardware-specification
#
# See picamera2 library docs:
# https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
class WatchCat:

    __instance = None

    __ASPECT_RATIO = 16 / 9

    __NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE = 3
    __NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY = 5

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
        self.__num_consecutive_face_frames = 0
        self.__num_consecutive_empty_frames = 0

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
                if self.__num_consecutive_face_frames < self.__NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE:
                    return

                (w0, h0) = self.__picam2.stream_configuration("main")["size"]
                (w1, h1) = self.__picam2.stream_configuration("main")["size"]
                self.__logger.info(f"draw_faces dims: {self.__confirmed_face_locations} {self.__picam2} {w0} {h0} {w1} {h1}")
                with picamera2.MappedArray(request, "main") as m:
                    for f in self.__confirmed_face_locations:
                        (x, y, w, h) = [c * n // d for c, n, d in zip(f, (w0, h0) * 2, (w1, h1) * 2)]
                        cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0))
                        self.__logger.info(f"draw_faces face width x height: {w} x {h}")

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
        self.__confirmed_face_locations = []

        self.__unix_socket_helper = UnixSocketHelper()
        self.__unix_socket_helper.connect(TickController.UNIX_SOCKET_PATH)

    def run(self):
        # haarcascade_frontalface_alt2 seemed to be the best model for detecting Ryans' face (beard + glasses)
        # we also tried haarcascade_frontalface_default, haarcascade_frontalface_alt, haarcascade_frontalface_alt_tree, and
        # haarcascade_eye_tree_eyeglasses
        face_detector = cv2.CascadeClassifier(f"{os.path.dirname(os.path.dirname(__file__))}/data/haarcascade_frontalface_alt2.xml")
        is_paused = False
        while True:
            loop_start = time.time()
            self.__logger.info("Capturing image...")

            img_capture_start = time.time()
            # Grab a single frame of video from the RPi camera as a numpy array
            output = self.__picam2.capture_array()
            img_capture_end = time.time()

            face_detect_start = time.time()
            # Find all the faces and face encodings in the current frame of video
            gray = cv2.cvtColor(output, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            # detectMultiScale docs:
            # * https://docs.opencv.org/4.7.0/d1/de5/classcv_1_1CascadeClassifier.html#aaf8181cb63968136476ec4204ffca498
            # * https://stackoverflow.com/a/55628240
            # * https://github.com/raspberrypi/picamera2/blob/main/examples/opencv_face_detect.py
            # * https://answers.opencv.org/question/10654/how-does-the-parameter-scalefactor-in-detectmultiscale-affect-face-detection/
            # * https://stackoverflow.com/questions/22249579/opencv-detectmultiscale-minneighbors-parameter
            face_locations = face_detector.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=4, maxSize=(140,140), minSize=(15, 15))
            now = time.time()
            if len(face_locations) > 0:
                self.__num_consecutive_face_frames = self.__num_consecutive_face_frames + 1
                if self.__num_consecutive_face_frames >= self.__NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE:
                    self.__num_consecutive_empty_frames = 0
                    self.__confirmed_face_locations = face_locations
                    if not is_paused:
                        self.__unix_socket_helper.send_msg(TickController.PAUSE_SIGNAL)
                        is_paused = True
                        self.__logger.info("Found a confirmed face")
            elif len(face_locations) <= 0:
                self.__num_consecutive_empty_frames = self.__num_consecutive_empty_frames + 1
                if self.__num_consecutive_empty_frames >= self.__NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY:
                    self.__num_consecutive_face_frames = 0
                    self.__confirmed_face_locations = []
                    if is_paused:
                        self.__unix_socket_helper.send_msg(TickController.UNPAUSE_SIGNAL)
                        is_paused = False
                        self.__logger.info("Lost a confirmed face [found]")
            self.__logger.info(f"Found {len(face_locations)} faces in image. Loop took " +
                f"{round(now - loop_start, 3)} s. Image capture took {round(img_capture_end - img_capture_start, 3)} s. Face detect took {round(now - face_detect_start, 3)} s.")
