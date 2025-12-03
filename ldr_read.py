# Import libraries
import time
import RPi.GPIO as GPIO

LDR_in = 23
LDR_out = 24
LEDs = 4

# Charge cap
GPIO.output(LDR_in, GPIO.HIGH)

time.sleep(2)
GPIO.output(LDR_in, GPIO.LOW)

# Calculate the start time
start = time.time()

if(GPIO.input(LDR_out) == False){
    # Get discharge time
    end = time.time()
    length = end - start

    #Turn on LEDs if discharge time > 0.5s
    if(length > 0.5){
        GPIO.output(LEDs, GPIO.HIGH)
    }
    else{
        GPIO.output(LEDs, GPIO.LOW)
    }

}

