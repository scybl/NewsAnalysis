"""
Bloomberg 终极爬虫 - 完全模拟真实浏览器HTTP/2请求
1. 从打开的Chrome获取Cookie（CDP方式）
2. 使用curl_cffi模拟完整的HTTP/2请求（包括所有Cookie和Headers）
3. 解析文章并保存到MongoDB
"""

import os
import json
import time
import random
from datetime import datetime
from typing import Dict, List, Optional
import pymongo
from pymongo.errors import DuplicateKeyError
import urllib.parse
from dotenv import load_dotenv
import subprocess
from bs4 import BeautifulSoup
import re
import hashlib

# 加载环境变量
load_dotenv()

# 导入pychrome用于CDP获取Cookie
try:
    import pychrome
    HAS_PYCHROME = True
except ImportError:
    HAS_PYCHROME = False
    print("[ERROR] pychrome未安装，无法从浏览器获取Cookie")
    print("[ERROR] 请运行: pip install pychrome")

# 导入curl_cffi用于HTTP/2请求
try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
    print("[INFO] 使用 curl_cffi 模拟真实Chrome浏览器 (HTTP/2)")
except ImportError:
    import requests
    USE_CURL_CFFI = False
    print("[WARNING] curl_cffi未安装，将使用普通requests（可能被检测）")
    print("[WARNING] 强烈建议运行: pip install curl-cffi")

