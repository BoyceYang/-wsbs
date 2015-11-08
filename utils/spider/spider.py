#!/usr/bin/env python
# -*- coding: utf-8 -*-

import gevent
from gevent import monkey
monkey.patch_all()
from gevent import queue
from gevent import Greenlet
from gevent import event
from gevent import Timeout
from gevent import pool
from gevent import threadpool

import os
import uuid
import logging
import urlparse
import requests

from exceptions import *

from cache import UrlCache, UrlData
from utils import HtmlAnalyzer, monkey_patch, to_unicode

monkey_patch()

try:
    from utils import WebKit
except Exception, e:
    pass


from srvconf import IMG_UNSPIDER_URL_KEY
from dbmanager import global_redis


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
        self.unspider_url_list = self.spider.unspider_url_list
        self.spider_type = self.spider.spider_type

    def _fetcher(self):
        logging.info("Fetcher %s Starting..." % self.fetcher_id)
        while not self.spider.stopped.isSet():                # 队列中存在任务，进入循环
            try:
                url_data = self.fetcher_queue.get(block=False)      # 取队列中的元素，不阻塞（可选超时和阻塞）
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
                            else:
                                # 存储未遍历的url
                                self.unspider_url_list.append(url_data.url)
                            self.crawler_cache.insert(url_data)
                            self.crawler_cache.store_content(html, url_data.url, self.spider_type)
                    except Exception, e:
                        import traceback
                        traceback.print_exc()
                self.spider.fetcher_queue.task_done()

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
            if int(r.headers.get('content-length', self.TOO_LONG)) > self.TOO_LONG:
                r.close()
                return u''
            try:
                html = r.content
                html = html.decode('utf-8', 'ignore')
            except Exception, e:
                logging.warn("%s %s" % (url_data.url, str(e)))
            finally:
                r.close()
                if vars().get('html'):
                    return html
                else:
                    return u''

    def _run(self):
        self._fetcher()


