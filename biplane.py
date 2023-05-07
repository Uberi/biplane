import time
import errno


__version__ = "0.0.0+auto.0"
__repo__ = "https://github.com/Uberi/biplane.git"


class BufferedNonBlockingSocket:
  def __init__(self, sock, buffer_size=2):
    self.sock = sock
    self.read_buffer = bytearray(buffer_size)
    self.start, self.end = 0, 0

  def read(self, size=-1, stop_byte=None):
    while True:
      # fulfill as much of the request as possible from the buffer
      if stop_byte is not None:
        try:
          new_size = self.read_buffer[self.start:].index(stop_byte) + 1  # stop immediately after encountering the stop byte
          size = min(size, new_size) if size >= 0 else new_size
        except ValueError:
          pass
      buffer_slice = self.read_buffer[self.start:min(self.end, self.start + size) if size >= 0 else self.end]
      if buffer_slice:
        yield buffer_slice
      size -= len(buffer_slice)
      self.start += len(buffer_slice)
      if size == 0:  # request satisfied
        break

      # request still unsatisfied, refresh buffer and try again
      self.start, self.end = 0, 0
      try:
        self.end = self.sock.recv_into(self.read_buffer, len(self.read_buffer))
        if self.end == 0:  # client closed connection, there's no more to read
          break
      except OSError as e:
        if e.errno != errno.EAGAIN:
          raise
      yield b""  # client is not done sending yet, try again

  def write(self, data):
    bytes_sent = 0
    while bytes_sent < len(data):
      yield
      try:
        bytes_sent += self.sock.send(data[bytes_sent:])
      except OSError as e:
        if e.errno != errno.EAGAIN:  # still pending, try again
          raise


class Response:
  def __init__(self, body, status_code=200, content_type="text/plain", headers={}):
    self.body_bytes = body if isinstance(body, bytes) else body.encode("ascii")
    self.status_code = status_code
    self.headers = headers
    self.headers["content-length"] = len(self.body_bytes)
    self.headers["content-type"] = content_type

  def serialize(self):
    response = bytearray(f"HTTP/1.1 {self.status_code} {self.status_code}\r\n".encode("ascii"))
    for name, value in self.headers.items():
      response += f"{name}: {value}\r\n".encode("ascii")
    yield response + b"\r\n" + self.body_bytes


