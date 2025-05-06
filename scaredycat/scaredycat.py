import picamera2
import time
import cv2
import libcamera
import os
import traceback
import numpy as np

from scaredycat.logger import Logger
from scaredycat.unixsockethelper import UnixSocketHelper
from scaredycat.tickcontroller import TickController

# See specs for raspberry pi camera module 3:
# https://www.raspberrypi.com/documentation/accessories/camera.html#hardware-specification
#
# See picamera2 library docs:
# https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf
class ScaredyCat:

    __NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE = 1
    __NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY = 2
    __MIN_FACE_WIDTH = 30
    __MIN_FACE_HEIGHT = 40
    __FACE_DETECTION_MINIMUM_SCORE = 0.65 # float in range [0, 1]: how confident the face detection is in a given face

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
        self.__logger.info("Starting ScaredyCat...")

        self.__picam2 = picamera2.Picamera2()
        self.__num_consecutive_face_frames = 0
        self.__num_consecutive_empty_frames = 0
        self.__confirmed_face_locations = []
        self.__unconfirmed_face_locations = []
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
            self.__setup_camera_preview(width, height)

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

        self.__logger.info("Finished starting ScaredyCat.")

    """
    A note on timing the main loop - we provide 3 timings in the logs:
    1) loop timing
    2) image capture timing
    3) face detection timing

    This inequality will be satisfied: (1) <= (2) + (3). The image capture timing (2)
    can be deceptive. Make sure to pay attention to the overall loop timing when making
    performance optimizations.

    By setting a FrameRate, we could go even faster. But the tradeoff is we'd get darker images,
    which might result in worse face detection. We haven't experimented to decide if it's
    worth the tradeoff yet: https://github.com/raspberrypi/picamera2/issues/914#issuecomment-1880177348

    Relatedly, if we don't explicitly set a FrameRate, the loop speed varies depending on the
    brightness of the room. This is because the camera spends a longer time exposing the image
    in a dark room.

    In a dark room, we might see something like this:

        Found 0 faces in image. Loop took 0.119 s. Image capture took 0.056 s. Face detect took 0.063 s. Image dimensions: (252, 150, 3)

    Whereas in a bright room, it will be faster:

        Found 0 faces in image. Loop took 0.062 s. Image capture took 0.002 s. Face detect took 0.061 s. Image dimensions: (252, 150, 3)

    See also:
    * https://gist.github.com/dasl-/768b53593a420f740933063b7a335fdc
    * https://github.com/dasl-/scaredy-cat/commit/68463a40320fd733b68525f9a4db3dea92e48567
    """
    def run(self):
        is_paused = False

        cam_img_w, cam_img_h = self.__picam2.camera_configuration()['main']['size']
        self.__logger.info(f"Using cam_img_w x cam_img_h: {cam_img_w} x {cam_img_h}")
        cropped_img_w = cam_img_w * self.__mid_col_pct
        self.__crop_x0 = (cam_img_w - cropped_img_w) / 2
        self.__crop_x1 = int(round(self.__crop_x0 + cropped_img_w))
        self.__crop_x0 = int(round(self.__crop_x0))

        # See:
        # https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html
        # https://docs.opencv.org/4.x/df/d20/classcv_1_1FaceDetectorYN.html#a42293cf2d64f8b69a707ab70d11925b3
        # https://github.com/opencv/opencv_zoo/blob/80f7c6aa030a87b3f9e8ab7d84f62f13d308c10f/models/face_detection_yunet/yunet.py#L15
        face_detector = cv2.FaceDetectorYN.create(
            model = os.path.abspath(os.path.dirname(__file__) + '/../data/face_detection_yunet_2023mar.onnx'),
            config="", input_size = (self.__crop_x1 - self.__crop_x0, cam_img_h),
            score_threshold = self.__FACE_DETECTION_MINIMUM_SCORE
        )
        while True:
            loop_start = time.time()
            # Grab a single frame of video from the RPi camera as a numpy array
            uncropped_output = self.__picam2.capture_array()
            img_capture_elapsed_s = round(time.time() - loop_start, 3)

            # Crop the image with numpy. See a performance comparison of different cropping methods:
            # https://gist.github.com/dasl-/cda68e8fef981edf9727c5995129b864
            output = uncropped_output[:, self.__crop_x0:self.__crop_x1, :]

            face_detect_start = time.time()
            # Find all the faces and face encodings in the current frame of video

            ignore, face_locations = face_detector.detect(output)
            if face_locations is None:
                face_locations = []
            now = time.time()
            if len(face_locations) > 0:
                face_locations = self.__filterFacesByDimensions(face_locations, cam_img_w, cam_img_h)

            if len(face_locations) > 0:
                self.__num_consecutive_face_frames = self.__num_consecutive_face_frames + 1
                if self.__num_consecutive_face_frames >= self.__NUM_CONSECUTIVE_FACE_FRAMES_TO_CONFIRM_FACE:
                    self.__num_consecutive_empty_frames = 0
                    self.__confirmed_face_locations = face_locations
                    self.__unconfirmed_face_locations = []
                    if not is_paused:
                        self.__unix_socket_helper.send_msg(TickController.PAUSE_SIGNAL)
                        is_paused = True
                        self.__logger.info(f"Found a confirmed face: {face_locations}")
                else:
                    self.__unconfirmed_face_locations = face_locations
            elif len(face_locations) <= 0:
                self.__unconfirmed_face_locations = []
                self.__num_consecutive_empty_frames = self.__num_consecutive_empty_frames + 1
                if self.__num_consecutive_empty_frames >= self.__NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY:
                    self.__num_consecutive_face_frames = 0
                    self.__confirmed_face_locations = []
                    if is_paused:
                        self.__unix_socket_helper.send_msg(TickController.UNPAUSE_SIGNAL)
                        is_paused = False
                        self.__logger.info("Lost a confirmed face")

            self.__logger.info(f"Found {len(face_locations)} faces in image. Loop took " +
                f"{round(now - loop_start, 3)} s. Image capture took {img_capture_elapsed_s} s. " +
                f"Face detect took {round(now - face_detect_start, 3)} s. Image dimensions: {output.shape}")

    def __filterFacesByDimensions(self, face_locations, cam_img_w, cam_img_h):
        face_dimensions_above_threshold = []
        face_dimensions_below_threshold = []
        face_indices_above_threshold = []

        # Iterate through the list in reverse order because we may delete items from the list as we iterate
        for i in reversed(range(len(face_locations))):
            face = face_locations[i]
            (x, y, w, h) = [c * n // d for c, n, d in zip(face, (cam_img_w, cam_img_h) * 2, (cam_img_w, cam_img_h) * 2)]
            x = x + self.__crop_x0
            if (w < self.__MIN_FACE_WIDTH or h < self.__MIN_FACE_HEIGHT) and len(self.__confirmed_face_locations) <= 0:
                # Don't drop a face if we have already confirmed it -- if a face is on the cusp of being below the
                # minimum dimensions, we don't want it to flap if the dimensions vary slightly
                face_dimensions_below_threshold.append((int(w), int(h)))
            else:
                face_dimensions_above_threshold.append((int(w), int(h)))
                face_indices_above_threshold.append(i)

        if face_dimensions_above_threshold:
            self.__logger.info(f"faces above the minimum dimensions threshold, width x height: {face_dimensions_above_threshold}")
        if face_dimensions_below_threshold:
            self.__logger.info("faces dropped because they were below the minimum dimensions threshold, width x height: " +
                f"{face_dimensions_below_threshold}")

        # https://stackoverflow.com/a/7139454/22828008
        faces_above_threshold = face_locations[face_indices_above_threshold]
        return faces_above_threshold

    def __setup_camera_preview(self, stream_img_w, stream_img_h):
        self.__picam2.start_preview(picamera2.Preview.QT)

        def draw_faces(request):
            with picamera2.MappedArray(request, "main") as m:
                # Place black bars on the sides of the image where we cropped them out
                cv2.rectangle(img=m.array, pt1=(0, 0), pt2=(self.__crop_x0, stream_img_h), color=(0, 0, 0, 0), thickness=-1)
                cv2.rectangle(img=m.array, pt1=(self.__crop_x1, 0), pt2=(stream_img_w, stream_img_h), color=(0, 0, 0, 0), thickness=-1)

                if isinstance(self.__confirmed_face_locations, np.ndarray) and self.__confirmed_face_locations.size > 0:
                    self.__confirmed_face_locations = self.__confirmed_face_locations[:, 0:4].astype(np.int16)
                for f in self.__confirmed_face_locations:
                    (x, y, w, h) = [c * n // d for c, n, d in zip(f, (stream_img_w, stream_img_h) * 2, (stream_img_w, stream_img_h) * 2)]
                    x = x + self.__crop_x0
                    cv2.rectangle(m.array, (x, y), (x + w, y + h), (0, 255, 0, 0))

                if isinstance(self.__unconfirmed_face_locations, np.ndarray) and self.__unconfirmed_face_locations.size > 0:
                    self.__unconfirmed_face_locations = self.__unconfirmed_face_locations[:, 0:4].astype(np.int16)
                for f in self.__unconfirmed_face_locations:
                    (x, y, w, h) = [c * n // d for c, n, d in zip(f, (stream_img_w, stream_img_h) * 2, (stream_img_w, stream_img_h) * 2)]
                    x = x + self.__crop_x0
                    cv2.rectangle(m.array, (x, y), (x + w, y + h), (255, 0, 0, 0))

        self.__picam2.post_callback = draw_faces
