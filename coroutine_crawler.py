# -*- coding: utf8 -*-
from selectors import *
import re
import socket
import urllib.parse
import time

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


class Task:

    def __init__(self, coro):
        self.coro = coro
        f = Future()
        f.set_result(None)
        self.step(f)

    def step(self, future):
        try:
            next_future = self.coro.send(future.result)
        except StopIteration:
            return
        next_future.add_callback(self.step)


class Fetcher():

    def __init__(self, url):
        print("start fetching {}".format(url))
        self.url = url
        self.response = b''

    def fetch(self):
        global concurrency_achieved
        concurrency_achieved = max(concurrency_achieved, len(urls_todo))
        sock = socket.socket()
        sock.setblocking(False)
        try:
            sock.connect(('xkcd.com', 80))
        except BlockingIOError:
            pass

        f = Future()

        def on_connected():
            f.set_result(None)
        selector.register(sock.fileno(), EVENT_WRITE, on_connected)
        yield f
        selector.unregister(sock.fileno())
        print('connected')

        request = 'GET {} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n'.format(self.url)
        sock.send(request.encode('ascii'))
        global stopped
        while True:
            f = Future()

            def on_readable():
                f.set_result(sock.recv(4096))
            selector.register(sock.fileno(), EVENT_READ, on_readable)
            chunk = yield f
            selector.unregister(sock.fileno())
            if chunk:
                self.response += chunk
            else:
                links = self.parse_links()
                for link in links.difference(urls_seen):
                    urls_todo.add(link)
                    Task(Fetcher(link).fetch())
                urls_seen.update(links)
                urls_todo.remove(self.url)
                if not urls_todo:
                    stopped = True
                break

    def _is_html(self):
        headers, body = self.response.split(b'\r\n\r\n', 1)
        headers = dict(head.split(': ')
                       for head in headers.decode().split('\r\n')[1:])
        return headers.get('Content-Type', '').startswith('text/html')

    def body(self):
        body = self.response.split(b'\r\n\r\n', 1)[1]
        return body.decode('utf-8')

    def parse_links(self):
        if not self.response:
            print('error: {}'.format(self.url))
            return set()
        if not self._is_html():
            return set()
        urls = set(re.findall(r'''(?i)href=['"]?([^\s<>'"]+)''', self.body()))
        links = set()
        for url in urls:
            norm_url = urllib.parse.urljoin(self.url, url)
            url_parts = urllib.parse.urlparse(norm_url)
            if url_parts.scheme not in ('', 'http', 'https'):
                continue
            host, port = urllib.parse.splitport(url_parts.netloc)
            if host and host.lower() not in ('xkcd.com', 'www.xkcd.com'):
                continue
            defragmented, frag = urllib.parse.urldefrag(url_parts.path)
            links.add(defragmented)
        return links


def loop():
    while not stopped:
        events = selector.select()
        for event_key, event_mask in events:
            callback = event_key.data
            callback()

if __name__ == '__main__':
    start = time.time()
    fetcher = Fetcher('/')
    Task(fetcher.fetch())
    loop()
    print('{} URLs fetched in {:.1f} seconds, achieved concurrency = {}'.format(
        len(urls_seen), time.time() - start, concurrency_achieved))
