"""
Bloomberg URL获取器 - 全自动版本

功能：
1. 自动启动Chrome浏览器（如果未运行）
2. 从Chrome获取Cookie（CDP协议）
3. 使用真实Cookie + curl_cffi模拟浏览器
4. 从/latest页面的__NEXT_DATA__提取URL（结构化JSON数据）
5. 保存到MongoDB（自动去重）

端口配置（避免冲突）：
- 默认: 9225（避开finalarticle的9222）
- 自定义: 设置环境变量 CHROME_DEBUG_PORT

使用方法：
直接运行即可！
  python bloomberg_url_fetcher.py

如果需要登录Bloomberg，会自动打开Chrome窗口，手动登录后脚本会继续执行。

快捷方式方式（可选）：
创建Chrome快捷方式，目标改为：
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9225 --user-data-dir="%USERPROFILE%\chrome-geturl-9225" --remote-allow-origins=*
"""

# 尝试导入curl_cffi以模拟真实Chrome
try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
    print("[INFO] 使用 curl_cffi 模拟真实Chrome浏览器")
except ImportError:
    import requests
    USE_CURL_CFFI = False
    print("[WARNING] curl_cffi未安装，使用requests（可能被检测）")
    print("[WARNING] 建议运行: pip install curl-cffi")

import json
import time
import random
import subprocess
from datetime import datetime
from typing import List, Dict, Optional
import pymongo
from pymongo.errors import DuplicateKeyError
import urllib.parse
import os
from dotenv import load_dotenv
import logging
import signal
import sys

try:
    import pychrome
    HAS_PYCHROME = True
except ImportError:
    pychrome = None
    HAS_PYCHROME = False

load_dotenv(os.path.join(os.path.dirname(__file__), '../../../../.env'))

SPIDER_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if SPIDER_ROOT not in sys.path:
    sys.path.insert(0, SPIDER_ROOT)

from news_schema import canonicalize_url

# 设置日志
# 日志将在初始化时配置到logs目录

