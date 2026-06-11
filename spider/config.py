#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"Mysql配置信息"

import os

config = {
    'address': os.getenv('MYSQL_HOST', 'localhost'),
    'port': int(os.getenv('MYSQL_PORT', '3306')),
    'username': os.getenv('MYSQL_USER', 'root'),
    'password': os.getenv('MYSQL_PASSWORD', 'root'),
    'database_name': os.getenv('MYSQL_DATABASE', 'news'),
}
