import atexit
import pigpio
import RPi.GPIO as GPIO
import traceback

from watchcat.unixsockethelper import UnixSocketHelper
from watchcat.logger import Logger

SERVO_PIN = 17 # Use this pin to tell the servo to hold or release the pendulum
MAGNET_PIN = 27 # Use this pin to tell the electromagnet to turn on or off

SERVO_PAUSE_POSITION = 1000
SERVO_UNPAUSE_POSITION = 500

class TickController:

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting tick controller...")

        atexit.register(self.__cleanupGPIO)
        self.__pwm = self.__setupGPIO()

        # Reset position in case it was last stopped in paused state
        self.__unpause()
        self.__paused = False

    def run(self):
        self.__unix_socket_helper = UnixSocketHelper()
        socket = UnixSocketHelper().create_server_unix_socket(self.UNIX_SOCKET_PATH)
        self.__unix_socket_helper.set_server_socket(socket)

        self.__logger.info('Waiting to accept socket...')
        try:
            self.__unix_socket_helper.accept()
        except Exception as e:
            self.__logger.error(f'Caught exception: {traceback.format_exc()}')
            raise e
        self.__logger.info('Socket accepted!')
        while (True):
            # timeout_s = None: block until there's a message
            self.__readAndRespondToControlMessage(timeout_s = None)

    # Returns boolean: true if we read a message within the timeout, false otherwise
    def __readAndRespondToControlMessage(self, timeout_s):
        signal = self.RUN_SIGNAL
        if self.__unix_socket_helper.is_ready_to_read(timeout_s):
            try:
                signal = self.__unix_socket_helper.recv_msg()
            except Exception as e:
                self.__logger.error(f'Caught exception: {traceback.format_exc()}')
                raise e
        else:
            return False

        if signal == self.RUN_SIGNAL:
            self.__unpause()
        elif signal == self.PAUSE_SIGNAL:
            self.__pause()
        else:
            raise Exception(f"unknown signal: {signal}")
        return True

    def __unpause(self):
        self.__paused = False

        # Move the servo to release the hold on the pendulum
        self.__pwm.set_servo_pulsewidth(SERVO_PIN, SERVO_UNPAUSE_POSITION)

        # Pulse the magnet on and off 5 times to get the pendulum swinging
        for i in range(5):
            GPIO.output(MAGNET_PIN, True) # turn magnet on
            # timeout_s = 0.5: wait up to 0.5s for a message
            if self.__readAndRespondToControlMessage(timeout_s = 0.5):
                GPIO.output(MAGNET_PIN, False) # turn magnet off
                break
            GPIO.output(MAGNET_PIN, False) # turn magnet off
            if self.__readAndRespondToControlMessage(timeout_s = 0.5):
                break

    def __pause(self):
        self.__paused = True

        # Move the servo to hold the pendulum
        self.__pwm.set_servo_pulsewidth(SERVO_PIN, SERVO_PAUSE_POSITION)

    def __setupGpio(self):
        pwm = pigpio.pi()
        pwm.set_mode(SERVO_PIN, pigpio.OUTPUT)
        pwm.set_PWM_frequency(SERVO_PIN, 50)

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(MAGNET_PIN, GPIO.OUT)

        return pwm

    # is this necessary?
    def __cleanupGPIO(self):
        GPIO.cleanup()
