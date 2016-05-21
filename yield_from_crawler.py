#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import re
import time
from selectors import DefaultSelector
from selectors import EVENT_WRITE, EVENT_READ
import socket
import urllib.parse


selector = DefaultSelector()
urls_todo = set(['/'])
urls_seen = set(['/'])
stopped = False
concurrency_achieved = 0


class Future:

    def __init__(self):
        self.result = None
        self._callbacks = []

    def set_result(self, result):
        self.result = result
        for fn in self._callbacks:
            fn(self)

    def add_callback(self, callback):
        self._callbacks.append(callback)

    def __iter__(self):
        yield self
        return self.result


class Task:

    def __init__(self, coroutine):
        self.coroutine = coroutine
        f = Future()
        f.set_result(None)
        self.step(f)

    def step(self, future):
        try:
            next_future = self.coroutine.send(future.result)
        except StopIteration:
            return
        next_future.add_callback(self.step)


def connect(sock, address):
    f = Future()

    def on_connect():
        f.set_result(None)
    selector.register(sock.fileno(), EVENT_WRITE, on_connect)
    try:
        sock.connect(address)
    except BlockingIOError:
        pass
    yield from f
    selector.unregister(sock.fileno())


def read(sock):
    f = Future()

    def on_readable():
        f.set_result(sock.recv(4096))
    selector.register(sock.fileno(), EVENT_READ, on_readable)
    chunk = yield from f
    selector.unregister(sock.fileno())
    return chunk


def read_all(sock, request):
    sock.send(request)
    response = b''
    while True:
        chunk = yield from read(sock)
        if chunk:
            response += chunk
        else:
            break
    return response


def parse_links(response, addr, base_url):
    if not is_html(response):
        return set()
    body = get_body_of_response(response)
    urls = set(re.findall(r'''(?i)href=['"]?([^\s'"<>]+)''', body))
    links = set()
    for url in urls:
        norm_url = urllib.parse.urljoin(base_url, url)
        url_parts = urllib.parse.urlparse(norm_url)
        if url_parts.scheme not in ('http', 'https', ''):
            continue
        host, port = urllib.parse.splitport(url_parts.netloc)
        host = host.lower()
        if host and not (host in addr[0] or addr[0] in host):
            continue
        defragmented, frag = urllib.parse.urldefrag(url_parts.path)
        links.add(defragmented)
    return links


def is_html(response):
    headers = response.split(b'\r\n\r\n', 1)[0].decode('ascii')
    headers = dict(h.split(': ', 1) for h in headers.split('\r\n')[1:])
    return headers.get('Content-Type', '').startswith('text/html')


def get_body_of_response(response):
    return response.split(b'\r\n\r\n', 1)[1].decode('utf-8')


class Fetcher:

    def __init__(self, address):
        self.addr = address

    def fetch(self, url):
        global stopped, concurrency_achieved
        concurrency_achieved = max(concurrency_achieved, len(urls_todo))
        sock = socket.socket()
        sock.setblocking(False)
        yield from connect(sock, self.addr)
        request = 'GET {} HTTP/1.0\r\nHost: {}\r\n\r\n'.format(url, self.addr[0])
        response = yield from read_all(sock, request.encode('ascii'))
        links = parse_links(response, self.addr, url)
        for link in links.difference(urls_seen):
            urls_todo.add(link)
            Task(Fetcher(self.addr).fetch(link))
        urls_seen.update(links)
        urls_todo.remove(url)
        if not urls_todo:
            stopped = True
        print("fetched {}, {} pages to fetch, {} pages seen".format(url, len(urls_todo), len(urls_seen)))


def loop():
    while not stopped:
        events = selector.select()
        for event_key, event_mask in events:
            callback = event_key.data
            callback()


if __name__ == '__main__':
    start = time.time()
    fetcher = Fetcher(('xkcd.com', 80))
    Task(fetcher.fetch('/'))
    loop()
    print('{} URLs fetched in {:.1f} seconds, achieved concurrency = {}'.format(
        len(urls_seen), time.time() - start, concurrency_achieved))
