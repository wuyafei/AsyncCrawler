#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import sys
from asyncio import Queue
import asyncio
import aiohttp
import logging
import urllib.parse
import time


LOGGER = logging.getLogger(__name__)


class Crawler:

    def __init__(self, domain, max_redirects=10,
                 max_retries=3, max_tasks=10):
        self.domain = domain
        self.max_redirects = max_redirects
        self.max_tasks = max_tasks
        self.max_retries = max_retries
        # self.loop = loop or asyncio.get_event_loop()
        self.q = Queue()
        self.urls_seen = set()
        self.session = aiohttp.ClientSession()
        self.add_url('/')

    @asyncio.coroutine
    def crawl(self):
        workers = [asyncio.Task(self.work())
                   for _ in range(self.max_tasks)]
        yield from self.q.join()
        for worker in workers:
            worker.cancel()

    def close(self):
        self.session.close()

    @asyncio.coroutine
    def work(self):
        try:
            while True:
                url, max_redirects = yield from self.q.get()
                # LOGGER.debug('fetching {}'.format(url))
                yield from self.fetch(url, max_redirects)
                self.q.task_done()
        except asyncio.CancelledError:
            pass

    @asyncio.coroutine
    def fetch(self, url, max_redirects):
        retry = 0
        while retry < self.max_retries:
            try:
                response = yield from self.session.get(self.domain+url, allow_redirects=False)
                LOGGER.debug('fetched {}'.format(url))
                break
            except aiohttp.ClientError as client_err:
                retry += 1
                LOGGER.info('fetching {} failed {} times with error {}'.format(url, retry, client_err))
            except Exception as e:
                LOGGER.error('fetching {} with error: {}'.format(url, e))
                return
        else:
            LOGGER.error('fetching {} out of max retry times'.format(url))
            return

        if self.is_redirect(response):
            location = response.headers['location']
            next_url = urllib.parse.urlparse(location).path
            next_url = urllib.parse.urljoin(url, next_url)
            if next_url in self.urls_seen:
                pass
            elif max_redirects > 0:
                self.add_url(next_url, max_redirects-1)
                LOGGER.info('redirect from {} to {}'.format(url, next_url))
            else:
                LOGGER.error('redirect from {} to {} out of times'.format(url, next_url))
        else:
            links = yield from self.parse_links(response)
            LOGGER.debug('parsed {} links from {}'.format(len(links), url))
            for link in links.difference(self.urls_seen):
                self.q.put_nowait((link, self.max_redirects))
            self.urls_seen.update(links)
        yield from response.release()

    def add_url(self, url, max_redirects=None):
        max_redi = max_redirects or self.max_redirects
        self.urls_seen.add(url)
        self.q.put_nowait((url, max_redi))

    def is_redirect(self, response):
        return response.status in (300, 301, 302, 303, 307)

    @asyncio.coroutine
    def parse_links(self, response):
        links = set()
        if response.status == 200:
            content_type = response.headers.get('content-type', '')
            if content_type and content_type.startswith('text/html'):
                text = yield from response.text()
                urls = set(re.findall(r'''(?i)href=["']([^\s"'<>]+)''',
                                      text))
                if urls:
                    LOGGER.info('got {} distinct urls from {}'.format(
                                len(urls), response.url))
                for url in urls:
                    norm_url = urllib.parse.urljoin(response.url, url)
                    url_parts = urllib.parse.urlparse(norm_url)
                    if url_parts.scheme not in ('http', 'https', ''):
                        continue
                    host, port = urllib.parse.splitport(url_parts.netloc)
                    host = host.lower()
                    host = host[4:] if host.startswith('www.') else host
                    if host and not host in self.domain:
                        continue
                    defragmented, frag = urllib.parse.urldefrag(url_parts.path)
                    links.add(defragmented)
        return links


def main():
    logging.basicConfig(level=logging.ERROR)
    loop = asyncio.get_event_loop()
    crawler = Crawler(domain='http://xkcd.com')
    start = time.time()
    try:
        loop.run_until_complete(crawler.crawl())  # Crawler gonna crawl.
        print('{} pages fetched in {} seconds'.format(len(crawler.urls_seen), time.time()-start))
    except KeyboardInterrupt:
        sys.stderr.flush()
        print('\nInterrupted\n')
    finally:
        crawler.close()

        # next two lines are required for actual aiohttp resource cleanup
        loop.stop()
        loop.run_forever()

        loop.close()

if __name__ == '__main__':
    main()
