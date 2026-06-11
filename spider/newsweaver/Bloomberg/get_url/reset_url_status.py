#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重置所有URL状态为pending
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import pymongo
from urllib.parse import quote_plus
import subprocess
import time
import socket
import logging

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# 加载环境变量
load_dotenv()

class SSHTunnel:
    """SSH隧道管理类"""
    def __init__(self):
        self.process = None
        self.local_port = None
    
    def _start_ssh_tunnel(self, ssh_host, ssh_port, ssh_user, ssh_key_path, 
                          remote_host, remote_port, local_port):
        """启动SSH隧道"""
        try:
            if local_port is None:
                local_port = 27017
            
            self.local_port = local_port
            
            ssh_cmd = [
                "ssh",
                "-N", "-T",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=5",
                "-o", "ServerAliveCountMax=2",
                "-o", "StrictHostKeyChecking=accept-new",
                "-i", ssh_key_path,
                "-p", str(ssh_port),
                "-L", f"127.0.0.1:{local_port}:{remote_host}:{remote_port}",
                f"{ssh_user}@{ssh_host}",
            ]
            
            print(f"[INFO] 启动SSH隧道: {ssh_host}:{ssh_port} -> 127.0.0.1:{local_port}")
            
            self.process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
            
            # 等待隧道建立
            max_retries = 10
            retry_interval = 0.5
            
            for attempt in range(max_retries):
                time.sleep(retry_interval)
                
                if self.process.poll() is not None:
                    return False
                
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                try:
                    result = sock.connect_ex(('127.0.0.1', local_port))
                    sock.close()
                    if result == 0:
                        print(f"[OK] SSH隧道建立成功")
                        return True
                except Exception:
                    pass
            
            return False
            
        except Exception as e:
            print(f"[ERROR] 启动SSH隧道失败: {e}")
            return False
    
    def stop_tunnel(self):
        """停止SSH隧道"""
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
                print("[INFO] SSH隧道已关闭")
            except Exception as e:
                print(f"[ERROR] 关闭SSH隧道失败: {e}")

def main():
    """主函数"""
    print("="*60)
    print("Bloomberg URL状态重置工具")
    print("="*60)
    print("功能: 将所有URL状态改为pending")
    
    ssh_tunnel = SSHTunnel()
    
    try:
        # 1. 连接MongoDB
        print("\n[1] 连接MongoDB...")
        
        # 读取配置
        ssh_host = os.getenv('SSH_HOST', '')
        ssh_port = int(os.getenv('SSH_PORT', '7022'))
        ssh_user = os.getenv('SSH_USER', 'tunnel')
        ssh_key_path = os.getenv('SSH_KEY_PATH', '')
        remote_mongo_host = os.getenv('SSH_REMOTE_HOST', '127.0.0.1')
        remote_mongo_port = int(os.getenv('SSH_REMOTE_PORT', '27017'))
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', '27017'))
        mongo_user = os.getenv('MONGO_USER', '')
        mongo_password = os.getenv('MONGO_PASSWORD', '')
        mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')
        
        database_name = os.getenv('MONGODB_DATABASE') or os.getenv('URL_QUEUE_DATABASE', 'bloomberg_url_queue')
        collection_name = os.getenv('MONGODB_COLLECTION') or os.getenv('URL_QUEUE_COLLECTION', 'urls')
        
        print(f"[INFO] SSH配置: {ssh_user}@{ssh_host}:{ssh_port}")
        print(f"[INFO] 目标数据库: {database_name}.{collection_name}")
        
        # 启动SSH隧道
        if not ssh_tunnel._start_ssh_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, 
                                            remote_mongo_host, remote_mongo_port, mongo_port):
            print("[ERROR] SSH隧道启动失败")
            return
        
        # 连接MongoDB
        if mongo_user and mongo_password:
            encoded_username = quote_plus(mongo_user)
            encoded_password = quote_plus(mongo_password)
            connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/?authSource={mongo_authsource}"
        else:
            connection_string = f"mongodb://{mongo_host}:{mongo_port}/"
        
        client = pymongo.MongoClient(connection_string, serverSelectionTimeoutMS=8000, socketTimeoutMS=8000)
        client.admin.command('ping')
        print("[OK] MongoDB连接成功!")
        
        db = client[database_name]
        collection = db[collection_name]
        
        # 2. 统计当前状态
        print("\n[2] 统计当前URL状态...")
        
        total_count = collection.estimated_document_count()
        print(f"[INFO] 总URL数: {total_count}")
        
        # 按状态统计
        pipeline = [
            {'$group': {'_id': '$status', 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}}
        ]
        
        status_stats = {}
        for doc in collection.aggregate(pipeline):
            status = doc['_id'] if doc['_id'] else '(无状态)'
            status_stats[status] = doc['count']
        
        print(f"\n当前状态分布:")
        for status, count in status_stats.items():
            print(f"  {status}: {count}")
        
        # 3. 询问确认
        print("\n" + "="*60)
        print("⚠️  警告：此操作将把所有URL状态改为pending")
        print("="*60)
        response = input("\n是否继续? (yes/no): ").strip().lower()
        
        if response not in ['yes', 'y', '是']:
            print("[INFO] 用户取消操作")
            client.close()
            return
        
        # 4. 更新所有URL状态
        print("\n[3] 开始更新URL状态...")
        print("[INFO] 将status改为pending，并删除处理时间戳...")
        
        result = collection.update_many(
            {},  # 匹配所有文档
            {
                '$set': {
                    'status': 'pending'
                },
                '$unset': {
                    'processing_at': '',
                    'processed_at': '',
                    'failed_at': ''
                }
            }
        )
        
        print(f"\n[OK] 更新完成!")
        print(f"  匹配文档数: {result.matched_count}")
        print(f"  修改文档数: {result.modified_count}")
        
        # 5. 验证结果
        print("\n[4] 验证更新结果...")
        
        pending_count = collection.count_documents({'status': 'pending'})
        print(f"[OK] pending状态URL数: {pending_count}")
        
        # 再次统计状态
        print(f"\n更新后状态分布:")
        for doc in collection.aggregate(pipeline):
            status = doc['_id'] if doc['_id'] else '(无状态)'
            count = doc['count']
            print(f"  {status}: {count}")
        
        client.close()
        
        print("\n" + "="*60)
        print("✅ 状态重置完成!")
        print("="*60)
        print(f"所有 {pending_count} 个URL已重置为pending状态")
        
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ssh_tunnel.stop_tunnel()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FATAL ERROR] 程序崩溃: {e}")
        import traceback
        traceback.print_exc()
        input("\n按Enter键退出...")
        sys.exit(1)

