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
    __NUM_CONSECUTIVE_EMPTY_FRAMES_TO_CONFIRM_EMPTY = 5

    # Set parameters for filtering which faces are allowed. INIT_* values apply to
    # the first face detected in a sequence of images and are generally more restrictive.
    # REPEAT_* values apply to subsequent images and are generally more permissive. The
    # intention is to avoid flapping -- once a face is detected, it should stay detected
    # so long as it stays in mostly the same position.

    # Minimum width and height of the detected face. When changing the width / height of the
    # captured image, it probably makes sense to adjust these proportionally -- an image
    # at twice the resolution will have the same face twice as large, all else being equal.
    # INIT > REPEAT
    __INIT_MIN_W = 24
    __INIT_MIN_H = 30
    __REPEAT_MIN_W = 18
    __REPEAT_MIN_H = 22

    # float in range [0, 1]: how confident the face detection is in a given face
    # INIT > REPEAT
    __INIT_MIN_SCORE = 0.9
    __REPEAT_MIN_SCORE = 0.4

    # float in range [0, 1]: determines the range of acceptable values for
    # the face's Gaze Percent. For example, a GAZE_RANGE of 0.50 indicates that a Gaze
    # Percent between 0.25 - 0.75 would be allowed.
    # INIT < REPEAT
    __INIT_GAZE_RANGE = 0.20
    __REPEAT_GAZE_RANGE = 0.28

    # width, height: if both width and height are set, we will set the
    #   dimensions of the captured camera image to these dimensions. The
    #   units are pixels. Using smaller dimensions will speed up face
    #   detection (the camera's native resolution is 4608x2592).
    #
    # mid_col_pct: Middle column percentage. The portion of the captured image
    #   to capture for face detection. Should be a float in (0,1]
    #
    # horizontal_offset_pct: If the camera was not perfectly aligned when mounted, we
    #   can compensate with this parameter. Should be a float in [-1,1]. Negative
    #   values shift the middle column left. Positive values shift it right. This
    #   parameter is a percentage of the width. For example, if `width = 300` and
    #   `horizontal_offset_pct = 0.1`, we will shift the middle column right 30
    #   pixels.
    #
    # Explanation of how width and mid_col_pct interact:
    # If we set mid_col_pct to 1/3, then the middle third of the image will be used.
    # For example, if `width = 300`, we will use the middle 100 pixels of the captured
    # image. If you think of the image as divided into 3 columns, we will be using the
    # middle column.
    #
    # show_preview: if True, we will send a live feed of the captured
    #   images via SSH X11 forwarding.
    def __init__(self, width=None, height=None, mid_col_pct=1 / 3, horizontal_offset_pct = 0, show_preview=False):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting ScaredyCat...")

        self.__picam2 = picamera2.Picamera2()
        self.__num_consecutive_face_frames = 0
        self.__num_consecutive_empty_frames = 0
        self.__confirmed_face_locations = []
        self.__unconfirmed_face_locations = []
        self.__crop_x0 = None
        self.__crop_x1 = None

        self.__unix_socket_helper = UnixSocketHelper()
        self.__unix_socket_helper.connect(TickController.UNIX_SOCKET_PATH)

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

        self.__cam_img_w, self.__cam_img_h = self.__picam2.camera_configuration()['main']['size']
        self.__logger.info(f"Using cam_img_w x cam_img_h: {self.__cam_img_w} x {self.__cam_img_h}")
        self.__setup_crop(mid_col_pct, horizontal_offset_pct)

        # See information about autofocus / focus bug that could resurface:
        # https://github.com/dasl-/scaredy-cat/blob/main/docs/issues_weve_seen_before.adoc#blurry-images-autofocus--focus-problems
        self.__picam2.set_controls({
            "AfMetering": libcamera.controls.AfMeteringEnum.Auto,
            "AfMode": libcamera.controls.AfModeEnum.Continuous,
            "AfRange": libcamera.controls.AfRangeEnum.Full,
            "AfSpeed": libcamera.controls.AfSpeedEnum.Normal,
        })

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

        # See:
        # https://docs.opencv.org/4.x/d0/dd4/tutorial_dnn_face.html
        # https://docs.opencv.org/4.x/df/d20/classcv_1_1FaceDetectorYN.html#a42293cf2d64f8b69a707ab70d11925b3
        # https://github.com/opencv/opencv_zoo/blob/80f7c6aa030a87b3f9e8ab7d84f62f13d308c10f/models/face_detection_yunet/yunet.py#L15
        face_detector = cv2.FaceDetectorYN.create(
            model = os.path.abspath(os.path.dirname(__file__) + '/../data/face_detection_yunet_2023mar.onnx'),
            config="", input_size = (self.__crop_x1 - self.__crop_x0, self.__cam_img_h),
            score_threshold = 0,
            top_k = 1 # keep only the best face detection candidate
        )
        while True:
            loop_start = time.time()
            # Grab a single frame of video from the RPi camera as a numpy array
            uncropped_output = self.__picam2.capture_array()
            img_capture_elapsed_s = round(time.time() - loop_start, 3)

            # Crop the image with numpy. See a performance comparison of different cropping methods:
            # https://gist.github.com/dasl-/cda68e8fef981edf9727c5995129b864
            output = uncropped_output[:, self.__crop_x0:self.__crop_x1, :]

            # Find all the faces and face encodings in the current frame of video
            face_detect_start = time.time()
            ignore, face_locations = face_detector.detect(output)
            if face_locations is None:
                face_locations = []
            face_detect_elapsed_s = round(time.time() - face_detect_start, 3)
            if len(face_locations) > 0:
                face_locations = self.__filterFacesByScore(face_locations)
            if len(face_locations) > 0:
                face_locations = self.__filterFacesByDimensions(face_locations)
            if len(face_locations) > 0:
                face_locations = self.__filterFacesByGaze(face_locations)

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

            self.__logger.debug(f"Found {len(face_locations)} faces in image. Loop took " +
                f"{round(time.time() - loop_start, 3)} s. Image capture took {img_capture_elapsed_s} s. " +
                f"Face detect took {face_detect_elapsed_s} s. Image dimensions: {output.shape}")

    # Only keep faces with sufficiently high face detection score. Low scores might be false positives.
    def __filterFacesByScore(self, face_locations):
        if len(self.__confirmed_face_locations) <= 0: # initial detection
            min_score = self.__INIT_MIN_SCORE
            threshold_text = f"initial threshold of {self.__INIT_MIN_SCORE}"
        else: # repeat detection
            min_score = self.__REPEAT_MIN_SCORE
            threshold_text = f"repeat threshold of {self.__REPEAT_MIN_SCORE}"

        face_indices_above_threshold = []
        face_indices_below_threshold = []
        for i in range(len(face_locations)):
            score = face_locations[i][14]
            if score >= min_score:
                face_indices_above_threshold.append(i)
            else:
                face_indices_below_threshold.append(i)

        if face_indices_above_threshold:
            scores = []
            for i in face_indices_above_threshold:
                scores.append(face_locations[i][14])
            self.__logger.debug(f"faces scores above the {threshold_text}: {scores}")

        if face_indices_below_threshold:
            scores = []
            for i in face_indices_below_threshold:
                scores.append(face_locations[i][14])
            self.__logger.debug(f"faces scores below the {threshold_text}: {scores}")

        # return faces_locations above the threshold: https://stackoverflow.com/a/7139454/22828008
        return face_locations[face_indices_above_threshold]

    # Only keep faces that are sufficiently large. Small faces might be false positives.
    def __filterFacesByDimensions(self, face_locations):
        if len(self.__confirmed_face_locations) <= 0: # initial detection
            min_w = self.__INIT_MIN_W
            min_h = self.__INIT_MIN_H
            threshold_text = f"initial threshold of {min_w}x{min_h}"
        else: # repeat detection
            min_w = self.__REPEAT_MIN_W
            min_h = self.__REPEAT_MIN_H
            threshold_text = f"repeat threshold of {min_w}x{min_h}"

        face_dimensions_above_threshold = []
        face_dimensions_below_threshold = []
        face_indices_above_threshold = []
        for i in range(len(face_locations)):
            (x, y, w, h) = face_locations[i][:4]
            x = x + self.__crop_x0
            if w >= min_w and h >= min_h:
                face_dimensions_above_threshold.append((int(w), int(h)))
                face_indices_above_threshold.append(i)
            else:
                face_dimensions_below_threshold.append((int(w), int(h)))

        if face_dimensions_above_threshold:
            self.__logger.debug(f"face dimensions above the {threshold_text}: {face_dimensions_above_threshold}")
        if face_dimensions_below_threshold:
            self.__logger.debug(f"face dimensions below the {threshold_text}: {face_dimensions_below_threshold}")

        # return faces_locations above the threshold: https://stackoverflow.com/a/7139454/22828008
        return face_locations[face_indices_above_threshold]

    # Only keep faces that are looking straight at the camera in terms of horizontal viewing angle (with some tolerance).
    # A face's "Gaze Percent" is in the range [0, 1]. A face with a "Gaze Percent" of 0.5 is looking directly at the
    # camera. A Gaze Percent < 0.5 means the face is looking to the left. And > 0.5 means the face is looking to the
    # right.
    def __filterFacesByGaze(self, face_locations):
        if len(self.__confirmed_face_locations) <= 0: # initial detection
            mid_col_pct = 0.20
            range_text = f"initial range of"
        else: # repeat detection
            mid_col_pct = 0.28
            range_text = f"repeat range of"

        min_gaze_pct = (1 - mid_col_pct) / 2
        max_gaze_pct = round(min_gaze_pct + mid_col_pct, 2)
        min_gaze_pct = round(min_gaze_pct, 2)

        gaze_pcts_within_bounds = []
        gaze_pcts_out_of_bounds = []
        face_indices_within_bounds = []
        for i in range(len(face_locations)):
            face = face_locations[i]
            face_x = face[0]
            face_w = face[2]

            right_eye_x = face[4] - face_x
            left_eye_x = face[6] - face_x
            nose_x = face[8] - face_x
            right_mouth_x = face[10] - face_x
            left_mouth_x = face[12] - face_x

            # This should be a float in [0, 1]
            gaze_pct = round(1 - ((right_eye_x + left_eye_x + nose_x + right_mouth_x + left_mouth_x) / 5 / face_w), 2)

            if min_gaze_pct <= gaze_pct and gaze_pct <= max_gaze_pct:
                gaze_pcts_within_bounds.append(gaze_pct)
                face_indices_within_bounds.append(i)
            else:
                gaze_pcts_out_of_bounds.append(gaze_pct)

        if gaze_pcts_within_bounds:
            self.__logger.debug(f"face gaze % within {range_text} [{min_gaze_pct} - {max_gaze_pct}]: {gaze_pcts_within_bounds}")
        if gaze_pcts_out_of_bounds:
            self.__logger.debug(f"face gaze % outside of {range_text} [{min_gaze_pct} - {max_gaze_pct}]: {gaze_pcts_out_of_bounds}")

        # return faces_locations above the threshold: https://stackoverflow.com/a/7139454/22828008
        return face_locations[face_indices_within_bounds]

    def __setup_crop(self, mid_col_pct, horizontal_offset_pct):
        cropped_img_w = self.__cam_img_w * mid_col_pct
        horizontal_offset = -horizontal_offset_pct * self.__cam_img_w
        self.__crop_x0 = (self.__cam_img_w - cropped_img_w) / 2
        self.__crop_x1 = int(round(self.__crop_x0 + cropped_img_w + horizontal_offset))
        self.__crop_x0 = int(round(self.__crop_x0 + horizontal_offset))
        self.__logger.info(f"horizontal_offset: {horizontal_offset}, crop_x0: {self.__crop_x0}, crop_x1: {self.__crop_x1}")

    def __setup_camera_preview(self, stream_img_w, stream_img_h):
        self.__picam2.start_preview(picamera2.Preview.QT, transform=libcamera.Transform(hflip=1))

        thickness = 2

        def draw_face(face_array, is_confirmed, img):
            face_x = int(face_array[0] + self.__crop_x0)
            face_y = int(face_array[1])
            face_w = int(face_array[2])
            face_h = int(face_array[3])

            right_eye_x = int(face_array[4] + self.__crop_x0)
            right_eye_y = int(face_array[5])
            left_eye_x = int(face_array[6] + self.__crop_x0)
            left_eye_y = int(face_array[7])

            nose_x = int(face_array[8] + self.__crop_x0)
            nose_y = int(face_array[9])

            right_mouth_x = int(face_array[10] + self.__crop_x0)
            right_mouth_y = int(face_array[11])
            left_mouth_x = int(face_array[12] + self.__crop_x0)
            left_mouth_y = int(face_array[13])

            # Draw face bounding box: green if confirmed, red if unconfirmed
            if is_confirmed:
                face_bounding_box_color = (0, 255, 0, 0)
            else:
                face_bounding_box_color = (255, 0, 0, 0)
            cv2.rectangle(img.array, (face_x, face_y), (face_x + face_w, face_y + face_h), face_bounding_box_color)

            # Right eye: red
            cv2.circle(img.array, (right_eye_x, right_eye_y), 2, (255, 0, 0), thickness)

            # Left eye: blue
            cv2.circle(img.array, (left_eye_x, left_eye_y), 2, (0, 0, 255), thickness)

            # Nose: red
            cv2.circle(img.array, (nose_x, nose_y), 2, (255, 0, 0), thickness)

            # Right corner of mouth: magenta
            cv2.circle(img.array, (right_mouth_x, right_mouth_y), 2, (255, 0, 255), thickness)

            # Left corner of mouth: cyan
            cv2.circle(img.array, (left_mouth_x, left_mouth_y), 2, (0, 255, 255), thickness)

        def draw_faces(request):
            with picamera2.MappedArray(request, "main") as m:
                # Place black bars on the sides of the image where we cropped them out
                cv2.rectangle(img=m.array, pt1=(0, 0), pt2=(self.__crop_x0, stream_img_h), color=(0, 0, 0, 0), thickness=-1)
                cv2.rectangle(img=m.array, pt1=(self.__crop_x1, 0), pt2=(stream_img_w, stream_img_h), color=(0, 0, 0, 0), thickness=-1)

                for f in self.__confirmed_face_locations:
                    draw_face(f, True, m)

                for f in self.__unconfirmed_face_locations:
                    draw_face(f, False, m)

        self.__picam2.post_callback = draw_faces
