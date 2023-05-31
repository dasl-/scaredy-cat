#!/usr/bin/python3
import RPi.GPIO as GPIO
import time
import keyboard
import sys

class WatchCatMotor:

    DIRECTION_LEFT = False
    DIRECTION_RIGHT = True

    LEFT_POSITION = -110
    CENTER_POSITION = 0
    RIGHT_POSITION = 110
    FULL_SWEEP = 220

    SLEEP_TIME = 0.003 # .0015 seems like the fastest reliable speed

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

    def resetPosition(self):
        self.__position = WatchCatMotor.CENTER_POSITION

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
        while (True):
            if (self.__position == WatchCatMotor.LEFT_POSITION):
                # start moving right
                self.__direction = WatchCatMotor.DIRECTION_RIGHT

            elif (self.__position == WatchCatMotor.RIGHT_POSITION):
                # start moving left
                self.__direction = WatchCatMotor.DIRECTION_LEFT

            self.step()
    
    def step(self):
        for pin in range(0, len(self.__motor_pins)):
            GPIO.output( self.__motor_pins[pin], WatchCatMotor.STEP_SEQUENCE[self.__motor_step_counter][pin] )
        
        if self.__direction == WatchCatMotor.DIRECTION_LEFT:
            self.__position = self.__position - 1
            self.__motor_step_counter = (self.__motor_step_counter - 1) % 8
        elif self.__direction == WatchCatMotor.DIRECTION_RIGHT:
            self.__position = self.__position + 1
            self.__motor_step_counter = (self.__motor_step_counter + 1) % 8
        else:
            self.cleanup()
            exit( 1 )

        time.sleep( WatchCatMotor.SLEEP_TIME )

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
    print ("Please Center the Eye - 1:move left, 2:move right, 3:start loop")
    motor = WatchCatMotor()

    centering = True

    try:
        while (centering):
            x = input('')

            if x == '1':
                motor.step_left()
            elif x == '2':
                motor.step_right()
            elif x == '3':
                print  ("running...")
                motor.resetPosition()
                centering = False
                
        motor.run()

    except KeyboardInterrupt:
        motor.cleanup()
        exit( 1 )

    motor.cleanup()
    exit( 0 )

if __name__ == '__main__':
    sys.exit(main())