class Spider(object):
    """
        concurrent_num    : 并行crawler和fetcher数量
        crawl_tags        : 爬行时收集URL所属标签列表
        custom_headers    : 自定义HTTP请求头
        plugin            : 自定义插件列表
        depth             : 爬行深度限制
        max_url_num       : 最大收集URL数量
        internal_timeout  : 内部调用超时时间
        spider_timeout    : 爬虫超时时间
        crawler_mode      : 爬取器模型(0:多线程模型,1:gevent模型)
        same_origin       : 是否限制相同域下
        dynamic_parse     : 是否使用WebKit动态解析
    """
    def __init__(self, concurrent_num=20, crawl_tags=[], custom_headers={}, plugin=[], depth=3, max_url_num=300,
                 internal_timeout=60, spider_timeout=6*3600, crawler_mode=0, same_origin=True, dynamic_parse=False,
                 spider_type='img'):
        self.stopped = event.Event()
        self.internal_timeout = internal_timeout
        self.internal_timer = Timeout(internal_timeout)

        self.crawler_mode = crawler_mode             # 爬取器模型
        self.concurrent_num = concurrent_num
        self.fetcher_pool = pool.Pool(self.concurrent_num)                  # 运行的进程数目

        if self.crawler_mode == 0:
            self.crawler_pool = threadpool.ThreadPool(min(50, self.concurrent_num))
        else:
            self.crawler_pool = pool.Pool(self.concurrent_num)

        # self.crawler_pool = []
        self.fetcher_queue = threadpool.Queue(maxsize=self.concurrent_num*10000)
        self.crawler_queue = threadpool.Queue(maxsize=self.concurrent_num*10000)

        self.fetcher_cache = UrlCache()                     # url缓存设置
        self.crawler_cache = UrlCache()

        self.default_crawl_tags = ['a', 'base', 'iframe', 'frame', 'object']
        self.ignore_ext = ['js', 'css', 'png', 'jpg', 'gif', 'bmp', 'svg', 'exif', 'jpeg', 'exe', 'rar', 'zip']

        self.crawl_tags = list(set(self.default_crawl_tags) | set(crawl_tags))       # 取二者的并集
        self.same_origin = same_origin
        self.depth = depth                              # 爬虫访问深度
        self.max_url_num = max_url_num
        self.dynamic_parse = dynamic_parse
        if self.dynamic_parse:
            self.webkit = WebKit()
        self.crawler_stopped = event.Event()

        self.plugin_handler = plugin   # 注册Crawler中使用的插件
        self.custom_headers = custom_headers
        self.unspider_url_list = []
        self.spider_type = spider_type

    def _start_fetcher(self):
        for i in xrange(self.concurrent_num):
            fetcher = Fetcher(self)
            self.fetcher_pool.start(fetcher)

    def _start_crawler(self):
        for _ in xrange(self.concurrent_num):
            self.crawler_pool.spawn(self.crawler)
        # self.crawler_pool = [gevent.spawn(self.crawler) for _ in xrange(self.concurrent_num)]

    def start(self):
        logging.info("spider starting...")

        if self.crawler_mode == 0:
            logging.info("crawler run in multi-thread mode.")
        elif self.crawler_mode == 1:
            logging.info("crawler run in gevent mode.")

        self._start_fetcher()
        self._start_crawler()

        self.stopped.wait()      # 等待停止事件置位

        try:
            self.internal_timer.start()
            self.fetcher_pool.join(timeout=self.internal_timer)

            if self.crawler_mode == 1:
                self.crawler_pool.join(timeout=self.internal_timer)
            else:
                self.crawler_pool.join()

        except Timeout:
            logging.error("internal timeout triggered")
        finally:
            self.internal_timer.cancel()

        self.stopped.clear()
        if self.dynamic_parse:
            self.webkit.close()

        unspider_url_list = list(set(self.unspider_url_list))          # 对未访问的list进行去重
        unspider_url_list.sort(key=self.unspider_url_list.index)
        redis_key = IMG_UNSPIDER_URL_KEY         # redis_key控制spider检索的数据类型

        try:
            with global_redis.pipeline() as pipe:
                pipe.lpush(redis_key, *unspider_url_list).ltrim(redis_key, 0, 100).expire(redis_key, 72000).execute()
        except:
            logging.info("store unspider url error!!")
            pass
        logging.info("crawler_cache:%s fetcher_cache:%s" % (len(self.crawler_cache), len(self.fetcher_cache)))
        logging.info("spider process quit.")

    def crawler(self, _dep=None):
        while not self.stopped.isSet() and not self.crawler_stopped.isSet():
            try:
                self._maintain_spider()         # 维护爬虫池
                url_data = self.crawler_queue.get(block=False)
            except queue.Empty, e:
                if self.crawler_queue.unfinished_tasks == 0 and self.fetcher_queue.unfinished_tasks == 0:
                    self.stop()
                else:
                    if self.crawler_mode == 1:
                        gevent.sleep()
            else:
                pre_depth = url_data.depth
                curr_depth = pre_depth+1
                link_generator = HtmlAnalyzer.extract_links(url_data.html, url_data.url, self.crawl_tags)
                link_list = [url for url in link_generator]

                if self.dynamic_parse:
                    link_generator = self.webkit.extract_links(url_data.url)
                    link_list.extend([url for url in link_generator])
                link_list = list(set(link_list))
                for index, link in enumerate(link_list):
                    if not self.check_url_usable(link):
                        continue
                    if curr_depth > self.depth:     # 最大爬行深度判断
                        if self.crawler_stopped.isSet():
                            break
                        else:
                            self.crawler_stopped.set()
                            break
                    if len(self.fetcher_cache) == self.max_url_num:   # 最大收集URL数量判断
                        if self.crawler_stopped.isSet():
                            break
                        else:
                            self.crawler_stopped.set()
                            break
                    link = to_unicode(link)
                    url = UrlData(link, depth=curr_depth)
                    self.fetcher_cache.insert(url)
                    self.fetcher_queue.put(url, block=True)

                for plugin_name in self.plugin_handler:     # 循环动态调用初始化时注册的插件
                    try:
                        plugin_obj = eval(plugin_name)()
                        plugin_obj.start(url_data)
                    except Exception, e:
                        import traceback
                        traceback.print_exc()

                self.crawler_queue.task_done()

    def check_url_usable(self, link):
        """
        检查URL是否符合可用规则
        """
        if link in self.fetcher_cache:
            return False

        if not link.startswith("http"):
            return False

        if self.same_origin:
            if not self._check_same_origin(link):
                return False

        link_ext = os.path.splitext(urlparse.urlsplit(link).path)[-1][1:]
        if link_ext in self.ignore_ext:
            return False

        return True

    def feed_url(self, url):
        """
        设置初始爬取URL
        """
        if isinstance(url, basestring):
            url = to_unicode(url)
            url = UrlData(url)

        if self.same_origin:
            url_part = urlparse.urlparse(unicode(url))
            self.origin = (url_part.scheme, url_part.netloc)

        self.fetcher_queue.put(url, block=True)

    def stop(self):
        """
        终止爬虫
        """
        self.stopped.set()

    def _maintain_spider(self):
        """
        维护爬虫池:
        1)从池中剔除死掉的crawler和fetcher
        2)根据剩余任务数量及池的大小补充crawler和fetcher
        维持爬虫池饱满
        """
        if self.crawler_mode == 1:
            for greenlet in list(self.crawler_pool):
                if greenlet.dead:
                    self.crawler_pool.discard(greenlet)
            for i in xrange(min(self.crawler_queue.qsize(), self.crawler_pool.free_count())):
                self.crawler_pool.spawn(self.crawler)

        for greenlet in list(self.fetcher_pool):
            if greenlet.dead:
                self.fetcher_pool.discard(greenlet)
        for i in xrange(min(self.fetcher_queue.qsize(), self.fetcher_pool.free_count())):
            fetcher = Fetcher(self)
            self.fetcher_pool.start(fetcher)

    def _check_same_origin(self, current_url):
        """
        检查两个URL是否同源
        """
        current_url = to_unicode(current_url)
        url_part = urlparse.urlparse(current_url)
        url_origin = (url_part.scheme, url_part.netloc)
        return url_origin == self.origin


if __name__ == '__main__':
    spider = Spider(concurrent_num=5, depth=3, max_url_num=300, crawler_mode=0, dynamic_parse=False)
    url = "http://image.baidu.com/"
    spider.feed_url(url)
    spider.start()