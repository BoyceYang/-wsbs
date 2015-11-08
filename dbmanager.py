#!/usr/bin/env python
# -*-coding:utf-8-*-

import redis

from srvconf import REDIS_HOST, REDIS_PORT

global_redis = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT)
