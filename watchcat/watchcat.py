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

    __NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE = 3
    __NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY = 5

    # width, height: if both width and height are set, we will set the
    #   dimensions of the captured camera image to these dimensions. The
    #   units are pixels. Using smaller dimensions will speed up face
    #   detection.
    #
    # mid_col_pct: Middle column percentage. The portion of the captured image
    #   to capture for face detection. Should be a float in (0,1]
    #
    # Explanation of how width and mid_col_pct interact:
    # The camera's native resolution is 4608x2592. If we set mid_col_pct to
    # 1/3, then the middle third of the image will be used - we will use the
    # middle 1536 pixels of the captured image. If you think of the image as divided
    # into 3 columns, we will be using the middle column. At this point, we have a
    # captured image that is 1536x2592. We will scale this image down to the width
    # specified by the `width` parameter. That is, if `width` is 150, we will
    # proportionally scale the captured image such that it becomes 150x253.
    #
    # show_preview: if True, we will send a live feed of the captured
    #   images via SSH X11 forwarding.
    def __init__(self, width=None, height=None, mid_col_pct=1 / 3, show_preview=False):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting WatchCat...")

        self.__picam2 = picamera2.Picamera2()
        self.__num_consecutive_face_frames = 0
        self.__num_consecutive_empty_frames = 0
        self.__confirmed_face_locations = []
        self.__mid_col_pct = mid_col_pct
        self.__crop_x0 = None
        self.__crop_x1 = None

        # See the camera modes here:
        # https://github.com/raspberrypi/picamera2/issues/914#issuecomment-1879949316
        mode = self.__picam2.sensor_modes[1]
        main = {}
        if width is not None and height is not None:
            main = {"size": (width, height)}

        display = None # controls which streams will be shown in the preview
        if show_preview:
            display = 'main'
            self.__setup_camera_preview()

        # raw: ensure we get the full field of view even when using a small viewport. See:
        # * https://github.com/raspberrypi/picamera2/discussions/567
        # * For pi camera v1 and v2 modules, but a similar concept applies for v3 (we use v3):
        #   https://picamera.readthedocs.io/en/release-1.13/fov.html#sensor-modes
        #
        # buffer_count: this parameter is extremely important for the main loop performance! We must
        #   increase it from the default value of 1 - otherwise `picam2.capture_array()` performance
        #   would suffer. See: https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf#_more_on_the_buffer_count
        #   (Sections 4.2.1.3. "More on the buffer_count" and 4.2.1.4. "More on the queue parameter")
        config = self.__picam2.create_still_configuration(
            main=main, display=display, raw={'size': mode['size']}, buffer_count=2
        )
        self.__picam2.align_configuration(config)
        self.__logger.info(f"Using aligned picam config: {config}")

        self.__picam2.configure(config)
        self.__picam2.start()

        self.__picam2.set_controls({
            "AfMode": libcamera.controls.AfModeEnum.Continuous,  # TODO: is this AF stuff working?
            "AfRange": libcamera.controls.AfRangeEnum.Full,
            "AfSpeed": libcamera.controls.AfSpeedEnum.Fast,
        })

        self.__unix_socket_helper = UnixSocketHelper()
        self.__unix_socket_helper.connect(TickController.UNIX_SOCKET_PATH)

        self.__logger.info("Finished starting WatchCat.")

    """
    A note on timing the main loop - we provide 3 timings in the logs:
    1) loop timing
    2) image capture timing
    3) face detection timing

    This inequality will be satisfied: (1) <= (2) + (3). The image capture timing (2)
    can be deceptive. Make sure to pay attention to the overall loop timing when making
    performance optimizations.

    See:
    * https://gist.github.com/dasl-/768b53593a420f740933063b7a335fdc
    * https://github.com/dasl-/watchcat/commit/68463a40320fd733b68525f9a4db3dea92e48567
    """
    def run(self):
        # haarcascade_frontalface_alt2 seemed to be the best model for detecting Ryans' face (beard + glasses)
        # we also tried haarcascade_frontalface_default, haarcascade_frontalface_alt, haarcascade_frontalface_alt_tree, and
        # haarcascade_eye_tree_eyeglasses
        face_detector = cv2.CascadeClassifier(f"{os.path.dirname(os.path.dirname(__file__))}/data/haarcascade_frontalface_alt2.xml")
        is_paused = False
        while True:
            loop_start = time.time()
            # Grab a single frame of video from the RPi camera as a numpy array
            uncropped_output = self.__picam2.capture_array()
            img_capture_elapsed_s = round(time.time() - loop_start, 3)

            # Crop the image with numpy. See a performance comparison of different cropping methods:
            # https://gist.github.com/dasl-/cda68e8fef981edf9727c5995129b864
            if self.__crop_x0 is None:
                crop_width = uncropped_output.shape[1] * self.__mid_col_pct
                self.__crop_x0 = (uncropped_output.shape[1] - crop_width) / 2
                self.__crop_x1 = int(round(self.__crop_x0 + crop_width))
                self.__crop_x0 = int(round(self.__crop_x0))
            output = uncropped_output[:, self.__crop_x0:self.__crop_x1, :]

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
            face_locations = face_detector.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=4, maxSize=(140, 140), minSize=(15, 15))
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
                f"{round(now - loop_start, 3)} s. Image capture took {img_capture_elapsed_s} s. " +
                f"Face detect took {round(now - face_detect_start, 3)} s. Image dimensions: {output.shape}")

    def __setup_camera_preview(self):
        self.__picam2.start_preview(picamera2.Preview.QT)

        def draw_faces(request):
            (w0, h0) = self.__picam2.stream_configuration("main")["size"]
            (w1, h1) = self.__picam2.stream_configuration("main")["size"]
            with picamera2.MappedArray(request, "main") as m:
                if self.__crop_x0 is not None:
                    # Place black bars on the sides of the image where we cropped them out
                    cv2.rectangle(img=m.array, pt1=(0, 0), pt2=(self.__crop_x0, h0), color=(0, 0, 0, 0), thickness=-1)
                    cv2.rectangle(img=m.array, pt1=(self.__crop_x1, 0), pt2=(w0, h0), color=(0, 0, 0, 0), thickness=-1)

                for f in self.__confirmed_face_locations:
                    (x, y, w, h) = [c * n // d for c, n, d in zip(f, (w0, h0) * 2, (w1, h1) * 2)]
                    x = x + self.__crop_x0
                    cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0))
                    self.__logger.info(f"draw_faces face width x height: {w} x {h}")

        self.__picam2.post_callback = draw_faces
