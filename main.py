import WIFI_CONFIG
import SHELLY_CONFIG
from network_manager import NetworkManager
import uasyncio
import urequests
import math
import time
from machine import Timer, Pin
from galactic import GalacticUnicorn
from picographics import PicoGraphics, DISPLAY_GALACTIC_UNICORN as DISPLAY
from phew import logging, ntp

# Constants for configuration
UPDATE_INTERVAL = 3  # Interval for updating the frame (in seconds)
DEFAULT_BRIGHTNESS = 0.5  # Default display brightness

min_brightness = 0.2
max_brightness = 0.7

min_sensor = 50  # Minimum sensor value for light mapping
max_sensor = 400  # Maximum sensor value for light mapping

TEXT_SIZE = 1  # Size of the text displayed on the screen

PEAK_SOLAR = 3000.0  # Peak solar power value
WORST_GRID = 1000.0  # Worst-case grid power value

GRID_SIDE = 0  # Side of the display for grid power visualization
SOLAR_SIDE = 1  # Side of the display for solar power visualization

HUE_OFFSET = -0.1  # Offset for hue in gradient background

# Color definitions for solar and grid visualization
SOLAR_HUE = 0.18
SOLAR_SATURATION = 1.0
SOLAR_VALUE = 1.0

POSITIVE_GRID_HUE = 0.05
NEGATIVE_GRID_HUE = 0.38
GRID_SATURATION = 1.0
GRID_VALUE = 1.0

solar_power = "0"
grid_power = "0"

# Set up the Pico W's onboard LED
pico_led = Pin('LED', Pin.OUT)

# Initialise Unicorn and constants
gu = GalacticUnicorn()
graphics = PicoGraphics(DISPLAY)

width = GalacticUnicorn.WIDTH
height = GalacticUnicorn.HEIGHT

# Set up some pens to use later
WHITE = graphics.create_pen(255, 255, 255)
BLACK = graphics.create_pen(0, 0, 0)

# Set the font for text rendering
graphics.set_font("bitmap8")
gu.set_brightness(DEFAULT_BRIGHTNESS)

def status_handler(mode, status, ip):
    """Handles WiFi status updates."""
    logging.info(mode, status, ip)
    logging.info('Connecting to wifi...')
    if status is not None:
        if status:
            logging.info('Wifi connection successful!')
            ntp.fetch()  # Fetch network time if WiFi is connected
        else:
            logging.info('Wifi connection failed!')

async def connect_to_wifi():
    """Attempts to connect to WiFi using the network manager."""
    try:
        await network_manager.client(WIFI_CONFIG.SSID, WIFI_CONFIG.PSK)
        logging.info("WiFi connected successfully.")
    except Exception as e:
        logging.error(f"WiFi connection failed: {e}")

def get_data(check_url, max_retries=3):
    """Fetches data from the given URL, retrying if the request fails."""
    retries = 0
    while retries < max_retries:
        try:
            # Make a request to the given URL
            r = urequests.get(check_url, auth=(SHELLY_CONFIG.USERNAME, SHELLY_CONFIG.PASSWORD), timeout=10)
            j = r.json()
            r.close()

            # Flash the onboard LED after getting data
            pico_led.value(True)
            time.sleep(0.2)
            pico_led.value(False)

            return j['power']

        except Exception as e:
            logging.error(f"An error occurred: {e}")
            logging.error("Attempting to reconnect Wi-Fi...")

            try:
                # Attempt to reconnect to WiFi
                uasyncio.get_event_loop().run_until_complete(connect_to_wifi())
                retries += 1
                continue  # Retry the data fetch after reconnection

            except Exception as e:
                logging.error(f"Reconnection failed: {e}")
                retries += 1  # Increment retries if reconnection fails as well

    logging.error(f"Failed to retrieve data after {max_retries} attempts. Resetting device...")
    machine.reset()  # Reset the device if max retries exceeded
    return 0

def outline_text(display_text, x, y, text_scale):
    """Draws outlined text to improve visibility on the display."""
    # Draw the outline in black
    graphics.set_pen(BLACK)
    graphics.text(display_text, x - 1, y - 1, -1, text_scale)
    graphics.text(display_text, x, y - 1, -1, text_scale)
    graphics.text(display_text, x + 1, y - 1, -1, text_scale)
    graphics.text(display_text, x - 1, y, -1, text_scale)
    graphics.text(display_text, x + 1, y, -1, text_scale)
    graphics.text(display_text, x - 1, y + 1, -1, text_scale)
    graphics.text(display_text, x, y + 1, -1, text_scale)
    graphics.text(display_text, x + 1, y + 1, -1, text_scale)

    # Draw the main text in white
    graphics.set_pen(WHITE)
    graphics.text(display_text, x, y, -1, text_scale)

def calculate_gradient_values(start, end, steps):
    """Helper function to calculate gradient values between start and end over a number of steps."""
    return [min(max(start + (end - start) * (i / steps), 0.0), 1.0) for i in range(steps)]