class Server:
  def __init__(self, max_request_line_size=4096, max_header_count=50, max_body_bytes=65536, request_timeout_seconds=10):
    self.routes = []
    self.max_request_line_size = max_request_line_size
    self.max_header_count = max_header_count
    self.max_body_bytes = max_body_bytes
    self.request_timeout_seconds = request_timeout_seconds

  def route(self, path, method='GET'):
    def register_route(request_handler):
      self.routes.append((path, method, request_handler))
    return register_route

  def handle_request(self, target, method, headers, content_length, buffered_client_socket):  # subclass Server and override this method for more customized request handling (e.g., large file uploads)
    if content_length > self.max_body_bytes:
      yield from Response("Content Too Large", 413).serialize()
      return

    # read request body
    body = bytearray()
    for data in buffered_client_socket.read(size=content_length):
      yield b""
      body += data

    path, query_parameters = target.split("?", 1) if "?" in target else (target, "")
    for route_path, route_method, request_handler in self.routes:
      if path == route_path and method == route_method:
        response = request_handler(query_parameters, headers, body)
        assert isinstance(response, Response), type(response)
        print("response status", response.status_code, "sending", len(response.body_bytes), "bytes")
        yield from response.serialize()
        return
    yield from Response("Not Found", 404).serialize()
    return

  def process_client_connection(self, buffered_client_socket):
    try:
      # parse start line
      start_line = bytearray()
      for data in buffered_client_socket.read(size=self.max_request_line_size, stop_byte=b'\n'):
        yield
        start_line += data
      print("received request", start_line)
      if start_line[-1:] != b'\n':
        print("excessively long start line, giving up")
      try:
        method, target, _ = start_line.decode("ascii").split(" ", 2)
      except UnicodeError:
        print("malformed start line, giving up")
        return

      # parse headers and request body
      headers = {}
      for _ in range(self.max_header_count + 1):
        header_line = bytearray()
        for data in buffered_client_socket.read(size=self.max_request_line_size, stop_byte=b'\n'):
          yield
          header_line += data
        if header_line[-1:] != b"\n":
          print("excessively long header, giving up")
          return
        if header_line == b"\r\n":  # end of headers
          break
        header_line = header_line.decode("ascii")
        if ":" not in header_line:
          print("malformed header, giving up")
          return
        header_name, header_value = header_line.split(":", 1)
        headers[header_name.strip().lower()] = header_value.strip()
        yield
      else:
        print("too many headers, giving up")
        return

      # generate and send response
      try:
        content_length = max(0, int(headers.get('content-length', '0')))
      except ValueError:
        print("malformed content-length header, giving up")
        return
      for data in self.handle_request(target, method, headers, content_length, buffered_client_socket):
        yield
        for _ in buffered_client_socket.write(data):
          yield
    except OSError as e:
      if e.errno not in (errno.ECONNRESET, errno.ENOTCONN):
        raise

  def start(self, server_socket, listen_on=('0.0.0.0', 80), max_parallel_connections=5):
    server_socket.setblocking(False)
    server_socket.bind(listen_on)
    server_socket.listen(max_parallel_connections)
    client_processors = []
    while True:
      if len(client_processors) < max_parallel_connections:
        try:
          new_client_socket, new_client_address = server_socket.accept()
        except OSError as e:
          if e.errno != errno.EAGAIN:
            raise
          # no connectings pending, try again
        else:
          print("accepted connection from", new_client_address)
          client_processors.append((time.monotonic(), new_client_socket, self.process_client_connection(BufferedNonBlockingSocket(new_client_socket))))

      # step through open client connections
      now = time.monotonic()
      new_client_processors = []
      for start_time, client_socket, client_processor in client_processors:
        try:
          if now - start_time > self.request_timeout_seconds:
            raise StopIteration()  # timed out
          next(client_processor)
        except Exception as e:
          client_socket.close()
          if not isinstance(e, StopIteration):
            raise
        else:
          new_client_processors.append((start_time, client_socket, client_processor))
      client_processors = new_client_processors
      yield

  def circuitpython_start_wifi_ap(self, ssid, password, mdns_hostname=None, listen_on=('0.0.0.0', 80), max_parallel_connections=5):
    import wifi
    import mdns
    import socketpool
    wifi.radio.start_ap(ssid=ssid, password=password)
    print(f"starting mDNS at {SERVICE_HOSTNAME}.local (IP address {wifi.radio.ipv4_address_ap})")
    server = mdns.Server(wifi.radio)
    server.hostname = mdns_hostname
    server.advertise_service(service_type="_http", protocol="_tcp", port=listen_on[1])
    pool = socketpool.SocketPool(wifi.radio)
    with pool.socket() as server_socket:
      yield from self.start_server(server_socket, listen_on, max_parallel_connections)

  def circuitpython_start_wifi_station(self, ssid, password, mdns_hostname, listen_on=('0.0.0.0', 80), max_parallel_connections=5):
    import wifi
    import mdns
    import socketpool
    wifi.radio.connect(ssid, password)
    print(f"starting mDNS at {SERVICE_HOSTNAME}.local (IP address {wifi.radio.ipv4_address})")
    server = mdns.Server(wifi.radio)
    server.hostname = mdns_hostname
    server.advertise_service(service_type="_http", protocol="_tcp", port=listen_on[1])
    pool = socketpool.SocketPool(wifi.radio)
    with pool.socket() as server_socket:
      yield from self.start_server(server_socket, listen_on, max_parallel_connections)
