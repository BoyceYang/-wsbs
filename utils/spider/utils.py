#!/usr/bin/env python
# coding:utf-8

import urlparse
import chardet
import requests

import lxml.html as H
from splinter import Browser


class WebKit(object):
    """WebKit引擎"""
    def __init__(self):
        self.tag_attr_dict = {'*': 'href',
                              'embed': 'src',
                              'frame': 'src',
                              'iframe': 'src',
                              'object': 'data'}
        self.browser = None

    def extract_links(self, url):
        """
        抓取页面链接
        """
        self.browser = Browser("phantomjs")
        try:
            self.browser.visit(url)
        except Exception, e:
            return
        for tag, attr in self.tag_attr_dict.iteritems():
            link_list = self.browser.find_by_xpath('//%s[@%s]' % (tag, attr))
            if not link_list:
                continue
            for link in link_list:
                link = link.__getitem__(attr)
                if not link:
                    continue
                link = link.strip()
                if link == 'about:blank' or link.startswith('javascript:'):
                    continue
                if not link.startswith('http'):
                    link = urlparse.urljoin(url, link)
                yield link

    def close(self):
        self.browser.quit()


class HtmlAnalyzer(object):
    """页面分析类"""
    @staticmethod
    def extract_links(html, base_ref, tags=[]):
        """
        抓取页面内链接(生成器)
        base_ref : 用于将页面中的相对地址转换为绝对地址
        tags     : 期望从该列表所指明的标签中提取链接
        """
        if not html.strip():
            return

        link_list = []
        try:
            doc = H.document_fromstring(html)
        except Exception, e:
            return

        default_tags = ['a', 'img', 'iframe', 'frame']
        default_tags.extend(tags)
        default_tags = list(set(default_tags))
        doc.make_links_absolute(base_ref)
        links_in_doc = doc.iterlinks()
        for link in links_in_doc:
            if link[0].tag in set(default_tags):
                yield link[2]


def to_unicode(data, charset=None):
    """
    将输入的字符串转化为unicode对象
    """
    unicode_data = ''
    if isinstance(data, str):
        if not charset:
            try:
                charset = chardet.detect(data).get('encoding')
            except Exception, e:
                pass
        if charset:
            unicode_data = data.decode(charset, 'ignore')
        else:
            unicode_data = data
    else:
        unicode_data = data
    return unicode_data


def monkey_patch():
    """
    requests库中文乱码补丁
    """
    prop = requests.models.Response.content

    def content(self):
        _content = prop.fget(self)
        if self.encoding == 'ISO-8859-1':
            encodings = requests.utils.get_encodings_from_content(_content)
            if encodings:
                self.encoding = encodings[0]
            else:
                self.encoding = self.apparent_encoding
            _content = _content.decode(self.encoding, 'replace').encode('utf8', 'replace')
            self._content = _content
        return _content
    requests.models.Response.content = property(content)