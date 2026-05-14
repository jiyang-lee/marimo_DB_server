from machine import ADC, I2C, Pin, time_pulse_us
import dht
import gc
import network
import time

# Pins
I2C_SCL_GPIO = 5
I2C_SDA_GPIO = 4
HCSR04_TRIG_GPIO = 14
HCSR04_ECHO_GPIO = 12
DHT11_GPIO = 13
KY038_DO_GPIO = 16
WATER_POWER_GPIO = 14
WATER_ADC = ADC(0)

# Sensor config
BH1750_ADDR = 0x23
BH1750_CONT_HIGH_RES = 0x10
WATER_RAW_MIN = 10
WATER_RAW_MAX = 500
WATER_AVG_COUNT = 8
WATER_STABILIZE_SECONDS = 0.3
LCD_ADDR_CANDIDATES = (0x27, 0x3F)

LCD_CHR = 1
LCD_CMD = 0
LCD_BACKLIGHT = 0x08
LCD_ENABLE = 0x04
LCD_LINE_1 = 0x80
LCD_LINE_2 = 0xC0

# Runtime config
POLL_SECONDS = 3
WATER_READ_INTERVAL_MS = 60 * 60 * 1000
TEMP_HUMID_READ_INTERVAL_MS = 60 * 60 * 1000
DEVICE_ID = "wemos_sensor_node"

# Wi-Fi / API
WIFI_SSID = "U+NetE3CC"
WIFI_PASSWORD = "G7D99A@476"
REALTIME_INGEST_URL = "http://192.168.219.56:8000/sensor/realtime-ingest"
HOURLY_INGEST_URL = "http://192.168.219.56:8000/sensor/hourly-ingest"


def clamp(value, minimum, maximum):
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def water_percent(raw_value):
    if raw_value is None:
        return None
    pct = (raw_value - WATER_RAW_MIN) * 100 / (WATER_RAW_MAX - WATER_RAW_MIN)
    return int(clamp(pct, 0, 100))


def ensure_wifi_connected():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True

    print("Connecting Wi-Fi...")
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(20):
        if wlan.isconnected():
            print("Wi-Fi connected:", wlan.ifconfig()[0])
            return True
        time.sleep(1)
    print("Wi-Fi connection failed")
    return False


def init_i2c_and_bh1750():
    i2c = I2C(scl=Pin(I2C_SCL_GPIO), sda=Pin(I2C_SDA_GPIO), freq=100000)
    ok = False
    try:
        devices = i2c.scan()
        if BH1750_ADDR in devices:
            i2c.writeto(BH1750_ADDR, bytes([BH1750_CONT_HIGH_RES]))
            time.sleep_ms(180)
            ok = True
    except Exception as e:
        print("BH1750 init error:", e)
    return i2c, ok


def lcd_write_byte(i2c, addr, value):
    i2c.writeto(addr, bytes([value | LCD_BACKLIGHT]))


def lcd_toggle_enable(i2c, addr, value):
    time.sleep_us(500)
    lcd_write_byte(i2c, addr, value | LCD_ENABLE)
    time.sleep_us(500)
    lcd_write_byte(i2c, addr, value & ~LCD_ENABLE)
    time.sleep_us(500)


def lcd_send_byte(i2c, addr, value, mode):
    high = mode | (value & 0xF0)
    low = mode | ((value << 4) & 0xF0)
    lcd_write_byte(i2c, addr, high)
    lcd_toggle_enable(i2c, addr, high)
    lcd_write_byte(i2c, addr, low)
    lcd_toggle_enable(i2c, addr, low)


def lcd_command(i2c, addr, value):
    lcd_send_byte(i2c, addr, value, LCD_CMD)


def lcd_write_char(i2c, addr, value):
    lcd_send_byte(i2c, addr, value, LCD_CHR)


def init_lcd(i2c):
    try:
        devices = i2c.scan()
    except Exception as e:
        print("LCD scan error:", e)
        return None

    addr = None
    for candidate in LCD_ADDR_CANDIDATES:
        if candidate in devices:
            addr = candidate
            break
    if addr is None:
        return None

    time.sleep_ms(50)
    for value in (0x30, 0x30, 0x30, 0x20):
        lcd_write_byte(i2c, addr, value)
        lcd_toggle_enable(i2c, addr, value)
        time.sleep_ms(5)

    for cmd in (0x28, 0x0C, 0x06, 0x01):
        lcd_command(i2c, addr, cmd)
    time.sleep_ms(2)
    return addr


def lcd_print_line(i2c, addr, row, text):
    line = LCD_LINE_1 if row == 0 else LCD_LINE_2
    lcd_command(i2c, addr, line)
    text = text[:16]
    text = text + (" " * (16 - len(text)))
    for ch in text:
        lcd_write_char(i2c, addr, ord(ch))


def vfmt(value, digits=0):
    if value is None:
        return "-"
    if digits == 1:
        return "{:.1f}".format(value)
    return str(int(value))


def update_lcd(i2c, lcd_addr, temp_c, humidity, water_pct, distance_cm):
    if lcd_addr is None:
        return
    try:
        line1 = "T:{}C H:{}%".format(vfmt(temp_c), vfmt(humidity))
        line2 = "W:{}% D:{}cm".format(vfmt(water_pct), vfmt(distance_cm))
        lcd_print_line(i2c, lcd_addr, 0, line1)
        lcd_print_line(i2c, lcd_addr, 1, line2)
    except Exception as e:
        print("LCD write error:", e)


