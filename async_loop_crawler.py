# -*- conding: utf8-*-
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


class Fetcher:

    def __init__(self, url):
        self.url = url
        print("start fetching {}".format(url))
        self.response = b''
        self.sock = None

    def fetch(self):
        global concurrency_achieved
        concurrency_achieved = max(concurrency_achieved, len(urls_todo))
        self.sock = socket.socket()
        self.sock.setblocking(False)
        try:
            self.sock.connect(('xkcd.com', 80))
        except BlockingIOError:
            pass
        selector.register(self.sock.fileno(), EVENT_WRITE, self.connected)

    def connected(self, key, mask):
        # print('connected')
        selector.unregister(key.fd)
        request = 'GET {} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n'.format(self.url)
        self.sock.send(request.encode('ascii'))
        selector.register(key.fd, EVENT_READ, self.read_response)

    def read_response(self, key, mask):
        global stopped
        chunk = self.sock.recv(4096)
        if chunk:
            self.response += chunk
        else:
            selector.unregister(key.fd)
            # print(self.response)
            links = self.parse_links()
            for link in links.difference(urls_seen):
                urls_todo.add(link)
                Fetcher(link).fetch()
            urls_seen.update(links)
            urls_todo.remove(self.url)
            if not urls_todo:
                stopped = True

    def _is_html(self):
        headers, body = self.response.split(b'\r\n\r\n', 1)
        headers = dict(head.split(': ') for head in headers.decode().split('\r\n')[1:])
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
            callback(event_key, event_mask)

if __name__ == '__main__':
    start = time.time()
    Fetcher('/').fetch()
    loop()
    print('{} URLs fetched in {:.1f} seconds, achieved concurrency = {}'.format(
        len(urls_seen), time.time() - start, concurrency_achieved))