def gradient_background(start_hue, start_sat, start_val, end_hue, end_sat, end_val, side):
    """Draws a gradient background on one side of the display."""
    half_width = width // 2  # Calculate half the width of the display
    q_width = width // 4  # Calculate a quarter of the width
    side_offset = (half_width + 1) * side  # Determine the starting point based on the side

    # Calculate gradient values for hue, saturation, and value
    hue_values = calculate_gradient_values(start_hue, end_hue, q_width)
    sat_values = calculate_gradient_values(start_sat, end_sat, q_width)
    val_values = calculate_gradient_values(start_val, end_val, q_width)

    # Draw the gradient on the specified side of the display
    for x in range(q_width):
        hue = hue_values[x]
        sat = sat_values[x]
        val = val_values[x]

        graphics.set_pen(graphics.create_pen_hsv(hue, sat, val))

        for y in range(height):
            graphics.pixel(side_offset + x, y)
            graphics.pixel(((half_width + side_offset) - x) - 1, y)

    # Draw a dividing line in black at the middle of the display
    graphics.set_pen(BLACK)
    for y in range(height):
        graphics.pixel(half_width, y)

def scale_value(val, max_val):
    """Scales the input value based on a blended approach of linear and square root scaling."""
    linear_percent = val / max_val
    # Blended approach: average of linear and square root
    return 0.5 * (linear_percent + math.sqrt(linear_percent))

def map_light_to_brightness(sensor_value):
    """Maps the sensor value to a brightness value within the specified range."""
    # Clamp the value between min and max sensor values
    sensor_value = max(min(sensor_value, max_sensor), min_sensor)

    # Normalize sensor value between 0 and 1
    normalized_value = (sensor_value - min_sensor) / (max_sensor - min_sensor)

    # Scale to the brightness range
    return normalized_value * (max_brightness - min_brightness) + min_brightness

try:
    # Initialize the network manager and attempt to connect to WiFi
    network_manager = NetworkManager(WIFI_CONFIG.COUNTRY, status_handler=status_handler)
    uasyncio.get_event_loop().run_until_complete(connect_to_wifi())
except Exception as e:
    logging.error(f'Wifi connection failed! {e}')

def main():
    previous_brightness = 0

    # Initialize counters for inner and outer loops
    brightness_update_interval = 0.1  # Brightness refresh rate (0.1 seconds)
    frame_interval = UPDATE_INTERVAL  # Frame refresh rate (3 seconds)
    brightness_refreshes = int(frame_interval / brightness_update_interval)  # Number of brightness updates per frame

    while True:
        # Get all the data (fetch once per frame refresh)
        solar = get_data(SHELLY_CONFIG.URL_SOLAR)
        grid = get_data(SHELLY_CONFIG.URL_GRID)
        solar_power = f"{round(solar)}"
        grid_power = f"{round(grid)}"
        
        # Determine the hue, saturation, and value based on grid power
        if grid < 0:
            hue = NEGATIVE_GRID_HUE
            sat = GRID_SATURATION
            val = GRID_VALUE * scale_value(abs(grid), PEAK_SOLAR)
        else:
            hue = POSITIVE_GRID_HUE
            sat = GRID_SATURATION
            val = GRID_VALUE * scale_value(grid, WORST_GRID)
            if val > 1.0:
                val = 1.0

        # Draw the gradient background for the grid side
        gradient_background(hue, sat, val, hue + HUE_OFFSET, sat, val, GRID_SIDE)

        # Draw solar background
        percent_to_peak = solar / PEAK_SOLAR
        if percent_to_peak > 1.0:
            percent_to_peak = 1.0

        hue = SOLAR_HUE
        sat = SOLAR_SATURATION
        val = SOLAR_VALUE * scale_value(solar, PEAK_SOLAR)
        if val > 1.0:
            val = 1.0

        # Draw the gradient background for the solar side
        gradient_background(hue, sat, val, hue + HUE_OFFSET, sat, val, SOLAR_SIDE)

        # Write grid and solar power text to the display
        w = graphics.measure_text(grid_power, TEXT_SIZE)
        x = int(width / 4 - w / 2 + 1)
        y = 2
        outline_text(grid_power, x, y, TEXT_SIZE)

        w = graphics.measure_text(solar_power, TEXT_SIZE)
        x = int(((width / 4) * 3) - w / 2 + 1)
        y = 2
        outline_text(solar_power, x, y, TEXT_SIZE)
        
        # Update the brightness multiple times during the frame interval
        for _ in range(brightness_refreshes):
            # Read the light sensor
            sensor_value = gu.light()  # Assuming `gu.light()` reads the ambient light sensor
            target_brightness = map_light_to_brightness(sensor_value)
            
            # Apply smoothing to brightness adjustment
            smoothing_factor = 0.1
            previous_brightness = (smoothing_factor * target_brightness) + ((1 - smoothing_factor) * previous_brightness)
            gu.set_brightness(previous_brightness)  # Update brightness
            gu.update(graphics)  # Update the display with new brightness

            time.sleep(brightness_update_interval)  # Wait before updating brightness again
            
        # Log the solar and grid power, sensor value, and brightness value
        logging.info(f'Solar power: {solar_power}')
        logging.info(f'Grid power: {grid_power}')
        logging.info(f'Light sensor value: {sensor_value}')
        logging.info(f'Brightness value: {previous_brightness}')

        time.sleep(brightness_update_interval)

# Run the main function
main()