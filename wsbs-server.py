#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
sys.path.append("..")
reload(sys)
sys.setdefaultencoding('gb18030')


import os
import logging
import logging.handlers

import tornado.web
import tornado.ioloop
import tornado.httpserver

from tornado.log import LogFormatter
from tornado.options import define, options

from urls import urls

"""
 Rewrite Tornado log formatter
"""
logger = logging.getLogger()
if options.log_file_prefix:
    logger.handlers = []
    channel = logging.handlers.TimedRotatingFileHandler(
        filename=options.log_file_prefix,
        when='midnight',
        backupCount=options.log_file_num_backups
    )
    channel.setFormatter(LogFormatter(color=False))
    logger.addHandler(channel)

define('application_name', default='Boyce WebSite', type=str)
define("port", default=10101, help="run on the given port", type=int)


class Application(tornado.web.Application):

    def __init__(self):

        settings = dict(
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "statics"),
            debug=True,
            gzip=True,
        )
        tornado.web.Application.__init__(self, handlers=urls, **settings)


def main():
    tornado.options.parse_command_line()
    http_server = tornado.httpserver.HTTPServer(Application())
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()


if __name__ == "__main__":
    main()