class BloombergURLFetcher:
    def __init__(self):
        self.mongodb_client = None
        self.db = None
        self.collection = None
        self.proxy_url = os.getenv('PROXY_URL', '').strip() or None
        if not self.proxy_url:
            # 兼容拆分式代理配置：PROXY_HOST/PROXY_PORT/PROXY_USERNAME/PROXY_PASSWORD
            proxy_host = (os.getenv('PROXY_HOST') or os.getenv('PROXY_SERVER') or '').strip()
            proxy_port = (os.getenv('PROXY_PORT') or '').strip()
            proxy_user = (os.getenv('PROXY_USERNAME') or '').strip()
            proxy_pass = (os.getenv('PROXY_PASSWORD') or '').strip()
            proxy_scheme = (os.getenv('PROXY_SCHEME') or 'http').strip()

            if proxy_host and proxy_port:
                if proxy_user and proxy_pass:
                    # 对用户名/密码进行URL编码，避免特殊字符导致格式错误
                    encoded_user = urllib.parse.quote(proxy_user, safe='')
                    encoded_pass = urllib.parse.quote(proxy_pass, safe='')
                    self.proxy_url = f"{proxy_scheme}://{encoded_user}:{encoded_pass}@{proxy_host}:{proxy_port}"
                else:
                    self.proxy_url = f"{proxy_scheme}://{proxy_host}:{proxy_port}"
        self.cookies_full = []  # 完整Cookie信息（带domain/path等）
        self.cookies_dict = {}  # 简单Cookie字典
        self.chrome_process = None  # Chrome进程
        # 使用环境变量配置端口，默认9225（避开finalarticle的9222）
        self.chrome_debug_port = int(os.getenv('CHROME_DEBUG_PORT', '9225'))
        
        # 创建logs目录
        self.logs_dir = 'logs'
        os.makedirs(self.logs_dir, exist_ok=True)
        
        # 配置日志到logs目录（先用普通文件名，检查后决定是否加warning前缀）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(self.logs_dir, f'bloomberg_url_fetcher_{timestamp}.log')
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file, encoding='utf-8'),
                logging.StreamHandler()
            ],
            force=True
        )
        logging.info("=" * 60)
        logging.info("Bloomberg URL获取器启动")
        logging.info("=" * 60)
        logging.info(f"日志文件: {self.log_file}")
        
        self.init_mongodb_connection()
    
    def rename_log_file_with_warning(self):
        """重命名日志文件，在前面加上warning前缀"""
        try:
            # 生成新的带warning前缀的文件名
            log_dir = os.path.dirname(self.log_file)
            original_filename = os.path.basename(self.log_file)
            warning_filename = original_filename.replace('bloomberg_url_fetcher_', 'warning_bloomberg_url_fetcher_')
            warning_log_file = os.path.join(log_dir, warning_filename)
            
            # 复制文件到新的warning文件名
            if os.path.exists(self.log_file):
                import shutil
                shutil.copy2(self.log_file, warning_log_file)
                
                # 更新日志文件路径
                self.log_file = warning_log_file
                
                logging.warning(f"日志文件已复制为: {self.log_file}")
                print(f"⚠️  检测到URL不一致，日志文件已复制为: {warning_filename}")
            
        except Exception as e:
            logging.error(f"复制日志文件失败: {e}")
    
    def find_chrome_path(self):
        """查找 Chrome 可执行文件路径"""
        possible_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None
    
    def start_chrome_auto(self):
        """自动启动Chrome浏览器（独立实例，避开finalarticle的9222）"""
        print("\n[INFO] 自动启动Chrome浏览器...")
        chrome_path = self.find_chrome_path()
        if not chrome_path:
            print("[ERROR] 未找到 Chrome")
            return False
        
        # 创建独立的用户数据目录（类似您的快捷方式方式）
        debug_dir = os.path.join(os.path.expanduser("~"), f"chrome-geturl-{self.chrome_debug_port}")
        os.makedirs(debug_dir, exist_ok=True)
        
        # 窗口配置：800x600，位置在右侧避开finalarticle
        WINDOW_WIDTH = 800
        WINDOW_HEIGHT = 600
        WINDOW_X = 850  # 避开左侧800区域
        WINDOW_Y = 0
        
        cmd = [
            chrome_path,
            f"--remote-debugging-port={self.chrome_debug_port}",
            f"--user-data-dir={debug_dir}",
            "--remote-allow-origins=*",  # 允许跨域访问CDP
            f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
            f"--window-position={WINDOW_X},{WINDOW_Y}",
            "https://www.bloomberg.com/latest"  # 访问latest页面，和请求保持一致
        ]
        
        print(f"[INFO] 调试端口: {self.chrome_debug_port}")
        print(f"[INFO] 用户数据目录: {debug_dir}")
        print(f"[INFO] 窗口: {WINDOW_WIDTH}x{WINDOW_HEIGHT} @ ({WINDOW_X}, {WINDOW_Y})")
        
        try:
            self.chrome_process = subprocess.Popen(cmd)
            print("[INFO] Chrome进程已启动，等待页面加载...")
            print("[提示] 请在打开的Chrome中登录Bloomberg（如果需要）")
            time.sleep(12)  # 等待页面加载（用户要求等5秒）
            print("[OK] Chrome 已启动")
            return True
        except Exception as e:
            print(f"[ERROR] Chrome启动失败: {e}")
            return False
    
    def get_cookies_from_chrome(self):
        """通过CDP从Chrome获取Cookie（返回完整Cookie信息）"""
        if not HAS_PYCHROME:
            print("[ERROR] pychrome未安装，无法获取Cookie")
            return [], {}
        
        try:
            print(f"[INFO] 正在从Chrome获取Cookie（端口{self.chrome_debug_port}）...")
            browser = pychrome.Browser(url=f"http://127.0.0.1:{self.chrome_debug_port}")
            tabs = browser.list_tab()
            
            if not tabs:
                print("[WARNING] 没有找到标签页，正在打开Bloomberg latest页面...")
                tab = browser.new_tab("https://www.bloomberg.com/latest")
                time.sleep(5)
            else:
                tab = tabs[0]
            
            tab.start()
            tab.call_method("Network.enable")
            result = tab.call_method("Network.getAllCookies")
            tab.stop()
            
            if not result or 'cookies' not in result:
                print("[ERROR] 未获取到Cookie数据")
                return [], {}
            
            # 筛选Bloomberg Cookie - 保存完整信息和简单字典
            bloomberg_cookies_full = []
            bloomberg_cookies_dict = {}
            
            for cookie in result['cookies']:
                if 'bloomberg.com' in cookie.get('domain', '').lower():
                    # 保存完整Cookie信息
                    bloomberg_cookies_full.append({
                        'domain': cookie.get('domain'),
                        'name': cookie.get('name'),
                        'value': cookie.get('value'),
                        'path': cookie.get('path', '/'),
                        'expires': cookie.get('expires', -1),
                        'secure': cookie.get('secure', False),
                        'httpOnly': cookie.get('httpOnly', False),
                        'sameSite': cookie.get('sameSite', 'None')
                    })
                    # 同时保存简单字典
                    bloomberg_cookies_dict[cookie.get('name')] = cookie.get('value')
            
            print(f"[OK] 获取到 {len(bloomberg_cookies_dict)} 个Bloomberg Cookie（完整信息）")
            return bloomberg_cookies_full, bloomberg_cookies_dict
            
        except Exception as e:
            print(f"[ERROR] CDP连接失败: {e}")
            import traceback
            traceback.print_exc()
            return [], {}
    
    def close_chrome(self):
        """关闭Chrome浏览器"""
        if self.chrome_process:
            try:
                print("\n[INFO] 正在关闭Chrome...")
                self.chrome_process.terminate()
                time.sleep(2)
                if self.chrome_process.poll() is None:
                    self.chrome_process.kill()
                print("[OK] Chrome已关闭")
            except Exception as e:
                print(f"[WARNING] 关闭Chrome失败: {e}")
    
    def init_mongodb_connection(self):
        """初始化MongoDB连接"""
        try:
            # MongoDB配置（从环境变量读取）
            mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
            mongo_port = int(os.getenv('MONGO_PORT', '27017'))
            mongo_user = os.getenv('MONGO_USER', '')
            mongo_password = os.getenv('MONGO_PASSWORD', '')
            mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')
            
            # URL 队列必须和文章集合分开；优先使用 URL_QUEUE_*，避免被 MONGODB_* 覆盖到 news.articles。
            database_name = os.getenv('URL_QUEUE_DATABASE') or os.getenv('URL_DATABASE') or 'bloomberg_url_queue'
            collection_name = os.getenv('URL_QUEUE_COLLECTION') or os.getenv('URL_COLLECTION') or 'urls'
            
            print(f"[INFO] MongoDB地址: {mongo_host}:{mongo_port}")
            print(f"[INFO] 目标数据库: {database_name}")
            print(f"[INFO] 目标集合: {collection_name}")
            
            # 构建MongoDB连接字符串
            if mongo_user and mongo_password:
                encoded_username = urllib.parse.quote_plus(mongo_user)
                encoded_password = urllib.parse.quote_plus(mongo_password)
                connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/{database_name}?authSource={mongo_authsource}"
                print(f"[INFO] MongoDB连接字符串: mongodb://{mongo_user}:***@{mongo_host}:{mongo_port}/{database_name}?authSource={mongo_authsource}")
            else:
                connection_string = f"mongodb://{mongo_host}:{mongo_port}/{database_name}"
                print(f"[INFO] MongoDB连接字符串: mongodb://{mongo_host}:{mongo_port}/{database_name}")
            
            # 连接MongoDB
            self.mongodb_client = pymongo.MongoClient(
                connection_string,
                serverSelectionTimeoutMS=8000,
                socketTimeoutMS=8000
            )
            
            # 测试连接
            self.mongodb_client.admin.command('ping')
            print("[OK] MongoDB 连接成功!")
            logging.info("MongoDB 连接成功!")
            
            # 使用配置的数据库和集合
            self.db = self.mongodb_client[database_name]
            self.collection = self.db[collection_name]
            
            self.collection.create_index("url", unique=True)
            try:
                self.collection.create_index("canonical_url", unique=True, sparse=True)
            except Exception:
                self.collection.create_index("canonical_url", sparse=True)
            self.collection.create_index("fetched_at")
            
            print(f"[INFO] 数据库: {database_name}")
            print(f"[INFO] 集合: {collection_name}")
            
            count = self.collection.estimated_document_count()
            print(f"[INFO] 现有URL数: {count}")
            logging.info(f"现有URL数: {count}")
            
        except Exception as e:
            print(f"[ERROR] MongoDB连接失败: {e}")
            self.mongodb_client = None
            self.db = None
            self.collection = None
    
    def get_enhanced_headers(self) -> Dict:
        """生成真实的浏览器请求头"""
        return {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Origin': 'https://www.bloomberg.com',
            'Pragma': 'no-cache',
            'Referer': 'https://www.bloomberg.com/latest',
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest'
        }
    
    def get_session_with_cookies(self):
        """创建带有完整cookies的会话"""
        session = requests.Session()
        
        # curl_cffi和requests设置Cookie的方式不同
        if USE_CURL_CFFI:
            # curl_cffi使用简单字典
            if self.cookies_dict:
                session.cookies.update(self.cookies_dict)
                print(f"[INFO] curl_cffi: 使用 {len(self.cookies_dict)} 个Cookie")
        else:
            # requests使用http.cookiejar.Cookie保留所有属性
            if self.cookies_full:
                from http.cookiejar import Cookie
                cookie_count = 0
                for cookie_data in self.cookies_full:
                    try:
                        cookie = Cookie(
                            version=0,
                            name=cookie_data.get('name'),
                            value=cookie_data.get('value'),
                            port=None,
                            port_specified=False,
                            domain=cookie_data.get('domain', '.bloomberg.com'),
                            domain_specified=True,
                            domain_initial_dot=cookie_data.get('domain', '').startswith('.'),
                            path=cookie_data.get('path', '/'),
                            path_specified=True,
                            secure=cookie_data.get('secure', False),
                            expires=int(cookie_data.get('expires', 0)) if cookie_data.get('expires', -1) > 0 else None,
                            discard=False,
                            comment=None,
                            comment_url=None,
                            rest={'HttpOnly': cookie_data.get('httpOnly', False)},
                            rfc2109=False
                        )
                        session.cookies.set_cookie(cookie)
                        cookie_count += 1
                    except Exception as e:
                        print(f"[WARNING] Cookie设置失败: {cookie_data.get('name', 'unknown')} - {e}")
                
                print(f"[INFO] requests: 使用完整Cookie {cookie_count} 个")
            elif self.cookies_dict:
                session.cookies.update(self.cookies_dict)
                print(f"[INFO] requests: 使用简单Cookie {len(self.cookies_dict)} 个")
        
        # 如果配置了代理，添加到session中
        if self.proxy_url:
            proxies = {
                'http': self.proxy_url,
                'https': self.proxy_url
            }
            session.proxies.update(proxies)
            # 打印时隐藏密码，避免泄露
            try:
                from urllib.parse import urlsplit, urlunsplit
                parts = urlsplit(self.proxy_url)
                netloc_masked = parts.netloc
                if '@' in parts.netloc and ':' in parts.netloc.split('@')[0]:
                    cred, host = parts.netloc.split('@', 1)
                    user = cred.split(':', 1)[0]
                    netloc_masked = f"{user}:***@{host}"
                safe_proxy = urlunsplit((parts.scheme, netloc_masked, parts.path, parts.query, parts.fragment))
                print(f"[INFO] 使用代理: {safe_proxy}")
            except Exception:
                print("[INFO] 使用代理(已隐藏密码)")
        
        return session
    
    def try_api_with_session(self, session, url, max_retries=3):
        """使用会话尝试API调用，包含重试机制"""
        headers = self.get_enhanced_headers()
        
        for attempt in range(max_retries):
            try:
                print(f"\n[INFO] 尝试 {attempt + 1}/{max_retries}: 获取最新文章URL")
                
                # 随机延迟，模拟人类行为
                if attempt > 0:
                    delay = random.uniform(3, 6)
                    print(f"[INFO] 等待 {delay:.1f} 秒...")
                    time.sleep(delay)
                
                response = session.get(url, headers=headers, timeout=30)
                
                print(f"[INFO] 状态码: {response.status_code}")
                
                if response.status_code == 200:
                    response.encoding = 'utf-8'
                    return response
                elif response.status_code == 403:
                    print("[ERROR] 遇到403错误，可能被反爬虫系统拦截")
                    return None
                elif response.status_code == 429:
                    print("[ERROR] 请求过于频繁")
                    time.sleep(random.uniform(10, 15))
                else:
                    print(f"[ERROR] 未知错误: {response.status_code}")
                    
            except Exception as e:
                print(f"[ERROR] 请求失败: {e}")
                
        return None
    
    def get_cookies_from_logged_chrome(self):
        """从已登录的Chrome获取Cookie（使用配置的端口）"""
        if not HAS_PYCHROME:
            print("[ERROR] pychrome未安装")
            return [], {}
        
        try:
            print(f"[INFO] 从登录浏览器({self.chrome_debug_port}端口)获取Cookie...")
            browser = pychrome.Browser(url=f"http://127.0.0.1:{self.chrome_debug_port}")
            tabs = browser.list_tab()
            
            if not tabs:
                print(f"[WARNING] {self.chrome_debug_port}端口没有找到标签页，正在打开Bloomberg latest页面...")
                tab = browser.new_tab("https://www.bloomberg.com/latest")
                time.sleep(5)
            else:
                tab = tabs[0]
            
            tab.start()
            tab.call_method("Network.enable")
            result = tab.call_method("Network.getAllCookies")
            tab.stop()
            
            if not result or 'cookies' not in result:
                print("[ERROR] 未获取到Cookie数据")
                return [], {}
            
            # 筛选Bloomberg Cookie
            bloomberg_cookies_full = []
            bloomberg_cookies_dict = {}
            
            for cookie in result['cookies']:
                if 'bloomberg.com' in cookie.get('domain', '').lower():
                    bloomberg_cookies_full.append({
                        'domain': cookie.get('domain'),
                        'name': cookie.get('name'),
                        'value': cookie.get('value'),
                        'path': cookie.get('path', '/'),
                        'expires': cookie.get('expires', -1),
                        'secure': cookie.get('secure', False),
                        'httpOnly': cookie.get('httpOnly', False),
                        'sameSite': cookie.get('sameSite', 'None')
                    })
                    bloomberg_cookies_dict[cookie.get('name')] = cookie.get('value')
            
            print(f"[OK] 从登录浏览器获取到 {len(bloomberg_cookies_dict)} 个Bloomberg Cookie")
            return bloomberg_cookies_full, bloomberg_cookies_dict
            
        except Exception as e:
            print(f"[ERROR] 从{self.chrome_debug_port}端口获取Cookie失败: {e}")
            print(f"[提示] 请确保登录浏览器正在运行（chrome.exe --remote-debugging-port={self.chrome_debug_port}）")
            import traceback
            traceback.print_exc()
            return [], {}
    
    def fetch_urls_from_api(self) -> List[str]:
        """获取最新文章URL列表"""
        print("\n" + "=" * 60)
        print("开始获取Bloomberg最新文章URL")
        print("=" * 60)
        
        # 步骤1: 尝试从已运行的Chrome获取Cookie，失败则自动启动
        print("[INFO] 从已登录的Chrome浏览器获取Cookie...")
        self.cookies_full, self.cookies_dict = self.get_cookies_from_logged_chrome()
        
        if not self.cookies_dict:
            print(f"[WARNING] 未能从端口{self.chrome_debug_port}获取Cookie")
            print("[INFO] 尝试自动启动Chrome...")
            
            if self.start_chrome_auto():
                print("[INFO] Chrome已启动，等待建立连接...")
                time.sleep(3)  # 额外等待CDP连接就绪
                
                # 再次尝试获取Cookie
                self.cookies_full, self.cookies_dict = self.get_cookies_from_chrome()
                
                if not self.cookies_dict:
                    print("[WARNING] 仍未获取到Cookie，将使用无Cookie模式尝试...")
            else:
                print("[WARNING] Chrome启动失败，将使用无Cookie模式尝试...")
        
        # 步骤3: 先访问latest页面（模拟正常用户行为），然后调用API端点
        latest_page_url = "https://www.bloomberg.com/latest"
        api_url = "https://www.bloomberg.com/lineup-next/api/stories"
        
        print(f"\n[INFO] Cookie数量: {len(self.cookies_dict)} 个（完整属性）")
        
        session = self.get_session_with_cookies()
        
        # 先访问首页建立会话
        try:
            print("[INFO] 步骤1: 先访问首页建立会话...")
            home_headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            }
            
            if USE_CURL_CFFI:
                home_resp = session.get('https://www.bloomberg.com/', headers=home_headers, timeout=30, impersonate='chrome120')
            else:
                home_resp = session.get('https://www.bloomberg.com/', headers=home_headers, timeout=30)
            
            print(f"[INFO] 首页状态码: {home_resp.status_code}")
            time.sleep(random.uniform(2, 4))  # 等待一下
        except Exception as e:
            print(f"[WARNING] 访问首页失败: {e}")
        
        # 步骤2: 访问latest页面（模拟正常用户）
        try:
            print(f"[INFO] 步骤2: 访问 /latest 页面（模拟正常用户）...")
            latest_headers = {
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'DNT': '1',
                'Pragma': 'no-cache',
                'Referer': 'https://www.bloomberg.com/',
                'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            if USE_CURL_CFFI:
                latest_resp = session.get(latest_page_url, headers=latest_headers, timeout=30, impersonate='chrome120')
            else:
                latest_resp = session.get(latest_page_url, headers=latest_headers, timeout=30)
            
            print(f"[INFO] /latest 页面状态码: {latest_resp.status_code}")
            time.sleep(random.uniform(1, 2))  # 等待一下，模拟真实用户
        except Exception as e:
            print(f"[WARNING] 访问/latest页面失败: {e}")
        
        # 步骤3: 调用API端点获取文章列表（模拟JavaScript请求）
        print(f"\n[INFO] 步骤3: 调用API端点获取文章数据...")
        
        # API请求的headers（模拟JavaScript fetch请求）
        api_headers = {
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'DNT': '1',
            'Origin': 'https://www.bloomberg.com',
            'Pragma': 'no-cache',
            'Referer': 'https://www.bloomberg.com/latest',  # 来自latest页面
            'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # API参数（和融合版一样）
        api_params = {
            'types': 'ARTICLE,FEATURE,INTERACTIVE,LETTER,EXPLAINERS',
            'pageNumber': '1',
            'limit': '25'
        }
        
        try:
            print(f"[INFO] 请求API: {api_url}")
            print(f"[INFO] 参数: {api_params}")
            
            # 如果使用curl_cffi，添加impersonate参数
            if USE_CURL_CFFI:
                print("[INFO] 使用curl_cffi模拟Chrome 120")
                response = session.get(api_url, headers=api_headers, params=api_params, timeout=30, impersonate='chrome120')
            else:
                response = session.get(api_url, headers=api_headers, params=api_params, timeout=30)
            
            print(f"[INFO] 状态码: {response.status_code}")
            print(f"[INFO] 响应大小: {len(response.content)} 字节")
            logging.info(f"API响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                print("[OK] API数据获取成功!")
                logging.info("API数据获取成功，开始解析URL")
                urls = self.extract_urls_from_api_response(response.text)
                return urls
            else:
                print(f"[ERROR] API请求失败: {response.status_code}")
                logging.error(f"API请求失败，状态码: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"[ERROR] API请求失败: {e}")
            logging.error(f"API请求失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def extract_urls_from_html(self, html_content):
        """从HTML页面中提取文章URL - 优先从__NEXT_DATA__ JSON提取，备用BeautifulSoup"""
        urls = []
        
        try:
            import re
            import json
            
            print("[INFO] 开始解析HTML...")
            logging.info(f"HTML内容长度: {len(html_content)} 字符")
            
            # 方法1: 从__NEXT_DATA__ JSON提取（融合版方法，更可靠）
            print("[INFO] 尝试从 __NEXT_DATA__ JSON 提取URL...")
            logging.info("使用正则搜索 __NEXT_DATA__ 标签")
            
            json_match = re.search(
                r'<script id="__NEXT_DATA__" type="application/json">\s*(\{.*?\})\s*</script>',
                html_content,
                re.DOTALL
            )
            
            if json_match:
                print("[OK] 找到 __NEXT_DATA__ 标签")
                logging.info("成功找到 __NEXT_DATA__ 标签")
                
                try:
                    json_str = json_match.group(1)
                    logging.info(f"JSON字符串长度: {len(json_str)} 字符")
                    
                    next_data = json.loads(json_str)
                    print("[OK] 成功解析 __NEXT_DATA__ JSON")
                    logging.info("JSON解析成功")
                    
                    # 保存完整JSON用于调试（无论是否找到URL都保存）
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    json_filename = f'debug_next_data_{timestamp}.json'
                    try:
                        with open(json_filename, 'w', encoding='utf-8') as f:
                            json.dump(next_data, f, ensure_ascii=False, indent=2)
                        print(f"[DEBUG] __NEXT_DATA__ 已保存到: {json_filename}")
                        logging.info(f"完整JSON已保存到: {json_filename}")
                    except Exception as e:
                        logging.error(f"保存JSON失败: {e}")
                    
                    # 尝试从不同路径提取文章列表
                    urls = self._extract_urls_from_next_data(next_data)
                    
                    if urls:
                        print(f"[OK] 从 __NEXT_DATA__ 提取到 {len(urls)} 个URL")
                        logging.info(f"成功提取 {len(urls)} 个URL")
                        self._display_urls(urls)
                        return urls
                    else:
                        print("[WARNING] __NEXT_DATA__ 中未找到文章URL，尝试备用方法...")
                        logging.warning("JSON中未找到文章URL，切换到HTML解析方法")
                        
                except json.JSONDecodeError as e:
                    print(f"[WARNING] __NEXT_DATA__ JSON解析失败: {e}")
                    logging.error(f"JSON解析失败: {e}")
            else:
                print("[WARNING] 未找到 __NEXT_DATA__ 标签")
                logging.warning("HTML中未找到 __NEXT_DATA__ 标签")
            
            # 方法2: BeautifulSoup备用方案（当前方法）
            print("[INFO] 使用 BeautifulSoup 备用方案...")
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # 查找所有包含/news/articles/的链接
            article_links = soup.find_all('a', href=re.compile(r'/news/articles/'))
            print(f"[INFO] 找到 {len(article_links)} 个文章链接")
            
            for link in article_links:
                href = link.get('href')
                if href:
                    # 如果是相对URL，添加域名前缀
                    if href.startswith('/'):
                        url = 'https://www.bloomberg.com' + href
                    elif not href.startswith('http'):
                        url = 'https://www.bloomberg.com/' + href.lstrip('/')
                    else:
                        url = href
                    
                    # 确保URL格式正确
                    if 'bloomberg.com' in url and url not in urls:
                        # 清理URL参数
                        url = url.split('?')[0]
                        urls.append(url)
            
            print(f"[OK] BeautifulSoup 提取到 {len(urls)} 个唯一URL")
            self._display_urls(urls)
            
            return urls
            
        except ImportError:
            print("[ERROR] 未安装beautifulsoup4，请运行: pip install beautifulsoup4")
            return []
        except Exception as e:
            print(f"[ERROR] HTML解析失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_urls_from_next_data(self, next_data):
        """从__NEXT_DATA__ JSON结构中提取文章URL"""
        urls = []
        
        try:
            logging.info("开始从JSON结构中提取URL")
            
            # 先记录JSON的顶层结构
            top_keys = list(next_data.keys()) if isinstance(next_data, dict) else []
            logging.info(f"JSON顶层键: {top_keys}")
            
            # 尝试多种可能的JSON路径
            possible_paths = [
                # /latest 页面可能的路径
                ['props', 'pageProps', 'stories'],
                ['props', 'pageProps', 'data', 'stories'],
                ['props', 'pageProps', 'lineupStories'],
                ['props', 'pageProps', 'articleList'],
                ['props', 'pageProps', 'items'],
                ['props', 'pageProps', 'results'],
                # 其他可能的路径
                ['props', 'initialState', 'stories'],
                ['props', 'initialProps', 'pageProps', 'stories'],
            ]
            
            stories = None
            found_path = None
            
            for path in possible_paths:
                try:
                    path_str = ' -> '.join(path)
                    logging.info(f"尝试路径: {path_str}")
                    
                    data = next_data
                    for i, key in enumerate(path):
                        if isinstance(data, dict) and key in data:
                            data = data[key]
                            logging.debug(f"  步骤{i+1}: 找到键 '{key}', 类型={type(data).__name__}")
                        else:
                            logging.debug(f"  步骤{i+1}: 键 '{key}' 不存在或数据不是字典")
                            data = None
                            break
                    
                    if data and isinstance(data, list) and len(data) > 0:
                        stories = data
                        found_path = path_str
                        print(f"[OK] 在路径找到数据: {found_path}")
                        logging.info(f"成功找到数据，路径: {found_path}, 数量: {len(data)}")
                        break
                    else:
                        logging.debug(f"  路径 {path_str} 无效或为空")
                except Exception as e:
                    logging.debug(f"  路径 {path_str} 异常: {e}")
                    continue
            
            if not stories:
                print("[WARNING] 尝试了所有已知路径，未找到文章列表")
                logging.warning(f"所有路径都失败，尝试了 {len(possible_paths)} 条路径")
                
                # 输出实际的props结构帮助调试
                if 'props' in next_data:
                    props_keys = list(next_data['props'].keys()) if isinstance(next_data.get('props'), dict) else []
                    logging.info(f"实际的 props 键: {props_keys}")
                    if 'pageProps' in next_data.get('props', {}):
                        pageProps_keys = list(next_data['props']['pageProps'].keys()) if isinstance(next_data['props'].get('pageProps'), dict) else []
                        logging.info(f"实际的 pageProps 键: {pageProps_keys}")
                
                return []
            
            print(f"[INFO] 找到 {len(stories)} 个故事条目")
            logging.info(f"stories 类型: {type(stories)}, 长度: {len(stories)}")
            
            # 从stories中提取URL
            logging.info(f"开始遍历 {len(stories)} 个story条目")
            
            # 先看第一个story的结构
            if stories and len(stories) > 0:
                first_story_keys = list(stories[0].keys()) if isinstance(stories[0], dict) else []
                logging.info(f"第一个story的键: {first_story_keys}")
            
            for idx, story in enumerate(stories):
                if not isinstance(story, dict):
                    logging.debug(f"story[{idx}] 不是字典类型: {type(story)}")
                    continue
                
                # 尝试不同的URL字段
                url = None
                found_field = None
                for url_field in ['url', 'uri', 'path', 'link', 'href', 'longURL']:
                    if url_field in story and story[url_field]:
                        url = story[url_field]
                        found_field = url_field
                        break
                
                if url:
                    logging.debug(f"story[{idx}] 找到URL字段 '{found_field}': {url}")
                    
                    # 规范化URL
                    original_url = url
                    if url.startswith('/'):
                        url = 'https://www.bloomberg.com' + url
                    elif not url.startswith('http'):
                        url = 'https://www.bloomberg.com/' + url.lstrip('/')
                    
                    # 清理参数
                    url = url.split('?')[0]
                    
                    # 只要文章类型的URL
                    if 'bloomberg.com' in url and '/news/articles/' in url:
                        if url not in urls:
                            urls.append(url)
                            print(f"  [+] {url}")
                            logging.info(f"添加URL: {url}")
                        else:
                            logging.debug(f"URL重复，跳过: {url}")
                    else:
                        logging.debug(f"URL不符合文章类型，跳过: {url}")
                else:
                    # 记录这个story有哪些可用的键
                    story_keys = list(story.keys())[:10]  # 只记录前10个键
                    logging.debug(f"story[{idx}] 未找到URL字段，可用键: {story_keys}")
            
            return urls
            
        except Exception as e:
            print(f"[ERROR] 从 __NEXT_DATA__ 提取URL失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _display_urls(self, urls):
        """显示提取到的URL"""
        if not urls:
            return
        
        # 显示前10个URL
        display_count = min(10, len(urls))
        for i, url in enumerate(urls[:display_count]):
            print(f"  [{i+1}] {url}")
        
        if len(urls) > display_count:
            print(f"  ... 还有 {len(urls) - display_count} 个URL")
    
    def extract_urls_from_api_data(self, data):
        """从API返回数据中提取文章URL"""
        urls = []
        
        try:
            # 尝试不同的数据结构
            stories = []
            
            if isinstance(data, dict):
                if 'stories' in data:
                    stories = data['stories']
                elif 'data' in data:
                    stories = data['data']
                elif 'results' in data:
                    stories = data['results']
                elif 'articles' in data:
                    stories = data['articles']
            elif isinstance(data, list):
                stories = data
            
            print(f"[INFO] 找到 {len(stories)} 个故事条目")
            
            for story in stories:
                if isinstance(story, dict):
                    # 尝试不同的URL字段
                    url = None
                    for url_field in ['url', 'uri', 'path', 'link', 'href']:
                        if url_field in story and story[url_field]:
                            url = story[url_field]
                            break
                    
                    if url:
                        # 如果是相对URL，添加域名前缀
                        if url.startswith('/'):
                            url = 'https://www.bloomberg.com' + url
                        elif not url.startswith('http'):
                            url = 'https://www.bloomberg.com/' + url.lstrip('/')
                        
                        # 确保URL以https://www.bloomberg.com开头
                        if not url.startswith('https://www.bloomberg.com'):
                            continue
                        
                        # 只要文章类型的URL
                        if '/news/articles/' in url:
                            urls.append(url)
                            print(f"[OK] 提取URL: {url}")
            
            print(f"\n[INFO] 总共提取到 {len(urls)} 个文章URL")
            
            # 限制最多25篇文章
            if len(urls) > 25:
                urls = urls[:25]
                print(f"[INFO] 限制为最新 25 篇文章")
            
            return urls
            
        except Exception as e:
            print(f"[ERROR] 提取URL失败: {e}")
            return []
    
    def extract_urls_from_api_response(self, json_text):
        """从API响应的JSON中提取文章URL（融合版方法）"""
        urls = []
        
        try:
            print("[INFO] 开始解析API返回的JSON数据")
            logging.info("开始解析API返回的JSON数据")
            
            # 解析JSON
            data = json.loads(json_text)
            print(f"[INFO] JSON解析成功")
            logging.info("JSON解析成功")
            
            # 初始化
            stories = []
            top_keys = []
            
            # 检查data的类型
            if isinstance(data, list):
                # API直接返回数组（Bloomberg的情况）
                print(f"[INFO] API直接返回数组，包含 {len(data)} 个元素")
                logging.info(f"API直接返回数组，包含 {len(data)} 个元素")
                stories = data
            elif isinstance(data, dict):
                # 尝试找到stories数组
                # 可能的路径
                possible_paths = [
                    ['stories'],
                    ['data', 'stories'],
                    ['results'],
                    ['data', 'results'],
                    ['articles'],
                    ['data', 'articles'],
                    ['items'],
                    ['data', 'items']
                ]
                
                # 记录JSON顶层键
                top_keys = list(data.keys())
                logging.info(f"JSON顶层键: {top_keys}")
                print(f"[INFO] JSON顶层键: {top_keys}")
                
                # 尝试每个路径
                for path in possible_paths:
                    try:
                        temp = data
                        path_str = ' -> '.join(path)
                        logging.info(f"尝试路径: {path_str}")
                        
                        for key in path:
                            if isinstance(temp, dict) and key in temp:
                                temp = temp[key]
                            else:
                                break
                        else:
                            # 所有键都找到了
                            if isinstance(temp, list) and len(temp) > 0:
                                stories = temp
                                print(f"[OK] 在路径 '{path_str}' 找到 {len(stories)} 个故事")
                                logging.info(f"在路径 '{path_str}' 找到 {len(stories)} 个故事")
                                break
                    except Exception as e:
                        logging.debug(f"路径 {path_str} 失败: {e}")
                        continue
            
            if not stories:
                print(f"[WARNING] 未找到stories数组")
                logging.warning("未找到stories数组")
                logging.warning(f"可用的顶层键: {top_keys}")
                return []
            
            # 从stories中提取URL
            print(f"[INFO] 开始从 {len(stories)} 个故事中提取URL...")
            logging.info(f"开始从 {len(stories)} 个故事中提取URL")
            
            for idx, story in enumerate(stories):
                if not isinstance(story, dict):
                    continue
                
                # 尝试不同的URL字段
                url = None
                for url_field in ['url', 'uri', 'path', 'link', 'href', 'longURL']:
                    if url_field in story and story[url_field]:
                        url = story[url_field]
                        break
                
                if url:
                    # 规范化URL
                    if url.startswith('/'):
                        url = 'https://www.bloomberg.com' + url
                    elif not url.startswith('http'):
                        url = 'https://www.bloomberg.com/' + url.lstrip('/')
                    
                    # 清理参数
                    url = url.split('?')[0]
                    
                    # 只要 /news/articles/ 的文章
                    if 'bloomberg.com' in url and '/news/articles/' in url:
                        if url not in urls:
                            urls.append(url)
                            print(f"  [+] {url}")
                            logging.info(f"添加URL: {url}")
                    else:
                        logging.debug(f"过滤非news/articles: {url}")
            
            print(f"[OK] 从API响应中提取到 {len(urls)} 个URL")
            logging.info(f"从API响应中提取到 {len(urls)} 个URL")
            return urls
            
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON解析失败: {e}")
            logging.error(f"JSON解析失败: {e}")
            return []
        except Exception as e:
            print(f"[ERROR] 从API响应提取URL失败: {e}")
            logging.error(f"从API响应提取URL失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def save_urls_to_mongodb(self, urls: List[str]) -> int:
        """批量保存URL到MongoDB URL队列。"""
        if not urls:
            return 0
        
        print(f"\n[INFO] 开始处理 {len(urls)} 个URL...")
        logging.info(f"开始处理 {len(urls)} 个URL")
        
        # MongoDB 是正式数据源；本地 JSON 只作为旧版本兼容，不再读写。
        mongodb_all_urls = set()
        if self.collection is not None:
            cursor = self.collection.find(
                {},
                {'url': 1, '_id': 0}
            )
            mongodb_all_urls = {doc['url'] for doc in cursor}
            print(f"[INFO] MongoDB URL历史: {len(mongodb_all_urls)} 个")
            logging.info(f"MongoDB URL历史: {len(mongodb_all_urls)} 个")

        mongodb_all_canonical_urls = {canonicalize_url(url) for url in mongodb_all_urls}
        mongodb_new_urls = [url for url in urls if url not in mongodb_all_urls and canonicalize_url(url) not in mongodb_all_canonical_urls]
        
        if not mongodb_new_urls:
            print(f"[INFO] 所有URL已存在于MongoDB，无需保存")
            logging.info("所有URL已存在于MongoDB")
            return 0
        
        print(f"[INFO] MongoDB新URL: {len(mongodb_new_urls)} 个")
        logging.info(f"MongoDB新URL: {len(mongodb_new_urls)} 个")
        
        mongodb_success = 0
        if self.collection is not None and mongodb_new_urls:
            for url in mongodb_new_urls:
                now = datetime.now().isoformat() + 'Z'
                result = self.collection.update_one(
                    {'canonical_url': canonicalize_url(url)},
                    {
                        '$setOnInsert': {
                            'url': url,
                            'canonical_url': canonicalize_url(url),
                            'fetched_at': now,
                            'status': 'pending',
                            'version': '1.0'
                        }
                    },
                    upsert=True
                )
                if result.upserted_id is not None:
                    mongodb_success += 1

            print(f"[OK] MongoDB插入成功: {mongodb_success} 个URL")
            logging.info(f"MongoDB插入成功: {mongodb_success} 个URL")
        
        print(f"\n[INFO] 本次新增URL列表:")
        for i, url in enumerate(mongodb_new_urls, 1):
            print(f"  {i}. [MongoDB] {url}")
            logging.info(f"新增URL [MongoDB]: {url}")
        
        print(f"\n[SUCCESS] 保存结果:")
        print(f"  - MongoDB: 新增 {mongodb_success} 个")
        print(f"  - 总计: {mongodb_success} 个URL新增到MongoDB")
        logging.info(f"保存结果: MongoDB新增 {mongodb_success} 个")
        
        return mongodb_success
    
    def close_connection(self):
        """关闭MongoDB连接"""
        if self.mongodb_client:
            self.mongodb_client.close()
            print("[OK] MongoDB连接已关闭")


def main():
    print("=" * 60)
    print("Bloomberg URL获取器 - 自动Cookie版本")
    print("=" * 60)
    print()
    
    fetcher = BloombergURLFetcher()
    
    try:
        # 获取最新URL
        urls = fetcher.fetch_urls_from_api()
        
        if urls:
            print(f"\n[INFO] 获取到 {len(urls)} 个URL")
            
            # 保存到MongoDB
            inserted_count = fetcher.save_urls_to_mongodb(urls)
            print(f"\n[SUCCESS] MongoDB: 新增 {inserted_count} 条")
            print("\n[SUCCESS] URL获取和保存完成!")
        else:
            print("\n[WARNING] 未获取到URL")
    
    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断")
    except Exception as e:
        print(f"\n[ERROR] 错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 关闭Chrome浏览器
        fetcher.close_chrome()
        # 关闭MongoDB连接
        fetcher.close_connection()


if __name__ == "__main__":
    main()
