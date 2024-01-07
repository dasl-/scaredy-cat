import atexit
import pigpio
import RPi.GPIO as GPIO
import traceback
import time

from scaredycat.unixsockethelper import UnixSocketHelper
from scaredycat.logger import Logger

SERVO_PIN = 18 # Use this pin to tell the servo to hold or release the pendulum
MAGNET_PIN = 23 # Use this pin to tell the electromagnet to turn on or off

SERVO_PAUSE_POSITION = 1050 # 1030 seems like the minimum amount
SERVO_UNPAUSE_POSITION = 800 # 860 working, 890 is too much

class TickController:

    PAUSE_SIGNAL = 'pause'
    UNPAUSE_SIGNAL = 'unpause'
    UNIX_SOCKET_PATH = '/tmp/motor_unix_socket'

    def __init__(self):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting tick controller...")

        atexit.register(self.__cleanupGPIO)
        self.__pwm = self.__setupGpio()

        self.__acceptSocket()

        # Set initial state, including resetting position of servo and pulsing magnet.
        self.__unpause()

    def run(self):
        while (True):
            # timeout_s = None: block until there's a message
            self.__readAndRespondToControlMessage(timeout_s = None)

    # Returns boolean: true if we read a message within the timeout, false otherwise
    def __readAndRespondToControlMessage(self, timeout_s):
        signal = None
        if self.__unix_socket_helper.is_ready_to_read(timeout_s):
            try:
                signal = self.__unix_socket_helper.recv_msg()
                self.__logger.info(f'got control message: {signal}')
            except Exception as e:
                self.__logger.error(f'Caught exception: {traceback.format_exc()}')
                raise e
        else:
            return False

        if signal == self.UNPAUSE_SIGNAL:
            self.__unpause()
        elif signal == self.PAUSE_SIGNAL:
            self.__pause()
        else:
            raise Exception(f"unknown signal: {signal}")
        return True

    def __unpause(self):
        if self.__paused is False:
            return

        self.__paused = False

        # Move the servo to release the hold on the pendulum
        # self.__pwm.set_servo_pulsewidth(SERVO_PIN, SERVO_UNPAUSE_POSITION)

        # move slowly to the unpaused position (to reduce motor volume)
        nextPosition = SERVO_PAUSE_POSITION
        while (nextPosition > SERVO_UNPAUSE_POSITION):
            self.__pwm.set_servo_pulsewidth(SERVO_PIN, nextPosition)
            nextPosition = nextPosition - 10
            time.sleep(0.005)

        # Pulse the magnet on and off 5 times to get the pendulum swinging
        for i in range(5):
            GPIO.output(MAGNET_PIN, True) # turn magnet on
            self.__logger.info('magnet on')
            time.sleep(0.5)
            # timeout_s = 0.5: wait up to 0.5s for a message
            # if self.__readAndRespondToControlMessage(timeout_s = 0.5):
            #     self.__logger.info('magnet: got control message')
            #     GPIO.output(MAGNET_PIN, False) # turn magnet off
            #     break
            GPIO.output(MAGNET_PIN, False) # turn magnet off
            self.__logger.info('magnet off')
            time.sleep(0.5)
            # if self.__readAndRespondToControlMessage(timeout_s = 0.5):
            #     self.__logger.info('magnet: got control message')
            #     break

    def __pause(self):
        if (self.__paused):
            return

        self.__paused = True

        # Move the servo to hold the pendulum
        # self.__pwm.set_servo_pulsewidth(SERVO_PIN, SERVO_PAUSE_POSITION)

        # move slowly to the paused position (to reduce motor volume)
        nextPosition = SERVO_UNPAUSE_POSITION
        while (nextPosition < SERVO_PAUSE_POSITION):
            self.__pwm.set_servo_pulsewidth(SERVO_PIN, nextPosition)
            nextPosition = nextPosition + 10
            time.sleep(0.005)

    def __setupGpio(self):
        pwm = pigpio.pi()
        pwm.set_mode(SERVO_PIN, pigpio.OUTPUT)
        pwm.set_PWM_frequency(SERVO_PIN, 50)

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(MAGNET_PIN, GPIO.OUT)

        return pwm

    def __acceptSocket(self):
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

    # is this necessary?
    def __cleanupGPIO(self):
        GPIO.cleanup()
