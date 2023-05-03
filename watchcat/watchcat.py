import face_recognition
import picamera2

from watchcat.logger import Logger

class WatchCat:

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
            main = {"size": (width, height)}

        display = None # controls which streams will be shown in the preview
        if show_preview:
            self.__picam2.start_preview(picamera2.Preview.QT)
            display = 'main'

        config = self.__picam2.create_still_configuration(main=main, display=display)

        self.__picam2.configure(config)
        self.__picam2.start()

        self.__logger.info("Finished starting WatchCat.")

    def run(self):
        while True:
            self.__logger.info("Capturing image...")
            # Grab a single frame of video from the RPi camera as a numpy array
            output = self.__picam2.capture_array()
            self.__logger.info(f"Done capturing image. Output shape: {output.shape}")

            # Find all the faces and face encodings in the current frame of video
            face_locations = face_recognition.face_locations(output)
            self.__logger.info(f"Found {len(face_locations)} faces in image.")
