#!/usr/bin/python3
import RPi.GPIO as GPIO
import time
import keyboard
import sys

class WatchCatMotor:

    DIRECTION_LEFT = False
    DIRECTION_RIGHT = True

    CENTER_POSITION = 0
    LEFT_POSITION = -180    # maximum number of steps to go to the left
    RIGHT_POSITION = 130    # maximum number of steps to go to the right

    # time (s) between steps, lower = faster movement. .003 is standard speed
    STEP_LEFT_SLEEP_TIME = 0.001  
    STEP_RIGHT_SLEEP_TIME = 0.002

    # how long (s) to sit at the extremes
    EYE_LEFT_DWELL_TIME = .6
    EYE_RIGHT_DWELL_TIME = .5

    STEP_SEQUENCE = [[1,0,0,1],
                    [1,0,0,0],
                    [1,1,0,0],
                    [0,1,0,0],
                    [0,1,1,0],
                    [0,0,1,0],
                    [0,0,1,1],
                    [0,0,0,1]]

    def __init__(self, in1 = 17, in2 = 18, in3 = 22, in4 = 23):
        self.__position = WatchCatMotor.CENTER_POSITION
        self.__direction = WatchCatMotor.DIRECTION_RIGHT
        self.__motor_pins = [in1, in2, in3, in4]
        self.__motor_step_counter = 0

        self.setupGPIO()

    def calibratePosition(self):
        for i in range(WatchCatMotor.RIGHT_POSITION * 4):
            self.step()

        self.__position = WatchCatMotor.RIGHT_POSITION

    def setupGPIO(self):
        GPIO.setmode( GPIO.BCM )

        GPIO.setup( self.__motor_pins[0], GPIO.OUT )
        GPIO.setup( self.__motor_pins[1], GPIO.OUT )
        GPIO.setup( self.__motor_pins[2], GPIO.OUT )
        GPIO.setup( self.__motor_pins[3], GPIO.OUT )

        GPIO.output( self.__motor_pins[0], GPIO.LOW )
        GPIO.output( self.__motor_pins[1], GPIO.LOW )
        GPIO.output( self.__motor_pins[2], GPIO.LOW )
        GPIO.output( self.__motor_pins[3], GPIO.LOW )

    def cleanup(self):
        GPIO.output( self.__motor_pins[0], GPIO.LOW )
        GPIO.output( self.__motor_pins[1], GPIO.LOW )
        GPIO.output( self.__motor_pins[2], GPIO.LOW )
        GPIO.output( self.__motor_pins[3], GPIO.LOW )

        GPIO.cleanup()

    def run(self):
        self.calibratePosition();

        while (True):
            if (self.__position == WatchCatMotor.LEFT_POSITION):
                # start moving right
                self.__direction = WatchCatMotor.DIRECTION_RIGHT
                time.sleep(WatchCatMotor.EYE_LEFT_DWELL_TIME)

            elif (self.__position == WatchCatMotor.RIGHT_POSITION):
                # start moving left
                self.__direction = WatchCatMotor.DIRECTION_LEFT
                time.sleep(WatchCatMotor.EYE_RIGHT_DWELL_TIME)

            self.step()

    def step(self):
        for pin in range(0, len(self.__motor_pins)):
            GPIO.output( self.__motor_pins[pin], WatchCatMotor.STEP_SEQUENCE[self.__motor_step_counter][pin] )

        if self.__direction == WatchCatMotor.DIRECTION_LEFT:
            self.__position = self.__position - 1
            self.__motor_step_counter = (self.__motor_step_counter - 1) % 8
            time.sleep( WatchCatMotor.STEP_LEFT_SLEEP_TIME )
        elif self.__direction == WatchCatMotor.DIRECTION_RIGHT:
            self.__position = self.__position + 1
            self.__motor_step_counter = (self.__motor_step_counter + 1) % 8
            time.sleep( WatchCatMotor.STEP_RIGHT_SLEEP_TIME )
        else:
            self.cleanup()
            exit( 1 )


    def step_left(self):
        self.__direction = WatchCatMotor.DIRECTION_LEFT
        i = 0
        for i in range(10):
            self.step()

    def step_right(self):
        self.__direction = WatchCatMotor.DIRECTION_RIGHT
        i = 0
        for i in range(10):
            self.step()


def main():
    motor = WatchCatMotor()

    try:
        motor.run()
    except KeyboardInterrupt:
        motor.cleanup()
        exit( 1 )

    motor.cleanup()
    exit( 0 )

if __name__ == '__main__':
    sys.exit(main())