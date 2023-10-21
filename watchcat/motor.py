#!/usr/bin/python3
import RPi.GPIO as GPIO
import atexit
import time
import traceback

from watchcat.unixsockethelper import UnixSocketHelper
from watchcat.logger import Logger

class Motor:

    UNIX_SOCKET_PATH = '/tmp/motor_unix_socket'

    DIRECTION_LEFT = False
    DIRECTION_RIGHT = True

    CENTER_POSITION = 0
    LEFT_POSITION = -180    # maximum number of steps to go to the left
    RIGHT_POSITION = 130    # maximum number of steps to go to the right

    # time (s) between steps, lower = faster movement. .003 is standard speed
    STEP_LEFT_SLEEP_TIME = 0.002
    STEP_RIGHT_SLEEP_TIME = 0.003

    # how long (s) to sit at the extremes
    EYE_LEFT_DWELL_TIME = .1
    EYE_RIGHT_DWELL_TIME = .2

    STEP_SEQUENCE = [[1, 0, 0, 1],
                     [1, 0, 0, 0],
                     [1, 1, 0, 0],
                     [0, 1, 0, 0],
                     [0, 1, 1, 0],
                     [0, 0, 1, 0],
                     [0, 0, 1, 1],
                     [0, 0, 0, 1]]

    PAUSE_SIGNAL = 'pause'
    RUN_SIGNAL = 'run'

    def __init__(self, in1 = 17, in2 = 18, in3 = 22, in4 = 23):
        self.__logger = Logger().set_namespace(self.__class__.__name__)
        self.__logger.info("Starting Motor...")
        self.__paused = False
        self.__position = Motor.CENTER_POSITION
        self.__direction = Motor.DIRECTION_RIGHT
        self.__motor_pins = [in1, in2, in3, in4]
        self.__motor_step_counter = 0

        atexit.register(self.__cleanupGPIO)
        self.__setupGPIO()

    def calibrate_position(self):
        for i in range(Motor.RIGHT_POSITION * 4):
            self.__step()

        self.__position = Motor.RIGHT_POSITION

    def __setupGPIO(self):
        GPIO.setmode(GPIO.BCM)

        GPIO.setup(self.__motor_pins[0], GPIO.OUT)
        GPIO.setup(self.__motor_pins[1], GPIO.OUT)
        GPIO.setup(self.__motor_pins[2], GPIO.OUT)
        GPIO.setup(self.__motor_pins[3], GPIO.OUT)

        GPIO.output(self.__motor_pins[0], GPIO.LOW)
        GPIO.output(self.__motor_pins[1], GPIO.LOW)
        GPIO.output(self.__motor_pins[2], GPIO.LOW)
        GPIO.output(self.__motor_pins[3], GPIO.LOW)

    def __cleanupGPIO(self):
        GPIO.output(self.__motor_pins[0], GPIO.LOW)
        GPIO.output(self.__motor_pins[1], GPIO.LOW)
        GPIO.output(self.__motor_pins[2], GPIO.LOW)
        GPIO.output(self.__motor_pins[3], GPIO.LOW)

        GPIO.cleanup()

    def pause(self):
        self.__paused = True

    def unpause(self):
        self.__paused = False

    def run(self):
        self.calibrate_position()
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
        signal = self.RUN_SIGNAL
        while (True):
            if (self.__position == Motor.LEFT_POSITION):
                # start moving right
                self.__direction = Motor.DIRECTION_RIGHT
                time.sleep(Motor.EYE_LEFT_DWELL_TIME)

            elif (self.__position == Motor.RIGHT_POSITION):
                # start moving left
                self.__direction = Motor.DIRECTION_LEFT
                time.sleep(Motor.EYE_RIGHT_DWELL_TIME)

            if self.__unix_socket_helper.is_ready_to_read():
                try:
                    signal = self.__unix_socket_helper.recv_msg()
                except Exception as e:
                    self.__logger.error(f'Caught exception: {traceback.format_exc()}')
                    raise e

            if signal == self.RUN_SIGNAL:
                self.unpause()
            elif signal == self.PAUSE_SIGNAL:
                self.pause()
            else:
                raise Exception(f"unknown signal: {signal}")

            if (not self.__paused):
                self.__step()

    def __step(self):
        for pin in range(0, len(self.__motor_pins)):
            GPIO.output(self.__motor_pins[pin], Motor.STEP_SEQUENCE[self.__motor_step_counter][pin])

        if self.__direction == Motor.DIRECTION_LEFT:
            self.__position = self.__position - 1
            self.__motor_step_counter = (self.__motor_step_counter - 1) % 8
            time.sleep(Motor.STEP_LEFT_SLEEP_TIME)
        elif self.__direction == Motor.DIRECTION_RIGHT:
            self.__position = self.__position + 1
            self.__motor_step_counter = (self.__motor_step_counter + 1) % 8
            time.sleep(Motor.STEP_RIGHT_SLEEP_TIME)
