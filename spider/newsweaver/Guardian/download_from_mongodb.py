#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从MongoDB下载所有Guardian文章
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

load_dotenv()

class SSHTunnel:
    """SSH隧道管理类"""
    def __init__(self):
        self.process = None
        self.local_port = None
        
    def start_tunnel(self, ssh_host, ssh_port, ssh_user, ssh_key_path, 
                        remote_host, remote_port, local_port=None):
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
            
            print(f"启动SSH隧道: {ssh_host}:{ssh_port} -> 127.0.0.1:{local_port}")
            
            self.process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
            
            import socket
            max_retries = 10
            retry_interval = 0.5
            
            for attempt in range(max_retries):
                time.sleep(retry_interval)
                
                poll_result = self.process.poll()
                if poll_result is not None:
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
            print(f"[ERROR] SSH隧道启动失败: {e}")
            return False
    
    def stop_tunnel(self):
        """停止SSH隧道"""
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                time.sleep(0.5)
                if self.process.poll() is None:
                    self.process.kill()
                print("SSH隧道已关闭")
            except Exception as e:
                print(f"关闭SSH隧道时出错: {e}")

def main():
    print("="*60)
    print("从MongoDB下载Guardian文章")
    print("="*60)
    
    ssh_tunnel = SSHTunnel()
    
    try:
        # 连接MongoDB
        print("\n[1] 连接MongoDB...")
        
        # SSH配置
        ssh_host = os.getenv('SSH_HOST', '')
        ssh_port = int(os.getenv('SSH_PORT', '7022'))
        ssh_user = os.getenv('SSH_USER', 'tunnel')
        ssh_key_path = os.getenv('SSH_KEY_PATH', '')
        
        remote_mongo_host = os.getenv('SSH_REMOTE_HOST', '127.0.0.1')
        remote_mongo_port = int(os.getenv('SSH_REMOTE_PORT', '27017'))
        
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', '27017'))
        mongo_db = os.getenv('MONGO_DB', 'news')
        mongo_collection = os.getenv('MONGO_COLLECTION', 'articles')
        mongo_user = os.getenv('MONGO_USER', '')
        mongo_password = os.getenv('MONGO_PASSWORD', '')
        mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')
        
        # 启动SSH隧道
        tunnel_success = ssh_tunnel.start_tunnel(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            ssh_key_path=ssh_key_path,
            remote_host=remote_mongo_host,
            remote_port=remote_mongo_port,
            local_port=mongo_port
        )
        
        if not tunnel_success:
            print("[ERROR] SSH隧道启动失败")
            return
        
        # 连接MongoDB
        if mongo_user and mongo_password:
            encoded_username = quote_plus(mongo_user)
            encoded_password = quote_plus(mongo_password)
            connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/{mongo_db}?authSource={mongo_authsource}"
        else:
            connection_string = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
        
        client = pymongo.MongoClient(
            connection_string,
            serverSelectionTimeoutMS=8000,
            socketTimeoutMS=8000
        )
        
        client.admin.command('ping')
        print("[OK] MongoDB连接成功!")
        
        db = client[mongo_db]
        collection = db[mongo_collection]
        
        # 下载数据
        print("\n[2] 下载Guardian文章...")
        print("正在查询...")
        
        # 查询所有Guardian文章（不包含_id）
        articles = list(collection.find(
            {'publisher': 'The Guardian'},
            {'_id': 0}  # 排除_id字段
        ))
        
        print(f"[OK] 查询到 {len(articles)} 篇Guardian文章")
        
        # 保存到文件
        print("\n[3] 保存到文件...")
        
        output_dir = 'data'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = os.path.join(output_dir, f'guardian_from_mongodb_{timestamp}.json')
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        
        file_size = os.path.getsize(output_file) / 1024 / 1024
        print(f"[OK] 已保存到: {output_file}")
        print(f"文件大小: {file_size:.2f} MB")
        
        # 显示一些统计信息
        print("\n" + "="*60)
        print("数据统计")
        print("="*60)
        print(f"总文章数: {len(articles)}")
        
        if articles:
            # 按section统计
            sections = {}
            dates = []
            for article in articles:
                section = article.get('source_section', '未知')
                sections[section] = sections.get(section, 0) + 1
                if article.get('date'):
                    dates.append(article['date'])
            
            print(f"\n版块分布（前10名）:")
            for section, count in sorted(sections.items(), key=lambda x: x[1], reverse=True)[:10]:
                print(f"  {section}: {count} 篇")
            
            if dates:
                print(f"\n最早文章: {min(dates)}")
                print(f"最新文章: {max(dates)}")
        
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

