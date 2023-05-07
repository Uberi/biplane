import socket
import urllib.request
import threading
import asyncio
import time

import os, sys; sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), '..'))  # add current folder to import path to ensure we can import biplane no matter what's in PYTHONPATH
import biplane


def test_basic():
    # set up background thread to make a server request
    response, response_content = None, None
    def make_request():
        nonlocal response, response_content
        time.sleep(1)
        response = urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/', b"test"), timeout=3)
        response_content = response.read()
    request_thread = threading.Thread(target=make_request)
    request_thread.start()

    # start the server
    server = biplane.Server()
    request_query, request_headers, request_body = None, None, None
    @server.route("/", "POST")
    def main(query_parameters, headers, body):
        nonlocal request_query, request_headers, request_body
        request_query, request_headers, request_body = query_parameters, headers, body
        return biplane.Response("abcdef")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # allow the server to reuse the address immediately after it's been closed
    for _ in server.start(server_socket, listen_on=('127.0.0.1', 8000)):
        if not request_thread.is_alive():
            break
    else:
        request_thread.join()

    assert request_query == "", request_query
    assert request_headers.get('content-length') == '4', request_headers.get('content-length')
    assert request_body == b'test', request_body
    assert response.status == 200, response.status
    assert response_content == b"abcdef", response_content

test_basic()
print("ALL TESTS PASSED")