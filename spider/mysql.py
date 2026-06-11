#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"Mysql操作类"

import pymysql


class Mysql(object):
    def __init__(self, config):
        self.__db = None
        if isinstance(config, dict):
            try:
                self.__address = config["address"]
                self.__port = config["port"]
                self.__username = config["username"]
                self.__password = config["password"]
                self.__database = config["database_name"]
                self.connect()
            except KeyError:
                print("Config Error.")
                print("Check the \"config.py\".")

    def __del__(self):
        self.close()

    def connect(self):
        """建立Mysql连接"""
        self.__db = pymysql.connect(
            host=self.__address,
            port=self.__port,
            user=self.__username,
            passwd=self.__password,
            db=self.__database,
            charset="utf8mb4",
            autocommit=False,
        )

    def close(self):
        """关闭mysql连接"""
        if self.__db:
            self.__db.close()
            self.__db = None

    def execute(self, sql, args=None):
        """执行一条写入或DDL语句"""
        self.ping()
        cursor = self.__db.cursor()
        try:
            cursor.execute(sql, args)
            self.__db.commit()
            return cursor.rowcount
        except Exception:
            self.__db.rollback()
            raise
        finally:
            cursor.close()

    def insert(self, sql, args=None):
        """插入一条记录"""
        return self.execute(sql, args)

    def query(self, sql, args=None):
        """查询一条记录"""
        self.ping()
        cursor = self.__db.cursor()
        try:
            cursor.execute(sql, args)
            return cursor.fetchone()
        finally:
            cursor.close()

    def queryall(self, sql, args=None):
        """查询全部记录"""
        self.ping()
        cursor = self.__db.cursor()
        try:
            cursor.execute(sql, args)
            return cursor.fetchall()
        finally:
            cursor.close()

    def ping(self):
        """Mysql断开重连"""
        try:
            self.__db.ping(reconnect=True)
        except Exception:
            self.connect()
