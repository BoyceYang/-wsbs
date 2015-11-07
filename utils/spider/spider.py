#!/usr/bin/env python
# -*- coding: utf-8 -*-

import uuid
import logging
import requests

import gevent
from gevent import queue
from gevent import Greenlet


class Fetcher(Greenlet):
    """抓取器"""
    def __init__(self, spider):
        gevent.Greenlet.__init__(self)
        self.fetcher_id = str(uuid.uuid1())[:8]
        self.TOO_LONG = 1048576  # 1M
        self.spider = spider
        self.fetcher_cache = self.spider.fetcher_cache
        self.crawler_cache = self.spider.crawler_cache
        self.fetcher_queue = self.spider.fetcher_queue
        self.crawler_queue = self.spider.crawler_queue

    def _fetcher(self):
        logging.info("Fetcher %s Starting..." % self.fetcher_id)
        while not self.spider.stopped.isSet():
            try:
                url_data = self.fetcher_queue.get(block=False)
            except queue.Empty, e:
                if self.spider.crawler_stopped.isSet() and self.fetcher_queue.unfinished_tasks == 0:
                    self.spider.stop()
                elif self.crawler_queue.unfinished_tasks == 0 and self.fetcher_queue.unfinished_tasks == 0:
                    self.spider.stop()
                else:
                    gevent.sleep()
            else:
                if not url_data.html:
                    try:
                        if url_data not in set(self.crawler_cache):
                            html = ''
                            with gevent.Timeout(self.spider.internal_timeout, False) as timeout:
                                html = self._open(url_data)
                            if not html.strip():
                                self.spider.fetcher_queue.task_done()
                                continue
                            logging.info("Fetcher %s Accept %s" % (self.fetcher_id, url_data))
                            url_data.html = html
                            if not self.spider.crawler_stopped.isSet():
                                self.crawler_queue.put(url_data, block=True)
                            self.crawler_cache.insert(url_data)
                    except Exception, e:
                        import traceback
                        traceback.print_exc()

    def _open(self, url_data):
        human_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/32.0.1700.76 Safari/537.36',
            'Accept-Encoding': 'gzip,deflate,sdch'
        }
        if self.spider.custom_headers:
            human_headers.update(self.spider.custom_headers)
        try:
            r = requests.get(url_data.url, headers=human_headers, stream=True)
        except Exception, e:
            logging.info("%s %s" % (url_data.url, str(e)))
            return u''
        else:
            if r.headers.get('content-type', '').find('text/html') < 0:
                r.close()
                return u''
            if int(r.headers.get('content-length',self.TOO_LONG)) > self.TOO_LONG:
                r.close()
                return u''
            try:
                html = r.content
                html = html.decode('utf-8','ignore')
            except Exception, e:
                logging.warn("%s %s" % (url_data.url,str(e)))
            finally:
                r.close()
                if vars().get('html'):
                    return html
                else:
                    return u''

    def _run(self):
        self._fetcher()