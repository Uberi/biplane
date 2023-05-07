Biplane
=======

Biplane is an HTTP server library for Python/CircuitPython.

Compared to common alternatives such as [Ampule](https://github.com/deckerego/ampule/), [circuitpython-native-wsgiserver](https://github.com/Neradoc/circuitpython-native-wsgiserver/), and [Adafruit_CircuitPython_HTTPServer](https://github.com/adafruit/Adafruit_CircuitPython_HTTPServer/), it has several unique features:

* **Non-blocking concurrent I/O**: can process multiple requests at the same time, even when `async`/`await`/`asyncio` isn't available!
    * While circuitpython-native-wsgiserver does non-blocking I/O as well, it performs certain operations in a blocking loop, making soft-realtime use difficult (e.g. displaying animations, driving motors).
    * To make this work without `asyncio`, we expose the entire server as a generator, where each step of the generator is O(1).
* **More performant**: 10ms per request on a 160MHz ESP32C3, thanks to buffered reads/writes and avoiding common issues such as bytes concatenation.
    * Comparable to blocking I/O servers such as Ampule and Adafruit_CircuitPython_HTTPServer.
    * Much faster than non-blocking I/O servers such as circuitpython-native-wsgiserver, which can take up to 100ms per request on a 160MHz ESP32C3 due to 1-byte recv() calls.
* **More robust**: correctly handles binary data, overly-large paths/headers/requests, too-slow/dropped connections, etc.
    * Strictly bounds untrusted input size during request processing using the `max_request_line_size` and `max_body_bytes` settings.
    * Strictly bounds request processing time using the `request_timeout_seconds` setting.
    * Correctly handles unusual cases such as binary data, dropped connections with no TCP RST, and incomplete writes from the client.
* **Smaller**: single-file implementation with ~200 SLOC.
    * Around the same size as Ampule, and much smaller than the other options.
* **Few dependencies**: relies only on the `time` and `errno` libraries, both of which are built into Python/CircuitPython (as well as `wifi`, `mdns`, and `socketpool` if using the WiFi helpers).

However, compared to those libraries, it intentionally doesn't include some features in order to keep the codebase small:

* Helpers for parsing query parameters and dealing with URL encoding/decoding.
* Helpers for building HTTP responses, such as header formatting, templating, and more.
* Helpers for dealing with MIME types (Adafruit_CircuitPython_HTTPServer has this).
* Support for chunked transfer encoding (Adafruit_CircuitPython_HTTPServer has this).
* Support for serving static files (Adafruit_CircuitPython_HTTPServer has this).

Installation
------------

### Python

Install via Pip:

```sh
pip install biplane
```

### CircuitPython

First, ensure you've set up CircUp according to the [Adafruit CircUp guide](https://learn.adafruit.com/keep-your-circuitpython-libraries-on-devices-up-to-date-with-circup). Then:

```sh
circup install biplane
```

For CircuitPython devices that don't support the CIRCUITPY drive used to upload code, you can instead manually upload `biplane.py` from this folder to `lib/biplane.py` on the board using one of the following methods:

* Using the Web Workflow via Bluetooth or WiFi. See the [AdaFruit Web Workflow guide](https://learn.adafruit.com/circuitpython-with-esp32-quick-start/setting-up-web-workflow) for more details.
* Using [Thonny](https://thonny.org/), which supports uploading code to CircuitPython.
* As a last-resort slow-but-simple option, using the CircuitPython REPL that you can access over the serial port:
    1. Run `python3 -c 'f=open("biplane.py");code=f.read();print(f"code={repr(code)};open(\"lib/biplane.py\",\"w\").write(code) if len(code)=={len(code)} else print(\"CODE CORRUPTED\")")'` in this folder, and copy the output of that command to the clipboard. This output is CircuitPython code that creates `lib/biplane.py` with the correct contents inside.
    2. Paste the copied output into the CircuitPython REPL and run it. If it outputs "CODE CORRUPTED", that means the code changed between when you pasted it and when it arrived in CircuitPython, which means your serial terminal is sending the characters too quickly and CircuitPython can't keep up (common when using `screen` or `minicom`); to fix this, configure your terminal to wait 2ms-4ms after sending each character and try again (2ms is usually good enough). Also, make sure that you do this after freshly resetting the board.

Examples
--------

### Basic example (CircuitPython)

Starts a WiFi network called "test" (password is "some_password") - when connected, you can see a Hello World page at `http://app.local/` (tested on an ESP32C3):

```python
import biplane

server = biplane.Server()

@server.route("/", "GET")
def main(query_parameters, headers, body):
  return biplane.Response("<b>Hello, world!</b>", content_type="text/html")

for _ in server.circuitpython_start_wifi_ap("test", "some_password", "app"):
  pass
```

### Basic example (Python)

Starts a server that displays a Hello World page at `http://localhost:8000`, similar to the CircuitPython example above:

```python
import biplane

server = biplane.Server()

@server.route("/", "POST")
def main(query_parameters, headers, body):
  return biplane.Response("<b>Hello, world!</b>", content_type="text/html")

server_socket = socket.socket()
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # allow the server to reuse the address immediately after it's been closed
for _ in server.start(server_socket, listen_on=('127.0.0.1', 8000)):
  pass
```

The usage is almost exactly the same, but we pass in a socket from the Python `socket` library instead of from CircuitPython's `socketpool` library.

### Parallel execution (CircuitPython)

Blinks an LED consistently at ~100Hz while serving HTTP requests, keeping a ~100Hz frequency regardless of how quickly HTTP requests are coming in:

```python
import time
import board
import digitalio
import biplane

server = biplane.Server()

@server.route("/", "GET")
def main(query_parameters, headers, body):
  return biplane.Response("<b>Hello, world!</b>", content_type="text/html")

def asyncio_sleep(seconds):  # minimal implementation of asyncio.sleep() as a generator
  start_time = time.monotonic()
  while time.monotonic() - start_time < seconds:
    yield

def blink_builtin_led():
  with digitalio.DigitalInOut(pin) as led:
    led.switch_to_output(value=False)
    while True:
      led.value = not led.value
      yield from asyncio_sleep(0.01)

for _ in zip(blink_builtin_led(), server.circuitpython_start_wifi_ap("test", "some_password")):  # run through both generators at the same time using zip()
  pass
```

With other HTTP servers, blinking the LED while serving requests would either be impossible, or would become inconsistent when many HTTP requests are coming in.

Note that CircuitPython's GC pauses may cause occasional longer pauses - to mitigate this, run `import gc; gc.collect()` at regular, predictable intervals, so that the GC never has to be invoked at unpredictable times.

### Parallel execution with async/await (CircuitPython)

Many CircuitPython implementations, especially those for boards with less RAM/flash, don't include the `asyncio` library. However, if `asyncio` is available, Biplane works well with it as well:

```python
import time
import board
import digitalio
import biplane

server = biplane.Server()

@server.route("/", "GET")
def main(query_parameters, headers, body):
  return biplane.Response("<b>Hello, world!</b>", content_type="text/html")

async def run_server():
  for _ in server.circuitpython_start_wifi_ap("test", "some_password")
    await asyncio.sleep(0)  # let other tasks run

async def blink_builtin_led():
  with digitalio.DigitalInOut(pin) as led:
    led.switch_to_output(value=False)
    while True:
      led.value = not led.value
      await asyncio.sleep(0.01)

asyncio.run(asyncio.gather(blink_builtin_led(), run_server()))  # run both coroutines at the same time
```

Essentially, we just need to loop through the generator as usual while calling `await asyncio.sleep(0)` each iteration to let other tasks run.

License
-------

Copyright 2023 [Anthony Zhang (Uberi)](http://anthonyz.ca).

The source code is available online at [GitHub](https://github.com/Uberi/biplane).

This program is made available under the MIT license. See ``LICENSE.txt`` in the project's root directory for more information.
