#!/usr/bin/env python
# -*- coding: utf-8 -*-

import tornado.web


class BasicHandler(tornado.web.RequestHandler):
    def __init__(self, application, request, **kwargs):
        super(BasicHandler, self).__init__(application, request, **kwargs)