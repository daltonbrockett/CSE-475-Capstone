# Import libraries
import time
import RPi.GPIO as GPIO

LDR_in = 16
LDR_out = 18

LEDs = 7

GPIO.setwarnings(False)
# Charge cap
GPIO.setmode(GPIO.BOARD)
GPIO.setup(LDR_in, GPIO.OUT)
GPIO.setup(LDR_out, GPIO.IN)
GPIO.setup(LEDs, GPIO.OUT)

GPIO.output(LDR_in, GPIO.HIGH)
GPIO.output(LEDs, GPIO.HIGH)

time.sleep(2)
GPIO.output(LDR_in, GPIO.LOW)

# Calculate the start time
start = time.time()

while(True):
  if(GPIO.input(LDR_out) == False):
                 # Get discharge time
    end = time.time()
    length = end - start
    print(length)

    #Turn on LEDs if discharge time > 0.5s
    if(length > 1):
        GPIO.output(LEDs, GPIO.HIGH)
    else:
        GPIO.output(LEDs, GPIO.LOW)

    GPIO.output(LDR_in, GPIO.HIGH)
    time.sleep(length)
    GPIO.output(LDR_in, GPIO.LOW)
    start = time.time()

