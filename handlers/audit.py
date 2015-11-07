#!/usr/bin/env python
# -*- coding: utf-8 -*-

from basic import BasicHandler


class AuditHandler(BasicHandler):
    def get(self):
        self.render('inpect_page.html')