def read_dht11(sensor):
    try:
        sensor.measure()
        return sensor.temperature(), sensor.humidity()
    except Exception as e:
        print("DHT11 read error:", e)
        return None, None


def read_bh1750_lux(i2c, enabled):
    if not enabled:
        return None
    try:
        data = i2c.readfrom(BH1750_ADDR, 2)
        raw = (data[0] << 8) | data[1]
        return raw / 1.2
    except Exception as e:
        print("BH1750 read error:", e)
        return None


def read_hcsr04_cm(trigger, echo):
    try:
        trigger.off()
        time.sleep_us(2)
        trigger.on()
        time.sleep_us(10)
        trigger.off()
        duration = time_pulse_us(echo, 1, 30000)
        if duration < 0:
            return None
        return duration * 0.0343 / 2
    except Exception as e:
        print("HC-SR04 read error:", e)
        return None


def read_water_average(power_pin):
    power_pin.on()
    time.sleep(WATER_STABILIZE_SECONDS)
    values = []
    for _ in range(WATER_AVG_COUNT):
        values.append(WATER_ADC.read())
        time.sleep(0.02)
    power_pin.off()
    avg_raw = sum(values) // len(values)
    return avg_raw, water_percent(avg_raw)


def build_realtime_payload(lux, distance_cm, sound_value):
    if lux is None or distance_cm is None or sound_value is None:
        return None
    return {
        "device_id": DEVICE_ID,
        "light": float(lux),
        "distance": float(distance_cm),
        "sound": float(sound_value),
    }


def build_hourly_payload(temp_c, humidity, water_pct, water_raw=None):
    if temp_c is None or humidity is None or water_pct is None:
        return None
    payload = {
        "device_id": DEVICE_ID,
        "temperature": float(temp_c),
        "humidity": float(humidity),
        "water_level": float(water_pct),
    }
    if water_raw is not None:
        payload["water_raw"] = int(water_raw)
    return payload


def post_json(url, body, label):
    if body is None:
        print(label, "skipped (missing value)")
        return
    if not ensure_wifi_connected():
        print(label, "skipped (wifi disconnected)")
        return

    response = None
    try:
        gc.collect()
        import urequests

        response = urequests.post(url, json=body)
        print(label + ":", response.status_code)
    except Exception as e:
        print(label, "error:", e)
    finally:
        if response is not None:
            response.close()
        gc.collect()


def due(now_ms, last_ms, interval_ms):
    return last_ms is None or time.ticks_diff(now_ms, last_ms) >= interval_ms


def main():
    i2c, bh1750_enabled = init_i2c_and_bh1750()
    lcd_addr = init_lcd(i2c)
    print("BH1750 ready" if bh1750_enabled else "BH1750 not found")
    print("LCD ready" if lcd_addr is not None else "LCD not found")
    ensure_wifi_connected()

    dht11 = dht.DHT11(Pin(DHT11_GPIO))
    hcsr04_trig = Pin(HCSR04_TRIG_GPIO, Pin.OUT)
    hcsr04_echo = Pin(HCSR04_ECHO_GPIO, Pin.IN)
    sound_digital = Pin(KY038_DO_GPIO, Pin.IN)
    water_power = Pin(WATER_POWER_GPIO, Pin.OUT)
    water_power.off()

    last_temp_humidity_ms = None
    last_water_ms = None

    latest_temp_c = None
    latest_humidity = None
    latest_water_pct = None
    latest_distance_cm = 100.0

    while True:
        now_ms = time.ticks_ms()

        temp_updated = False
        water_updated = False

        if due(now_ms, last_temp_humidity_ms, TEMP_HUMID_READ_INTERVAL_MS):
            temp_c, humidity = read_dht11(dht11)
            if temp_c is not None and humidity is not None:
                latest_temp_c = temp_c
                latest_humidity = humidity
                last_temp_humidity_ms = now_ms
                temp_updated = True

        water_raw = None
        if due(now_ms, last_water_ms, WATER_READ_INTERVAL_MS):
            water_raw, water_pct = read_water_average(water_power)
            if water_pct is not None and water_raw is not None:
                latest_water_pct = water_pct
                last_water_ms = now_ms
                water_updated = True

        lux = read_bh1750_lux(i2c, bh1750_enabled)
        distance_cm = read_hcsr04_cm(hcsr04_trig, hcsr04_echo)
        if distance_cm is not None:
            latest_distance_cm = distance_cm
        sound_value = sound_digital.value()

        print(
            "T:", latest_temp_c,
            "H:", latest_humidity,
            "Lx:", lux,
            "W%:", latest_water_pct,
            "D:", distance_cm,
            "D(last):", latest_distance_cm,
            "S:", sound_value,
        )
        update_lcd(i2c, lcd_addr, latest_temp_c, latest_humidity, latest_water_pct, latest_distance_cm)

        realtime_payload = build_realtime_payload(lux, latest_distance_cm, sound_value)
        post_json(REALTIME_INGEST_URL, realtime_payload, "Realtime ingest")

        if temp_updated or water_updated:
            hourly_payload = build_hourly_payload(
                latest_temp_c,
                latest_humidity,
                latest_water_pct,
                water_raw,
            )
            post_json(HOURLY_INGEST_URL, hourly_payload, "Hourly ingest")

        gc.collect()
        time.sleep(POLL_SECONDS)


main()
