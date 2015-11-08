#!/usr/bin/env python
# -*- coding: utf-8 -*-

import lxml.html as H

from srvconf import SPIDER_IMG_KEY
from dbmanager import global_redis


class UrlData(object):
    """URL对象类"""
    def __init__(self, url, html=None, depth=0):
        self.url = url
        self.html = html
        self.depth = depth
        self.params = {}
        self.fragments = {}
        self.post_data = {}

    def __str__(self):
        return self.url

    def __repr__(self):
        return '<Url data: %s>' % (self.url,)

    def __hash__(self):
        return hash(self.url)


class UrlCache(object):
    """URL缓存类"""
    def __init__(self):
        self.__url_cache = {}

    def __len__(self):
        return len(self.__url_cache)

    def __contains__(self, url):
        return hash(url) in self.__url_cache.keys()

    def __iter__(self):
        for url in self.__url_cache:
            yield url

    def insert(self, url):
        # self.store_image_link(url)
        if isinstance(url, basestring):
            url = UrlData(url)
        if url not in self.__url_cache:
            self.__url_cache.setdefault(hash(url), url)

    def store_content(self, html, base_ref, spider_type):
        if spider_type == 'img':
            self.store_image_link(html, base_ref)

    def store_image_link(self, html, base_ref):

        if not html.strip():
            return

        try:
            doc = H.document_fromstring(html)
        except Exception, e:
            return

        default_tags = ['img']
        doc.make_links_absolute(base_ref)
        links_in_doc = doc.iterlinks()
        link_list = []
        for link in links_in_doc:
            if link[0].tag in set(default_tags):
                link_list.append(link[2])

        if len(link_list):
            try:
                with global_redis.pipeline() as pipe:
                    pipe.sadd(SPIDER_IMG_KEY, *link_list).expire(SPIDER_IMG_KEY, 72000).execute()
            except:
                return