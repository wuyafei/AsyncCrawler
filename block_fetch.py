# -*-conding: utf8-*-
import socket
import re


def fetch(url):
    sock = socket.socket()
    sock.connect(('xkcd.com', 80))
    request = 'GET {} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n'.format(url)
    sock.send(request.encode('ascii'))
    response = b''
    chunk = sock.recv(4096)
    while chunk:
        response += chunk
        chunk = sock.recv(4096)

    # Page is now downloaded.
    urls = set(re.findall(r'''(?i)href=["']?([^\s"'<>]+)''',
                   response.split(b'\r\n\r\n', 1)[1].decode('utf-8')))
    print(urls)


if __name__ == '__main__':
    fetch('/')
