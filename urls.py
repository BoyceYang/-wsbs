#!/usr/bin/env python
# -*- coding: utf-8 -*-

from handlers.audit import AuditHandler

urls = [
    (r'/audit', AuditHandler),
]
