#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从MongoDB下载所有Bloomberg文章
"""

import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import pymongo
from urllib.parse import quote_plus
import subprocess
import time
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

class SSHTunnel:
    """SSH隧道管理类"""
    def __init__(self):
        self.process = None
        self.local_port = None
        
    def start_tunnel(self, ssh_host, ssh_port, ssh_user, ssh_key_path, 
                        remote_host, remote_port, local_port=None):
        try:
            if local_port is None:
                local_port = 27017
            
            self.local_port = local_port
            
            ssh_cmd = [
                "ssh", "-N", "-T",
                "-o", "ExitOnForwardFailure=yes",
                "-o", "ServerAliveInterval=5",
                "-o", "ServerAliveCountMax=2",
                "-o", "StrictHostKeyChecking=accept-new",
                "-i", ssh_key_path,
                "-p", str(ssh_port),
                "-L", f"127.0.0.1:{local_port}:{remote_host}:{remote_port}",
                f"{ssh_user}@{ssh_host}",
            ]
            
            print(f"启动SSH隧道: {ssh_host}:{ssh_port} -> 127.0.0.1:{local_port}")
            
            self.process = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            
            for attempt in range(10):
                time.sleep(0.5)
                if self.process.poll() is not None:
                    return False
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                try:
                    if sock.connect_ex(('127.0.0.1', local_port)) == 0:
                        sock.close()
                        print("[OK] SSH隧道建立成功")
                        return True
                except:
                    pass
            return False
        except Exception as e:
            print(f"[ERROR] SSH隧道启动失败: {e}")
            return False
    
    def stop_tunnel(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
                print("SSH隧道已关闭")
            except:
                pass

def main():
    print("="*60)
    print("从MongoDB下载Bloomberg文章")
    print("="*60)
    
    ssh_tunnel = SSHTunnel()
    
    try:
        # 连接MongoDB
        print("\n[1] 连接MongoDB...")
        
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
        
        # 文章存储数据库（与Guardian共用）
        article_db = os.getenv('MONGODB_DATABASE') or os.getenv('MONGO_DB', 'news')
        article_coll = os.getenv('MONGODB_COLLECTION') or os.getenv('MONGO_COLLECTION', 'articles')
        
        # 启动SSH隧道
        if not ssh_tunnel.start_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, remote_mongo_host, remote_mongo_port, mongo_port):
            print("[ERROR] SSH隧道启动失败")
            return
        
        # 连接MongoDB
        if mongo_user and mongo_password:
            encoded_username = quote_plus(mongo_user)
            encoded_password = quote_plus(mongo_password)
            connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/{article_db}?authSource={mongo_authsource}"
        else:
            connection_string = f"mongodb://{mongo_host}:{mongo_port}/{article_db}"
        
        client = pymongo.MongoClient(connection_string, serverSelectionTimeoutMS=8000, socketTimeoutMS=8000)
        client.admin.command('ping')
        print("[OK] MongoDB连接成功!")
        
        db = client[article_db]
        collection = db[article_coll]
        
        print(f"[INFO] 数据库: {article_db}")
        print(f"[INFO] 集合: {article_coll}")
        
        # 下载数据
        print("\n[2] 下载Bloomberg文章...")
        print("正在查询...")
        
        # 查询所有Bloomberg文章（不包含_id）
        articles = list(collection.find(
            {'publisher': 'Bloomberg'},
            {'_id': 0}
        ))
        
        print(f"[OK] 查询到 {len(articles)} 篇Bloomberg文章")
        
        # 保存到文件
        print("\n[3] 保存到文件...")
        
        output_dir = 'data'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(output_dir, f'bloomberg_from_mongodb_{timestamp}.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        
        file_size = os.path.getsize(output_file) / 1024 / 1024
        print(f"[OK] 已保存到: {output_file}")
        print(f"     文件大小: {file_size:.2f} MB")
        
        # 显示统计信息
        print("\n" + "="*60)
        print("数据统计")
        print("="*60)
        print(f"总文章数: {len(articles)}")
        
        if articles:
            # 统计日期分布
            dates = []
            for article in articles:
                if article.get('date'):
                    dates.append(article['date'])
            
            if dates:
                print(f"\n最早文章: {min(dates)}")
                print(f"最新文章: {max(dates)}")
            
            # 显示几个示例标题
            print(f"\n示例文章（前5篇）:")
            for i, article in enumerate(articles[:5], 1):
                title = article.get('title', 'N/A')[:60]
                date = article.get('date', 'N/A')[:10]
                print(f"  {i}. [{date}] {title}...")
        
        client.close()
        
        print("\n✅ 下载完成!")
        
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ssh_tunnel.stop_tunnel()

if __name__ == "__main__":
    main()

