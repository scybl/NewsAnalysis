#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从MongoDB下载所有Bloomberg URL
"""

import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
import pymongo
from urllib.parse import quote_plus

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv(os.path.join(os.path.dirname(__file__), '../../../../.env'))

def main():
    print("="*60)
    print("从MongoDB下载Bloomberg URL")
    print("="*60)
    
    try:
        # 连接MongoDB
        print("\n[1] 连接MongoDB...")
        mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
        mongo_port = int(os.getenv('MONGO_PORT', '27017'))
        mongo_user = os.getenv('MONGO_USER', '')
        mongo_password = os.getenv('MONGO_PASSWORD', '')
        mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')
        
        database_name = os.getenv('URL_QUEUE_DATABASE') or os.getenv('URL_DATABASE') or 'bloomberg_url_queue'
        collection_name = os.getenv('URL_QUEUE_COLLECTION') or os.getenv('URL_COLLECTION') or 'urls'

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
        
        print(f"[INFO] 数据库: {database_name}")
        print(f"[INFO] 集合: {collection_name}")
        
        # 下载数据
        print("\n[2] 下载URL数据...")
        print("正在查询...")
        
        # 查询所有URL文档
        url_docs = list(collection.find({}, {'_id': 0}))
        
        print(f"[OK] 查询到 {len(url_docs)} 个URL记录")
        
        # 统计状态
        status_count = {}
        for doc in url_docs:
            status = doc.get('status', 'unknown')
            status_count[status] = status_count.get(status, 0) + 1
        
        print(f"\n状态统计:")
        for status, count in sorted(status_count.items()):
            print(f"  {status}: {count}")
        
        # 保存完整数据
        print("\n[3] 保存到文件...")
        
        output_dir = 'data'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存完整文档
        output_file_full = os.path.join(output_dir, f'bloomberg_urls_full_{timestamp}.json')
        with open(output_file_full, 'w', encoding='utf-8') as f:
            json.dump(url_docs, f, ensure_ascii=False, indent=2)
        
        print(f"[OK] 完整数据已保存到: {output_file_full}")
        print(f"     文件大小: {os.path.getsize(output_file_full) / 1024:.2f} KB")
        
        # 保存纯URL列表（用于同步）
        urls_only = [doc['url'] for doc in url_docs if 'url' in doc]
        output_file_urls = os.path.join(output_dir, f'bloomberg_urls_only_{timestamp}.json')
        with open(output_file_urls, 'w', encoding='utf-8') as f:
            json.dump(urls_only, f, ensure_ascii=False, indent=2)
        
        print(f"[OK] 纯URL列表已保存到: {output_file_urls}")
        print(f"     文件大小: {os.path.getsize(output_file_urls) / 1024:.2f} KB")
        
        client.close()
        
        print("\n✅ 下载完成!")
        
    except Exception as e:
        print(f"\n[ERROR] 发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