class UltimateCrawler:
    def __init__(self, cookies=None):
        """
        初始化爬虫
        Args:
            cookies: 从Chrome获取的Cookie列表，如果为None则会报错
        """
        self.mongodb_client = None
        self.db_articles = None
        self.db_urls = None
        self.collection_articles = None
        self.collection_urls = None
        # SSH 隧道
        self._ssh_tunnel_proc = None
        self.cookies_dict = {}  # 简单的name:value字典
        self.cookies_full = []  # 完整的Cookie信息
        
        # 检查Cookie
        if not cookies:
            raise ValueError("必须提供Cookie参数")
        
        # 创建data和logs目录
        self.data_dir = 'data'
        self.logs_dir = 'logs'
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        
        # 主数据文件
        self.master_file = os.path.join(self.data_dir, 'bloomberg_articles.json')
        
        self.init_mongodb()
        self.set_cookies(cookies)  # 直接使用传入的Cookie
    
    def _start_ssh_tunnel(self, ssh_host, ssh_port, ssh_user, ssh_key_path, remote_host, remote_port, local_port):
        """启动SSH本地转发隧道 - 与Guardian一致，支持重试"""
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
        
        msg = f"启动SSH隧道: {ssh_host}:{ssh_port} -> 127.0.0.1:{local_port} -> {remote_host}:{remote_port}"
        print(f"[INFO] {msg}")
        
        # 启动SSH进程
        self._ssh_tunnel_proc = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT
        )
        
        # 等待隧道建立并重试检查端口
        print("[INFO] 等待SSH隧道建立...")
        
        # 多次检查端口是否可访问
        import socket
        max_retries = 10
        retry_interval = 0.5
        
        for attempt in range(max_retries):
            time.sleep(retry_interval)
            
            # 检查SSH进程是否还在运行
            poll_result = self._ssh_tunnel_proc.poll()
            if poll_result is not None:
                # 进程已退出
                stdout, _ = self._ssh_tunnel_proc.communicate()
                error_msg = f"SSH隧道启动失败！进程已退出，退出码: {poll_result}"
                print(f"[ERROR] {error_msg}")
                if stdout:
                    error_output = stdout.decode('utf-8', errors='ignore')
                    print(f"[ERROR] SSH输出:\n{error_output}")
                return False
            
            # 尝试连接端口
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                result = sock.connect_ex(('127.0.0.1', local_port))
                sock.close()
                if result == 0:
                    success_msg = f"SSH隧道端口 127.0.0.1:{local_port} 可访问 (尝试 {attempt + 1}/{max_retries})"
                    print(f"[OK] {success_msg}")
                    return True
                else:
                    if attempt < max_retries - 1:
                        print(f"[DEBUG] 端口尝试 {attempt + 1}/{max_retries}: 错误码 {result}，继续等待...")
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"[DEBUG] 端口尝试 {attempt + 1}/{max_retries}: {e}，继续等待...")
        
        # 所有重试都失败
        error_msg = f"SSH隧道端口 127.0.0.1:{local_port} 在{max_retries}次尝试后仍无法访问"
        print(f"[ERROR] {error_msg}")
        return False

    def init_mongodb(self):
        """初始化MongoDB连接（SSH隧道）"""
        try:
            # SSH 配置（从环境变量读取）
            ssh_host = os.getenv('SSH_HOST', '')
            ssh_port = int(os.getenv('SSH_PORT', '7022'))
            ssh_user = os.getenv('SSH_USER', 'tunnel')
            ssh_key_path = os.getenv('SSH_KEY_PATH', '')

            # 远程MongoDB服务器信息（SSH隧道的目标）
            remote_mongo_host = os.getenv('SSH_REMOTE_HOST', '127.0.0.1')
            remote_mongo_port = int(os.getenv('SSH_REMOTE_PORT', '27017'))

            # MongoDB配置（通过SSH隧道连接）
            mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
            mongo_port = int(os.getenv('MONGO_PORT', '27017'))
            mongo_user = os.getenv('MONGO_USER', '')
            mongo_password = os.getenv('MONGO_PASSWORD', '')
            mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')

            print(f"[INFO] SSH配置: {ssh_user}@{ssh_host}:{ssh_port}")
            print(f"[INFO] 远程MongoDB: {remote_mongo_host}:{remote_mongo_port}")
            print(f"[INFO] 本地隧道端口: {mongo_port}")

            # 启动SSH隧道
            if not self._start_ssh_tunnel(ssh_host, ssh_port, ssh_user, ssh_key_path, remote_mongo_host, remote_mongo_port, mongo_port):
                raise RuntimeError("SSH隧道启动失败")
            
            # 构建连接串（经本地隧道）
            if mongo_user and mongo_password:
                encoded_username = urllib.parse.quote_plus(mongo_user)
                encoded_password = urllib.parse.quote_plus(mongo_password)
                connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/?authSource={mongo_authsource}"
                print(f"[INFO] MongoDB连接字符串: mongodb://{mongo_user}:***@{mongo_host}:{mongo_port}/?authSource={mongo_authsource}")
            else:
                connection_string = f"mongodb://{mongo_host}:{mongo_port}/"
                print(f"[INFO] MongoDB连接字符串: mongodb://{mongo_host}:{mongo_port}/")

            self.mongodb_client = pymongo.MongoClient(connection_string, serverSelectionTimeoutMS=8000, socketTimeoutMS=8000)
            
            # 测试连接
            self.mongodb_client.admin.command('ping')
            print("[OK] MongoDB连接成功!")
            
            # 文章数据库优先使用 MONGODB_DATABASE/MONGODB_COLLECTION（与Guardian统一），兼容 ARTICLES_*/ARTICLE_*
            article_db = (
                os.getenv('MONGODB_DATABASE')
                or os.getenv('ARTICLES_DATABASE')
                or os.getenv('ARTICLE_DATABASE')
                or 'news'
            )
            article_coll = (
                os.getenv('MONGODB_COLLECTION')
                or os.getenv('ARTICLES_COLLECTION')
                or os.getenv('ARTICLE_COLLECTION')
                or 'articles'
            )
            self.db_articles = self.mongodb_client[article_db]
            self.collection_articles = self.db_articles[article_coll]
            
            # URL队列数据库（统一使用URL_QUEUE_开头的变量名，与get_url一致）
            url_db = os.getenv('URL_QUEUE_DATABASE') or os.getenv('URL_DATABASE', 'bloomberg_url_queue')
            url_coll = os.getenv('URL_QUEUE_COLLECTION') or os.getenv('URL_COLLECTION', 'urls')
            self.db_urls = self.mongodb_client[url_db]
            self.collection_urls = self.db_urls[url_coll]
            
            print(f"[INFO] 文章库: {article_db}.{article_coll}")
            print(f"[INFO] URL队列库: {url_db}.{url_coll}")
            
        except Exception as e:
            print(f"[ERROR] MongoDB连接失败: {e}")
            # 不在这里关闭SSH隧道，让程序继续运行
            raise
    
    def set_cookies(self, cookies):
        """
        设置Cookie
        Args:
            cookies: Cookie列表，每个Cookie是包含name、value等字段的字典
        """
        if not cookies:
            raise ValueError("Cookie列表不能为空")
        
        try:
            # 保存完整的Cookie信息
            self.cookies_full = cookies
            # 创建简单的name:value字典
            self.cookies_dict = {c['name']: c['value'] for c in self.cookies_full}
            
            print(f"[OK] Cookie已设置: {len(self.cookies_dict)} 个")
            print(f"[DEBUG] Cookie前5个: {list(self.cookies_dict.keys())[:5]}")
            
            # 检查关键Cookie的登录状态（更准确的登录判断）
            login_indicators = ['_pxhd', '_px2', 'session_id', 'agent_id', '_breg-uid']
            valid_login_cookies = 0
            missing_cookies = []
            
            for cookie_name in login_indicators:
                if cookie_name in self.cookies_dict:
                    value = self.cookies_dict[cookie_name]
                    if len(str(value)) > 10:  # 有效Cookie值通常较长
                        valid_login_cookies += 1
                    else:
                        missing_cookies.append(f"{cookie_name}(值太短)")
                else:
                    missing_cookies.append(f"{cookie_name}(缺失)")
            
            print(f"[DEBUG] 关键登录Cookie检查: {valid_login_cookies}/{len(login_indicators)} 个有效")
            if missing_cookies:
                print(f"[DEBUG] 缺失的Cookie: {missing_cookies}")
            
            # 根据日志分析，调整登录判断标准：
            # _breg-uid是必需的，没有它虽然能访问页面但无法获取完整文章数据
            # 1. 完全登录：5个关键Cookie都存在（登录很久）
            # 2. 未登录：缺少_breg-uid或其他关键Cookie（无法获取完整数据）
            
            if '_breg-uid' in str(missing_cookies):
                raise ValueError(f"缺少Bloomberg用户ID（_breg-uid），无法获取完整文章数据，疑似处于非登录状态")
            elif valid_login_cookies < 4:
                raise ValueError(f"关键登录Cookie不足（{valid_login_cookies}/{len(login_indicators)}个），疑似处于非登录状态")
            elif valid_login_cookies == 5:
                print(f"[INFO] 完全登录状态 - 所有关键Cookie都存在")
            else:
                print(f"[INFO] 登录状态（{valid_login_cookies}/{len(login_indicators)}个关键Cookie）")
            
            # 如果Cookie数量过少，也给出警告
            if len(self.cookies_dict) <= 64:
                print(f"[WARNING] Cookie数量较少（{len(self.cookies_dict)}个），但关键Cookie检查通过，继续执行")
                
        except Exception as e:
            print(f"[ERROR] 设置Cookie失败: {e}")
            raise
    
    def crawl_article_http2(self, article_url: str) -> Optional[Dict]:
        """使用HTTP/2完全模拟真实浏览器请求"""
        print(f"\n{'='*80}")
        print(f"[INFO] 开始爬取: {article_url}")
        print('='*80)
        
        print(f"[DEBUG] 当前Cookie字典大小: {len(self.cookies_dict)}")
        print(f"[DEBUG] 当前完整Cookie数组大小: {len(self.cookies_full)}")
        
        # 详细记录Cookie信息
        print(f"[DEBUG] Cookie详细信息:")
        print(f"  - 字典Cookie数量: {len(self.cookies_dict)}")
        print(f"  - 完整Cookie数量: {len(self.cookies_full)}")
        print(f"  - 前5个Cookie名称: {list(self.cookies_dict.keys())[:5]}")
        
        # 记录Cookie域名分布
        domains = {}
        for cookie in self.cookies_full:
            domain = cookie.get('domain', 'unknown')
            domains[domain] = domains.get(domain, 0) + 1
        print(f"  - Cookie域名分布: {domains}")
        
        # 检查关键Cookie的值（判断是否真正登录）
        print(f"  - 关键Cookie登录状态检查:")
        
        # 根据日志分析，真正的登录状态判断标准：
        # 1. 完全登录：所有5个关键Cookie都存在且有效
        # 2. 部分登录：缺少_breg-uid但其他4个存在（刚刷新过）
        # 3. 未登录：关键Cookie缺失或数量不足
        
        login_indicators = {
            '_pxhd': 'PerimeterX设备指纹',
            '_px2': 'PerimeterX会话ID', 
            'session_id': 'Bloomberg会话ID',
            'agent_id': 'Bloomberg代理ID',
            '_breg-uid': 'Bloomberg用户ID'
        }
        
        login_score = 0
        total_checks = len(login_indicators)
        missing_cookies = []
        
        for cookie_name, description in login_indicators.items():
            if cookie_name in self.cookies_dict:
                value = self.cookies_dict[cookie_name]
                value_length = len(str(value))
                # 检查值是否为空或过短
                if value_length > 10:  # 有效Cookie值通常较长
                    print(f"    ✅ {cookie_name}: {value[:20]}... ({value_length}字符) - {description}")
                    login_score += 1
                else:
                    print(f"    ❌ {cookie_name}: {value} ({value_length}字符) - 值太短 - {description}")
                    missing_cookies.append(cookie_name)
            else:
                print(f"    ❌ {cookie_name}: 缺失 - {description}")
                missing_cookies.append(cookie_name)
        
        login_percentage = (login_score / total_checks) * 100
        print(f"  - 登录状态评分: {login_score}/{total_checks} ({login_percentage:.1f}%)")
        
        # 更精确的登录状态判断
        if login_score == 5:
            print(f"  ✅ 完全登录状态 - 所有关键Cookie都存在")
        elif '_breg-uid' in missing_cookies:
            print(f"  ❌ 未登录状态 - 缺少Bloomberg用户ID，无法获取完整文章数据")
            print("[ERROR] 缺少关键登录Cookie，停止爬取")
            return None
        elif login_score >= 4:
            print(f"  ✅ 登录状态 - 关键Cookie基本完整")
        elif login_score >= 3:
            print(f"  ⚠️  登录状态不完整 - 缺少关键Cookie: {missing_cookies}")
        else:
            print(f"  ❌ 未登录状态 - 关键Cookie严重缺失: {missing_cookies}")
            print("[ERROR] 关键Cookie严重缺失，停止爬取")
            return None
        
        if not self.cookies_dict:
            print("[ERROR] 没有Cookie，无法继续")
            print("[DEBUG] self.cookies_dict为空！")
            return None
        
        try:
            # 创建会话
            print(f"[DEBUG] 创建requests.Session...")
            session = requests.Session()
            session.cookies.update(self.cookies_dict)
            
            print(f"[INFO] Cookie数量: {len(self.cookies_dict)} 个")
            print(f"[DEBUG] 前5个Cookie名称: {list(self.cookies_dict.keys())[:5]}")
            
            # 记录实际使用的Cookie
            print(f"[DEBUG] 实际使用的Cookie详情:")
            print(f"  - Session Cookie数量: {len(session.cookies)}")
            print(f"  - Session Cookie名称: {list(session.cookies.keys())[:5]}")
            
            # 检查Cookie值长度（判断是否为空）
            cookie_values_length = []
            for name, value in list(session.cookies.items())[:3]:
                cookie_values_length.append(f"{name}:{len(str(value))}字符")
            print(f"  - 前3个Cookie值长度: {cookie_values_length}")
            
            # 构建完全符合Wireshark抓包的Headers
            # 注意：HTTP/2的伪头部(:method, :authority等)会由curl_cffi自动处理
            headers = {
                # 标准headers（按照你抓包的顺序）
                'cache-control': 'max-age=0',
                'sec-ch-ua': '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-user': '?1',
                'sec-fetch-dest': 'document',
                'accept-encoding': 'gzip, deflate, br, zstd',
                'accept-language': 'zh-CN,zh;q=0.9',
                # 注意：Cookie会自动从session.cookies中添加
                # 注意：if-none-match会根据需要添加（缓存控制）
                'priority': 'u=0, i',
            }
            
            print("[INFO] 使用HTTP/2 Headers（完全模拟真实浏览器）")
            
            # curl_cffi的关键参数
            extra_params = {}
            if USE_CURL_CFFI:
                # 模拟Chrome 120（与抓包的Chrome 141最接近）
                extra_params['impersonate'] = 'chrome120'
                print("[INFO] curl_cffi模拟: Chrome 120 (HTTP/2 + TLS 1.3)")
                print("[INFO] 自动特性: HTTP/2伪头部、正确的Header顺序、JA3指纹")
            else:
                print("[WARNING] 使用HTTP/1.1（不如HTTP/2）")
            
            # 模拟真实用户行为：先访问首页建立session
            print("\n[STEP 1] 建立Session - 访问首页...")
            try:
                home_url = 'https://www.bloomberg.com/asia'
                headers_home = headers.copy()
                headers_home['sec-fetch-site'] = 'none'  # 首次访问
                
                response_home = session.get(
                    home_url, 
                    headers=headers_home, 
                    timeout=30, 
                    **extra_params
                )
                print(f"  状态码: {response_home.status_code}")
                
                # 随机延迟（模拟人类浏览）
                delay = random.uniform(2, 4)
                print(f"  等待 {delay:.1f} 秒...")
                time.sleep(delay)
            except Exception as e:
                print(f"  [WARNING] 首页访问失败: {e}")
            
            # 访问目标文章
            print(f"\n[STEP 2] 访问文章页面...")
            headers_article = headers.copy()
            headers_article['referer'] = 'https://www.bloomberg.com/asia'
            
            start_time = time.time()
            response = session.get(
                article_url,
                headers=headers_article,
                timeout=30,
                **extra_params
            )
            response_time = int((time.time() - start_time) * 1000)
            
            print(f"  状态码: {response.status_code}")
            print(f"  响应时间: {response_time} ms")
            print(f"  响应大小: {len(response.content)} 字节 ({len(response.content)/1024:.2f} KB)")
            print(f"  Content-Encoding: {response.headers.get('Content-Encoding', 'none')}")
            print(f"  Content-Type: {response.headers.get('Content-Type', 'unknown')}")
            
            print(f"[DEBUG] 响应接收完成")
            print(f"[DEBUG] 状态码: {response.status_code}")
            print(f"[DEBUG] Content-Type: {response.headers.get('Content-Type', 'N/A')}")
            
            # 保存响应HTML到本地
            html_content = response.text
            print(f"[DEBUG] HTML内容长度: {len(html_content)} 字符")
            
            if response.status_code != 200:
                print(f"[ERROR] 请求失败: {response.status_code}")
                
                # 检测反爬虫
                if response.status_code == 403:
                    self._check_anti_bot(html_content)
                
                return None
            
            # 解析文章
            print(f"\n[STEP 3] 解析文章...")
            print(f"  [DEBUG] 准备解析HTML（{len(html_content)} 字符）")
            
            article_data = self._parse_article(html_content, article_url, response_time)
            
            if article_data:
                print(f"[OK] 解析成功: {article_data.get('title', 'N/A')[:50]}...")
                
                return article_data
            else:
                print("[ERROR] 解析失败")
                print("[DEBUG] article_data为None，解析过程出错")
                return None
                
        except Exception as e:
            print(f"[ERROR] 爬取失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _check_anti_bot(self, html_content: str):
        """检测反爬虫系统"""
        print("\n[反爬虫分析]")
        html_lower = html_content.lower()
        
        checks = [
            ('PerimeterX', 'perimeterx' in html_lower),
            ('CAPTCHA', 'captcha' in html_lower),
            ('机器人验证', 'robot' in html_lower or 'are you a robot' in html_lower),
            ('Cloudflare', 'cloudflare' in html_lower),
            ('访问被拒绝', 'access denied' in html_lower or 'forbidden' in html_lower),
        ]
        
        for name, detected in checks:
            status = '❌ 检测到' if detected else '✅ 未检测到'
            print(f"  {name:20s}: {status}")
    
    def _parse_article(self, html_content: str, url: str, response_time: int = 0) -> Optional[Dict]:
        """解析文章内容（完全匹配get_article的格式）"""
        print(f"  [INFO] 解析HTML内容（{len(html_content)} 字符）...")
        
        # 提取JSON数据
        print(f"  [INFO] 查找__NEXT_DATA__标签...")
        print(f"  [DEBUG] 使用正则表达式查找...")
        
        json_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">\s*(\{.*?\})\s*</script>', 
                              html_content, re.DOTALL)
        
        if not json_match:
            print("  [ERROR] 未找到__NEXT_DATA__标签")
            print(f"  [DEBUG] HTML前500字符: {html_content[:500]}")
            print(f"  [DEBUG] 检查HTML中是否包含'__NEXT_DATA__': {'__NEXT_DATA__' in html_content}")
            print(f"  [DEBUG] 检查HTML中是否包含'<script': {'<script' in html_content}")
            return None
        
        print(f"  [OK] 找到__NEXT_DATA__，JSON长度: {len(json_match.group(1))} 字符")
        
        try:
            print(f"  [INFO] 解析JSON数据...")
            print(f"  [DEBUG] JSON前100字符: {json_match.group(1)[:100]}")
            
            next_data = json.loads(json_match.group(1))
            print(f"  [DEBUG] JSON解析成功，类型: {type(next_data)}")
            
            print(f"  [INFO] 提取story数据...")
            print(f"  [DEBUG] next_data keys: {list(next_data.keys())[:5]}")
            
            story_data = next_data['props']['pageProps']['story']
            print(f"  [DEBUG] story_data keys: {list(story_data.keys())[:10]}")
            
            print(f"  [INFO] 文章标题: {story_data.get('headline', 'N/A')[:80]}")
            
            # 基本信息
            title = story_data.get('headline', '')
            authors = story_data.get('authors', [])
            author = authors[0].get('name', '') if authors else ''
            
            # 标签和分类
            content_tags = story_data.get('contentTags', [])
            tags = [tag.get('name', '') for tag in content_tags if tag.get('name')]
            
            categories = []
            ad_targeting = story_data.get('adTargeting', {})
            sites = ad_targeting.get('sites', '')
            if sites:
                categories = [site.strip() for site in sites.split(',')]
            
            # 正文
            document_content = self._extract_content(story_data)
            
            # 构建标准格式（完全匹配get_article）
            article = {
                "url": url,
                "title": title,
                "publisher": "Bloomberg",
                "author": author,
                "date": story_data.get('publishedAt', ''),
                "fetch_date": datetime.now().isoformat() + 'Z',
                "language": story_data.get('language', 'en'),
                "location": "",
                "source_section": f"bloomberg/{story_data.get('pillar', 'None')}/article",
                "description": story_data.get('summaryText', ''),
                "headline": title,
                "trailText": "",
                "tags": tags,
                "entities": {"persons": [], "organizations": [], "locations": []},
                "categories": categories,
                "document": {
                    "title": title,
                    "content": document_content,
                    "raw_html": html_content
                },
                "crawler_meta": {
                    "status_code": 200,
                    "response_time_ms": response_time,
                    "raw_html_length": len(html_content),
                    "hash": hashlib.md5(html_content.encode()).hexdigest()
                },
                "mongodb_meta": {
                    "inserted_at": datetime.now().isoformat() + 'Z',
                    "version": "1.0"
                }
            }
            
            print(f"  [OK] 解析成功: {title[:50]}...")
            print(f"  作者: {author}, 标签: {len(tags)}, 段落: {len(document_content)}")
            return article
            
        except Exception as e:
            print(f"  [ERROR] 解析失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_content(self, story_data: Dict) -> List[Dict]:
        """提取正文内容（与get_article相同的逻辑）"""
        content_sections = []
        body = story_data.get('body', {})
        
        if 'content' in body:
            current_section = {"subtitle": "Introduction", "text": ""}
            
            for item in body['content']:
                item_type = item.get('type', '')
                
                if item_type == 'paragraph':
                    text = self._extract_text(item)
                    if text.strip():
                        if current_section["text"]:
                            current_section["text"] += " " + text
                        else:
                            current_section["text"] = text
                
                elif item_type == 'heading':
                    if current_section["text"].strip():
                        content_sections.append(current_section.copy())
                    
                    heading_text = self._extract_text(item)
                    current_section = {
                        "subtitle": heading_text if heading_text else "Section",
                        "text": ""
                    }
            
            if current_section["text"].strip():
                content_sections.append(current_section)
        
        return content_sections
    
    def _extract_text(self, item: Dict) -> str:
        """提取文本（与get_article相同的逻辑）"""
        text_parts = []
        
        if 'content' in item:
            for content_item in item['content']:
                if content_item.get('type') == 'text':
                    text_parts.append(content_item.get('value', ''))
                elif content_item.get('type') == 'link':
                    link_content = content_item.get('content', [])
                    for link_item in link_content:
                        if link_item.get('type') == 'text':
                            text_parts.append(link_item.get('value', ''))
                elif content_item.get('type') == 'entity':
                    # 处理entity类型（人名、机构等）
                    entity_content = content_item.get('content', [])
                    for entity_item in entity_content:
                        if entity_item.get('type') == 'text':
                            text_parts.append(entity_item.get('value', ''))
        
        return ' '.join(text_parts)
    
    def save_article_to_mongodb(self, article_data: Dict) -> bool:
        """保存文章到MongoDB"""
        if not article_data:
            print("[ERROR] article_data为空，无法保存")
            return False
        
        try:
            print(f"\n[STEP 4] 保存文章到MongoDB...")
            print(f"  [DEBUG] 数据库: {self.collection_articles.database.name}")
            print(f"  [DEBUG] 集合: {self.collection_articles.name}")
            print(f"  [DEBUG] 文章URL: {article_data.get('url', 'N/A')}")
            print(f"  [DEBUG] 文章标题: {article_data.get('title', 'N/A')[:50]}...")
            
            # 打印article_data的主要字段
            print(f"  [DEBUG] 数据字段:")
            print(f"    - title: {article_data.get('title', 'N/A')[:30]}...")
            print(f"    - author: {article_data.get('author', 'N/A')}")
            print(f"    - date: {article_data.get('date', 'N/A')}")
            print(f"    - tags: {len(article_data.get('tags', []))} 个")
            print(f"    - document.content: {len(article_data.get('document', {}).get('content', []))} 段")
            
            # 使用upsert避免重复（通过URL判断）
            print(f"  [DEBUG] 执行MongoDB update_one操作...")
            result = self.collection_articles.update_one(
                {'url': article_data['url']},
                {'$set': article_data},
                upsert=True
            )
            
            print(f"  [DEBUG] MongoDB操作结果:")
            print(f"    - matched_count: {result.matched_count}")
            print(f"    - modified_count: {result.modified_count}")
            print(f"    - upserted_id: {result.upserted_id}")
            
            if result.upserted_id:
                print(f"  [OK] 新文章已保存，ID: {result.upserted_id}")
                return True
            elif result.matched_count > 0:
                print(f"  [OK] 文章已更新（原有文档被替换）")
                return True
            else:
                print(f"  [WARNING] 操作完成但无匹配或插入")
                return False
            
        except DuplicateKeyError as e:
            print(f"  [ERROR] MongoDB重复键错误: {e}")
            print(f"  [DEBUG] URL: {article_data.get('url', '')}")
            return False
        except Exception as e:
            print(f"  [ERROR] 保存失败: {e}")
            print(f"  [DEBUG] 异常类型: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            return False
    
    def mark_url_processed(self, url: str, success: bool = True):
        """标记URL为已处理"""
        if self.collection_urls is None:
            return
        
        status = 'processed' if success else 'failed'
        try:
            self.collection_urls.update_one(
                {'url': url},
                {'$set': {
                    'status': status,
                    'processed_at': datetime.now().isoformat() + 'Z'
                }}
            )
        except Exception as e:
            print(f"[WARNING] 标记URL失败: {e}")
    
    def mark_url_processing(self, url: str):
        """标记URL为处理中"""
        if self.collection_urls is None:
            return
        
        try:
            self.collection_urls.update_one(
                {'url': url},
                {'$set': {
                    'status': 'processing',
                    'processing_at': datetime.now().isoformat() + 'Z'
                }}
            )
        except Exception as e:
            print(f"[WARNING] 标记URL失败: {e}")
    
    def batch_crawl(self):
        """批量爬取文章（完全按照get_article的流程）"""
        # 从环境变量读取配置
        batch_size = int(os.getenv('BATCH_SIZE', '10'))
        delay_min = int(os.getenv('ARTICLE_DELAY_MIN', '60'))
        delay_max = int(os.getenv('ARTICLE_DELAY_MAX', '120'))
        
        print("=" * 60)
        print("Bloomberg 文章爬取器")
        print("=" * 60)
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print(f"[CONFIG] 批量大小: {batch_size}")
        print(f"[CONFIG] 延迟范围: {delay_min}-{delay_max} 秒")
        print()
        
        # 获取待处理的URL文档
        print("[STEP 1] 获取待处理URL...")
        try:
            url_docs = list(self.collection_urls.find(
                {'status': 'pending'},
                {'url': 1, '_id': 0}
            ).limit(batch_size))
            
            print(f"数据库查询（状态=pending）:")
        except Exception as e:
            print(f"[ERROR] 获取URL失败: {e}")
            return
        
        if not url_docs:
            print("[INFO] 没有待处理的URL")
            return
        
        print(f"[OK] 获取到 {len(url_docs)} 个待处理URL")
        print(f"\n[STEP 2] 开始批量爬取 {len(url_docs)} 篇文章")
        print(f"每篇间隔: {delay_min}-{delay_max} 秒\n")
        
        success_count = 0
        fail_count = 0
        success_articles = []  # 成功爬取的文章列表
        failed_urls = []  # 失败的URL列表
        
        for i, url_doc in enumerate(url_docs, 1):
            url = url_doc['url']
            
            print(f"\n{'='*60}")
            print(f"[{i}/{len(url_docs)}] 处理URL: {url}")
            print(f"{'='*60}")
            
            # 每篇文章前重新获取Cookie
            print(f"[INFO] 从Chrome刷新Cookie...")
            try:
                if not self.refresh_cookies_from_chrome():
                    print(f"[WARNING] Cookie刷新失败，使用上次的Cookie继续")
            except ValueError as e:
                # Cookie数量不足，记录warning日志并终止
                print(f"\n[ERROR] ❌ {e}")
                print("[ERROR] 批量爬取终止")
                
                log_dir = os.path.join(os.path.dirname(__file__), 'logs')
                warning_log_file = os.path.join(log_dir, f"warning_bloomberg_article_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
                
                with open(warning_log_file, 'w', encoding='utf-8') as wf:
                    wf.write(f"[WARNING] Bloomberg爬虫Cookie检查失败\n")
                    wf.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    wf.write(f"位置: 批量爬取第{i}篇文章时\n")
                    wf.write(f"URL: {url}\n")
                    wf.write(f"错误: {e}\n")
                    wf.write(f"状态: 疑似处于非登录状态\n")
                    wf.write(f"建议: 请检查Chrome是否已正确登录Bloomberg账户\n")
                    wf.write(f"\n已完成: {success_count}/{i-1} 篇\n")
                    wf.write(f"已失败: {fail_count}/{i-1} 篇\n")
                
                print(f"[WARNING] 警告日志已保存到: {warning_log_file}")
                break  # 终止循环
            
            # 标记为处理中
            print(f"[INFO] 标记为处理中...")
            self.mark_url_processing(url)
            
            # 爬取文章
            print(f"[INFO] 开始爬取文章...")
            article = self.crawl_article_http2(url)
            
            if article:
                print(f"[OK] 文章爬取成功")
                # 保存文章
                print(f"[INFO] 保存文章到MongoDB...")
                if self.save_article_to_mongodb(article):
                    success_count += 1
                    success_articles.append(article)  # 添加到成功列表
                    print(f"[OK] 文章保存成功")
                    self.mark_url_processed(url, success=True)
                else:
                    fail_count += 1
                    failed_urls.append({'url': url, 'reason': '保存失败'})
                    print(f"[ERROR] 文章保存失败")
                    self.mark_url_processed(url, success=False)
            else:
                fail_count += 1
                failed_urls.append({'url': url, 'reason': '爬取失败'})
                print(f"[ERROR] 文章爬取失败")
                self.mark_url_processed(url, success=False)
            
            # 间隔延迟
            if i < len(url_docs):
                delay = random.uniform(delay_min, delay_max)
                print(f"[INFO] 等待 {delay:.1f} 秒后继续下一篇...\n")
                time.sleep(delay)
        
        print("\n" + "=" * 60)
        print("批量爬取完成")
        print(f"成功: {success_count}/{len(url_docs)} 篇")
        print(f"失败: {fail_count}/{len(url_docs)} 篇")
        print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        # 保存到JSON文件
        if success_articles:
            self._save_articles_to_json(success_articles)
        
        # 记录失败的URL
        if failed_urls:
            print(f"\n[WARNING] 以下 {len(failed_urls)} 个URL爬取失败:")
            for failed in failed_urls:
                print(f"  - {failed['url']} ({failed['reason']})")
    
    def _save_articles_to_json(self, articles):
        """保存文章到JSON文件（主文件+增量文件）"""
        try:
            import json
            
            # 读取现有主文件
            all_articles = []
            if os.path.exists(self.master_file):
                try:
                    with open(self.master_file, 'r', encoding='utf-8') as f:
                        all_articles = json.load(f)
                    print(f"[INFO] 读取现有主文件: {len(all_articles)} 篇文章")
                except Exception as e:
                    print(f"[WARNING] 读取主文件失败: {e}")
            
            # 去重：基于URL
            existing_urls = {article.get('url') for article in all_articles if article.get('url')}
            new_articles = [article for article in articles if article.get('url') not in existing_urls]
            
            if new_articles:
                # 保存增量文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                increment_file = os.path.join(self.data_dir, f'bloomberg_articles_new_{timestamp}.json')
                with open(increment_file, 'w', encoding='utf-8') as f:
                    json.dump(new_articles, f, ensure_ascii=False, indent=2)
                print(f"[OK] 增量文件已保存: {increment_file} ({len(new_articles)} 篇新文章)")
                
                # 更新主文件
                all_articles.extend(new_articles)
                with open(self.master_file, 'w', encoding='utf-8') as f:
                    json.dump(all_articles, f, ensure_ascii=False, indent=2)
                print(f"[OK] 主文件已更新: {self.master_file} (总计 {len(all_articles)} 篇)")
            else:
                print(f"[INFO] 没有新文章需要保存（所有文章已存在于主文件中）")
                
        except Exception as e:
            print(f"[ERROR] 保存JSON文件失败: {e}")
            import traceback
            traceback.print_exc()
    
    def refresh_cookies_from_chrome(self):
        """从Chrome重新获取Cookie"""
        try:
            import pychrome
            print(f"[DEBUG] 连接Chrome调试端口9222...")
            browser = pychrome.Browser(url="http://127.0.0.1:9222")
            tabs = browser.list_tab()
            
            if not tabs:
                raise Exception("Chrome未找到标签页")
            
            print(f"[DEBUG] 找到 {len(tabs)} 个标签页，使用第一个")
            tab = tabs[0]
            tab.start()
            
            print(f"[DEBUG] 调用Network.getAllCookies...")
            result = tab.call_method("Network.getAllCookies", _timeout=5)
            all_cookies = result.get('cookies', [])
            print(f"[DEBUG] 从Chrome获取到原始Cookie总数: {len(all_cookies)} 个")
            
            # 筛选Bloomberg Cookie
            bloomberg_cookies = [c for c in all_cookies if 'bloomberg.com' in c.get('domain', '')]
            print(f"[DEBUG] 筛选出Bloomberg Cookie: {len(bloomberg_cookies)} 个")
            
            # 打印Cookie域名分布
            domains = {}
            for cookie in bloomberg_cookies:
                domain = cookie.get('domain', 'unknown')
                domains[domain] = domains.get(domain, 0) + 1
            print(f"[DEBUG] Cookie域名分布: {domains}")
            
            # 打印前5个Cookie名称
            cookie_names = [c.get('name', 'unnamed') for c in bloomberg_cookies[:5]]
            print(f"[DEBUG] 前5个Cookie名称: {cookie_names}")
            
            tab.stop()
            
            if not bloomberg_cookies:
                raise Exception("未获取到Bloomberg Cookie")
            
            # 更新Cookie（会自动检查数量，如果<=64会抛出异常）
            print(f"[DEBUG] 开始设置Cookie...")
            self.set_cookies(bloomberg_cookies)
            print(f"[OK] ✅ 已刷新Cookie: {len(self.cookies_dict)} 个")
            return True
            
        except ValueError as e:
            # Cookie数量检查失败
            print(f"[ERROR] ❌ Cookie刷新失败: {e}")
            raise  # 重新抛出异常，让上层处理
        except Exception as e:
            print(f"[WARNING] Cookie刷新失败: {e}")
            return False
    
    def close(self):
        """关闭MongoDB连接"""
        if self.mongodb_client:
            self.mongodb_client.close()
            print("\n[INFO] MongoDB连接已关闭")
        # 关闭SSH隧道
        try:
            if self._ssh_tunnel_proc and self._ssh_tunnel_proc.poll() is None:
                self._ssh_tunnel_proc.terminate()
                time.sleep(0.5)
                if self._ssh_tunnel_proc.poll() is None:
                    self._ssh_tunnel_proc.kill()
                print("[INFO] SSH隧道已关闭")
        except Exception:
            pass

def main():
    """主函数"""
    import sys
    from datetime import datetime
    
    # 设置日志文件
    log_dir = os.path.join(os.path.dirname(__file__), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"bloomberg_article_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    
    # 同时输出到控制台和文件
    class TeeOutput:
        def __init__(self, *files):
            self.files = files
        def write(self, data):
            for f in self.files:
                f.write(data)
                f.flush()
        def flush(self):
            for f in self.files:
                f.flush()
    
    log_f = open(log_file, 'w', encoding='utf-8')
    sys.stdout = TeeOutput(sys.stdout, log_f)
    sys.stderr = TeeOutput(sys.stderr, log_f)
    
    print(f"[INFO] 日志文件: {log_file}")
    
    # 步骤1: 从Chrome获取Cookie
    print("\n[重要] 确保Chrome以调试模式运行:")
    print("  chrome.exe --remote-debugging-port=9222")
    print("  并已登录Bloomberg账户")
    
    bloomberg_cookies = None
    
    # 尝试获取Cookie
    try:
        import pychrome
        browser = pychrome.Browser(url="http://127.0.0.1:9222")
        tabs = browser.list_tab()
        
        if not tabs:
            raise Exception("Chrome未找到标签页，请确保Chrome正在运行")
        
        tab = tabs[0]
        tab.start()
        result = tab.call_method("Network.getAllCookies", _timeout=5)
        all_cookies = result.get('cookies', [])
        bloomberg_cookies = [c for c in all_cookies if 'bloomberg.com' in c.get('domain', '')]
        tab.stop()
        
        if not bloomberg_cookies:
            raise Exception("未获取到Bloomberg Cookie，请确保已登录Bloomberg")
        
        print(f"[OK] ✅ 从Chrome获取到 {len(bloomberg_cookies)} 个Bloomberg Cookie")
        print(f"[INFO] Cookie域名列表: {set(c.get('domain', '') for c in bloomberg_cookies)}")
        print()
        
    except Exception as e:
        print(f"[ERROR] ❌ 从Chrome获取Cookie失败: {e}")
        print("[ERROR] 无法继续，程序退出")
        print(f"[ERROR] 错误详情已记录到日志文件: {log_file}")
        log_f.close()
        sys.exit(1)
    
    # 步骤2: 创建爬虫并开始批量爬取（直接传入Cookie）
    try:
        crawler = UltimateCrawler(cookies=bloomberg_cookies)
    except ValueError as e:
        # 捕获Cookie数量检查异常
        if "Cookie数量过少" in str(e) or "疑似处于非登录状态" in str(e):
            warning_log_file = os.path.join(log_dir, f"warning_bloomberg_article_crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            print(f"\n[ERROR] ❌ {e}")
            print("[ERROR] 无法继续，程序退出")
            print(f"[ERROR] 错误详情已记录到日志文件: {log_file}")
            print(f"[WARNING] 警告日志已保存到: {warning_log_file}")
            
            # 创建warning日志文件
            with open(warning_log_file, 'w', encoding='utf-8') as wf:
                wf.write(f"[WARNING] Bloomberg爬虫Cookie检查失败\n")
                wf.write(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                wf.write(f"错误: {e}\n")
                wf.write(f"状态: 疑似处于非登录状态\n")
                wf.write(f"建议: 请检查Chrome是否已正确登录Bloomberg账户\n")
            
            log_f.close()
            sys.exit(1)
        else:
            # 其他ValueError异常
            print(f"\n[ERROR] 初始化失败: {e}")
            log_f.close()
            sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        log_f.close()
        sys.exit(1)
    
    try:
        crawler.batch_crawl()
    except KeyboardInterrupt:
        print("\n\n[WARNING] 用户中断")
    except Exception as e:
        print(f"\n[ERROR] 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        crawler.close()
        log_f.close()
        print(f"\n[INFO] 日志已保存到: {log_file}")

if __name__ == "__main__":
    main()
