#最终版
"""
Guardian新闻爬虫 - 只获取普通文章版本（可设置页数范围）
用URL去重，可设置起始页和结束页
"""

import requests
import json
from datetime import datetime
import hashlib
import time
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv
import pymongo
from pymongo.errors import DuplicateKeyError
import urllib.parse
import logging
from urllib.parse import quote_plus
import subprocess
import signal
import sys

# 加载环境变量
load_dotenv()

class SSHTunnel:
    """SSH隧道管理类"""
    def __init__(self):
        self.process = None
        self.local_port = None
        
    def start_tunnel(self, ssh_host, ssh_port, ssh_user, ssh_key_path, 
                        remote_host, remote_port, local_port=None, logger=None):
        """启动SSH隧道 - 与fanli配置一致"""
        try:
            # 如果没有指定本地端口，使用默认端口
            if local_port is None:
                local_port = 27010
            
            self.local_port = local_port
            
            # 构建SSH命令
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
            print(msg)
            if logger:
                logger.info(f"[DEBUG] {msg}")
                logger.info(f"[DEBUG] SSH命令: {' '.join(ssh_cmd)}")
            
            # 启动SSH进程
            self.process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT
            )
            
            # 等待隧道建立并重试检查端口
            if logger:
                logger.info(f"[DEBUG] 等待SSH隧道建立...")
            
            # 多次检查端口是否可访问
            import socket
            max_retries = 10
            retry_interval = 0.5
            
            for attempt in range(max_retries):
                time.sleep(retry_interval)
                
                # 检查SSH进程是否还在运行
                poll_result = self.process.poll()
                if poll_result is not None:
                    # 进程已退出
                    stdout, _ = self.process.communicate()
                    error_msg = f"SSH隧道启动失败！进程已退出，退出码: {poll_result}"
                    print(f"[ERROR] {error_msg}")
                    if logger:
                        logger.error(f"[ERROR] {error_msg}")
                    if stdout:
                        error_output = stdout.decode('utf-8', errors='ignore')
                        if logger:
                            logger.error(f"[ERROR] SSH输出:\n{error_output}")
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
                        if logger:
                            logger.info(f"[OK] {success_msg}")
                        return True
                    else:
                        if logger and attempt < max_retries - 1:
                            logger.info(f"[DEBUG] 端口尝试 {attempt + 1}/{max_retries}: 错误码 {result}，继续等待...")
                except Exception as e:
                    if logger and attempt < max_retries - 1:
                        logger.info(f"[DEBUG] 端口尝试 {attempt + 1}/{max_retries}: {e}，继续等待...")
            
            # 所有重试都失败
            error_msg = f"SSH隧道端口 127.0.0.1:{local_port} 在{max_retries}次尝试后仍无法访问"
            print(f"[ERROR] {error_msg}")
            if logger:
                logger.error(f"[ERROR] {error_msg}")
            return False
                
        except Exception as e:
            error_msg = f"启动SSH隧道时出错: {e}"
            print(f"[ERROR] {error_msg}")
            if logger:
                logger.error(f"[ERROR] {error_msg}")
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

class GuardianCrawler:
    def __init__(self, api_key: str = None, data_file: str = None, base_url: str = None):
        # 从环境变量读取配置，如果没有传参则使用环境变量
        self.api_key = api_key or os.getenv('GUARDIAN_API_KEY')
        self.base_url = base_url or os.getenv('GUARDIAN_BASE_URL', 'https://content.guardianapis.com')
        # 统一将本地存储放到 data 目录
        self.data_dir = os.getenv('GUARDIAN_DATA_DIR', 'data')
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
        # 主文件路径写死为 data/guardian_articles.json
        if data_file:
            self.data_file = data_file
        else:
            self.data_file = os.path.join(self.data_dir, 'guardian_articles.json')
        
        # 验证必需的配置
        if not self.api_key:
            raise ValueError("API Key未配置！请在guardian_config.env中设置GUARDIAN_API_KEY或通过参数传入")
        
        # 初始化日志
        self.setup_logging()
        
        # 初始化SSH隧道
        self.ssh_tunnel = SSHTunnel()
        
        # 初始化MongoDB连接
        self.mongodb_client = None
        self.db_articles = None
        self.collection_articles = None
        self.logger.info("[DEBUG] 开始初始化MongoDB连接...")
        self.init_mongodb_connection()
        self.logger.info("[DEBUG] MongoDB连接初始化完成")
        
        # 加载本地文件用于本地存储功能
        self.existing_articles = self.load_existing_articles()
        
        # 从数据库获取URL进行去重
        self.existing_urls = self.get_existing_urls()
        
        # 记录查重结果到日志
        self.log_dedup_results()
        
        print(f"初始化完成，已加载 {len(self.existing_articles)} 篇本地文章")
        print(f"从数据库获取到 {len(self.existing_urls)} 个Guardian文章URL用于去重")

    def setup_logging(self):
        """设置日志配置"""
        # 创建logs目录
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        # 生成日志文件名（先不添加warning前缀，等检查完再决定）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = os.path.join(log_dir, f"guardian_crawler_{timestamp}.log")
        
        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file, encoding='utf-8'),
                logging.StreamHandler()  # 同时输出到控制台
            ]
        )
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("=" * 60)
        self.logger.info("Guardian新闻爬虫启动")
        self.logger.info("=" * 60)
        self.logger.info(f"日志文件: {self.log_file}")

    def log_dedup_results(self):
        """记录查重结果到日志"""
        # 统计本地和数据库的文章数量
        local_count = len(self.existing_articles)
        db_count = len(self.existing_urls)
        
        self.logger.info("查重统计结果:")
        self.logger.info(f"  本地文件文章数: {local_count}")
        self.logger.info(f"  数据库Guardian文章数: {db_count}")
        self.logger.info(f"  去重URL总数: {len(self.existing_urls)}")
        
        # 检查URL不一致情况
        has_url_mismatch = False
        if local_count > 0:
            local_urls = {article['url'] for article in self.existing_articles if article.get('url')}
            overlap_count = len(local_urls.intersection(self.existing_urls))
            local_only_count = local_count - overlap_count
            db_only_count = db_count - overlap_count
            
            self.logger.info(f"  本地与数据库重叠文章数: {overlap_count}")
            self.logger.info(f"  仅本地存在文章数: {local_only_count}")
            self.logger.info(f"  仅数据库存在文章数: {db_only_count}")
            
            # 检查是否有URL不一致
            if local_only_count > 0 or db_only_count > 0:
                has_url_mismatch = True
                self.logger.warning("⚠️  检测到本地与数据库URL不一致！")
                self.logger.warning(f"  本地独有的URL数量: {local_only_count}")
                self.logger.warning(f"  数据库独有的URL数量: {db_only_count}")
        
        # 如果有URL不一致，重命名日志文件
        if has_url_mismatch:
            self.rename_log_file_with_warning()

    def rename_log_file_with_warning(self):
        """重命名日志文件，在前面加上warning前缀"""
        try:
            # 生成新的带warning前缀的文件名
            log_dir = os.path.dirname(self.log_file)
            original_filename = os.path.basename(self.log_file)
            warning_filename = original_filename.replace('guardian_crawler_', 'warning_guardian_crawler_')
            warning_log_file = os.path.join(log_dir, warning_filename)
            
            # 复制文件到新的warning文件名
            if os.path.exists(self.log_file):
                import shutil
                shutil.copy2(self.log_file, warning_log_file)
                
                # 更新日志文件路径
                self.log_file = warning_log_file
                
                self.logger.warning(f"日志文件已复制为: {self.log_file}")
                print(f"⚠️  检测到URL不一致，日志文件已复制为: {warning_filename}")
            
        except Exception as e:
            self.logger.error(f"复制日志文件失败: {e}")

    def init_mongodb_connection(self):
        """初始化MongoDB连接 - 使用SSH隧道"""
        self.logger.info("[DEBUG] ===== 开始MongoDB连接初始化 =====")
        try:
            # SSH配置（从环境变量读取）
            ssh_host = os.getenv('SSH_HOST', '')
            ssh_port = int(os.getenv('SSH_PORT', '7022'))
            ssh_user = os.getenv('SSH_USER', 'tunnel')
            ssh_key_path = os.getenv('SSH_KEY_PATH', '')
            
            # 远程MongoDB服务器信息（SSH隧道的目标）
            remote_mongo_host = os.getenv('SSH_REMOTE_HOST', '127.0.0.1')
            remote_mongo_port = int(os.getenv('SSH_REMOTE_PORT', '27017'))
            
            # MongoDB配置（从环境变量读取）
            mongo_host = os.getenv('MONGO_HOST', '127.0.0.1')
            mongo_port = int(os.getenv('MONGO_PORT', '27017'))
            mongo_db = os.getenv('MONGO_DB', 'news')
            mongo_collection = os.getenv('MONGO_COLLECTION', 'articles')
            mongo_user = os.getenv('MONGO_USER', '')
            mongo_password = os.getenv('MONGO_PASSWORD', '')
            mongo_authsource = os.getenv('MONGO_AUTHSOURCE', 'admin')
            
            self.logger.info(f"[DEBUG] SSH配置: {ssh_user}@{ssh_host}:{ssh_port}")
            self.logger.info(f"[DEBUG] SSH密钥: {ssh_key_path}")
            self.logger.info(f"[DEBUG] 远程MongoDB: {remote_mongo_host}:{remote_mongo_port}")
            self.logger.info(f"[DEBUG] 本地隧道端口: {mongo_port}")
            self.logger.info(f"[DEBUG] 目标数据库: {mongo_db}")
            self.logger.info(f"[DEBUG] 目标集合: {mongo_collection}")
            self.logger.info(f"[DEBUG] MongoDB用户: {mongo_user}")
            self.logger.info(f"[DEBUG] MongoDB认证源: {mongo_authsource}")
            
            # 启动SSH隧道
            self.logger.info(f"[DEBUG] 开始启动SSH隧道...")
            tunnel_success = self.ssh_tunnel.start_tunnel(
                ssh_host=ssh_host,
                ssh_port=ssh_port,
                ssh_user=ssh_user,
                ssh_key_path=ssh_key_path,
                remote_host=remote_mongo_host,
                remote_port=remote_mongo_port,
                local_port=mongo_port,
                logger=self.logger
            )
            
            if not tunnel_success:
                self.logger.error("[ERROR] SSH隧道启动失败，无法连接MongoDB")
                self.mongodb_client = None
                self.db_articles = None
                self.collection_articles = None
                return
            
            self.logger.info(f"[DEBUG] SSH隧道启动成功，开始连接MongoDB...")
            
            # 再次检查SSH进程状态
            if self.ssh_tunnel.process.poll() is not None:
                self.logger.error(f"[ERROR] SSH隧道进程意外退出！")
                self.mongodb_client = None
                self.db_articles = None
                self.collection_articles = None
                return
            
            # 构建MongoDB连接字符串
            if mongo_user and mongo_password:
                encoded_username = quote_plus(mongo_user)
                encoded_password = quote_plus(mongo_password)
                connection_string = f"mongodb://{encoded_username}:{encoded_password}@{mongo_host}:{mongo_port}/{mongo_db}?authSource={mongo_authsource}"
                self.logger.info(f"[DEBUG] MongoDB连接字符串: mongodb://{mongo_user}:***@{mongo_host}:{mongo_port}/{mongo_db}?authSource={mongo_authsource}")
            else:
                connection_string = f"mongodb://{mongo_host}:{mongo_port}/{mongo_db}"
                self.logger.info(f"[DEBUG] MongoDB连接字符串: mongodb://{mongo_host}:{mongo_port}/{mongo_db}")
            
            # 连接MongoDB
            self.logger.info(f"[DEBUG] 创建MongoDB客户端...")
            self.mongodb_client = pymongo.MongoClient(
                connection_string,
                serverSelectionTimeoutMS=8000,
                socketTimeoutMS=8000
            )
            
            # 测试连接
            self.logger.info(f"[DEBUG] 测试MongoDB连接...")
            self.mongodb_client.admin.command('ping')
            self.logger.info("[OK] MongoDB连接成功!")
            
            # 设置数据库和集合
            self.logger.info(f"[DEBUG] 设置数据库和集合...")
            self.db_articles = self.mongodb_client[mongo_db]
            self.collection_articles = self.db_articles[mongo_collection]
            
            self.logger.info(f"[OK] 数据库: {self.db_articles.name}")
            self.logger.info(f"[OK] 集合: {self.collection_articles.name}")
            
            # 测试查询
            self.logger.info(f"[DEBUG] 测试查询Guardian文章...")
            count = self.collection_articles.count_documents({'publisher': 'The Guardian'})
            self.logger.info(f"[OK] 数据库中Guardian文章数量: {count}")
            
        except Exception as e:
            self.logger.error(f"[ERROR] MongoDB连接失败: {e}")
            self.logger.error("[ERROR] 将只使用本地文件存储")
            import traceback
            self.logger.error(traceback.format_exc())
            self.mongodb_client = None
            self.db_articles = None
            self.collection_articles = None
            # 不在这里关闭SSH隧道，让程序继续运行

    def load_existing_articles(self) -> List[Dict]:
        """从本地文件加载现有文章"""
        if not os.path.exists(self.data_file):
            return []
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                articles = json.load(f)
                if isinstance(articles, list):
                    return articles
                else:
                    print("警告：文件格式不正确，将重新开始")
                    return []
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"警告：文件读取失败 {e}，将重新开始")
            return []

    def get_existing_urls(self) -> set:
        """获取现有文章的URL集合，用于去重 - 只从数据库获取"""
        db_urls = set()
        if self.collection_articles is not None:
            try:
                # 查询数据库中publisher为"The Guardian"的文章
                guardian_articles = self.collection_articles.find(
                    {'publisher': 'The Guardian'}, 
                    {'url': 1, '_id': 0}
                )
                db_urls = {doc['url'] for doc in guardian_articles}
                print(f"从数据库获取到 {len(db_urls)} 个Guardian文章URL用于去重")
            except Exception as e:
                print(f"从数据库获取URL失败: {e}")
        else:
            print("数据库连接不可用，无法进行去重检查")
        
        return db_urls

    def save_articles(self, new_articles: List[Dict]) -> bool:
        """保存文章到本地文件 - 各自查重各塞各的"""
        if not new_articles:
            self.logger.info("没有新文章需要保存")
            return True
            
        try:
            # 从本地文件读取已有文章
            local_existing_articles = []
            local_existing_urls = set()
            if os.path.exists(self.data_file):
                try:
                    with open(self.data_file, 'r', encoding='utf-8') as f:
                        local_existing_articles = json.load(f)
                        local_existing_urls = {article['url'] for article in local_existing_articles if article.get('url')}
                    self.logger.info(f"从本地文件读取到 {len(local_existing_articles)} 篇文章")
                except Exception as e:
                    self.logger.error(f"读取本地文件失败: {e}")
                    local_existing_articles = []
                    local_existing_urls = set()
            
            # 过滤出本地文件中不存在的新文章
            local_new_articles = [article for article in new_articles if article['url'] not in local_existing_urls]
            
            self.logger.info(f"本次获取 {len(new_articles)} 篇新文章（相对数据库）")
            self.logger.info(f"其中本地新增 {len(local_new_articles)} 篇（相对本地文件）")
            
            if not local_new_articles:
                self.logger.info("所有新文章本地都已存在，无需更新本地文件")
                print("本地文件无需更新（新文章本地都已存在）")
                return True
            
            # 将本地新文章添加到本地文章列表的最前面（最新）
            all_articles = local_new_articles + local_existing_articles
            
            # 保存总文件
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(all_articles, f, indent=2, ensure_ascii=False)
            
            # 创建新增文件（只包含本次本地新增的文章）
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_articles_file = os.path.join(self.data_dir, f"guardian_articles_new_{timestamp}.json")
            with open(new_articles_file, 'w', encoding='utf-8') as f:
                json.dump(local_new_articles, f, indent=2, ensure_ascii=False)
            
            # 更新内存中的数据
            self.existing_articles = all_articles
            
            self.logger.info(f"本地文件保存完成:")
            self.logger.info(f"  总文件: {self.data_file} (总计 {len(all_articles)} 篇文章)")
            self.logger.info(f"  新增文章文件: {new_articles_file} (本次本地新增 {len(local_new_articles)} 篇文章)")
            
            print(f"本地文件保存完成")
            print(f"总文件: {self.data_file} (总计 {len(all_articles)} 篇文章)")
            print(f"新增文章文件: {new_articles_file} (本次本地新增 {len(local_new_articles)} 篇文章)")
            return True
            
        except Exception as e:
            self.logger.error(f"本地文件保存失败: {e}")
            print(f"保存失败: {e}")
            return False

    def save_article_to_mongodb(self, article_data: Dict) -> bool:
        """保存文章到MongoDB"""
        if self.collection_articles is None:
            print("MongoDB连接不可用，跳过数据库保存")
            return False
        
        if not article_data:
            print("文章数据为空，无法保存到数据库")
            return False
        
        try:
            # 添加MongoDB元数据
            article_data['mongodb_meta'] = {
                'inserted_at': datetime.now().isoformat() + 'Z',
                'version': '1.0',
                'source': 'guardian_api'
            }
            
            # 使用upsert避免重复（通过URL判断）
            result = self.collection_articles.update_one(
                {'url': article_data['url']},
                {'$set': article_data},
                upsert=True
            )
            
            if result.upserted_id:
                print(f"  [DB] 新文章已保存到MongoDB: {article_data.get('title', 'N/A')[:50]}...")
            elif result.modified_count > 0:
                print(f"  [DB] 文章已更新到MongoDB: {article_data.get('title', 'N/A')[:50]}...")
            else:
                print(f"  [DB] 文章已存在于MongoDB: {article_data.get('title', 'N/A')[:50]}...")
            
            return True
            
        except Exception as e:
            print(f"保存到MongoDB失败: {e}")
            return False

    def batch_save_to_mongodb(self, articles: List[Dict]) -> int:
        """批量保存文章到MongoDB"""
        if self.collection_articles is None or not articles:
            return 0
        
        saved_count = 0
        for article in articles:
            if self.save_article_to_mongodb(article):
                saved_count += 1
        
        print(f"批量保存完成: {saved_count}/{len(articles)} 篇保存到MongoDB")
        return saved_count

    def format_article(self, article_data: Dict) -> Dict:
        """将Guardian API数据转换为标准格式"""
        try:
            # 基本信息提取
            fields = article_data.get('fields', {})
            tags = article_data.get('tags', [])
            
            # 提取作者信息
            author = fields.get('byline', '')
            if not author:
                contributors = [tag['webTitle'] for tag in tags if tag['type'] == 'contributor']
                author = ', '.join(contributors)
            
            # 从API数据中提取标签
            tag_names = [tag['webTitle'] for tag in tags if tag['type'] == 'keyword']
            
            # 使用bodyText作为content
            body_text = fields.get('bodyText', '')
            content_array = []
            if body_text:
                paragraphs = [p.strip() for p in body_text.split('\n') if p.strip()]
                for i, paragraph in enumerate(paragraphs):
                    content_array.append({
                        "subtitle": f"Paragraph {i+1}",
                        "text": paragraph
                    })
            
            # 生成内容哈希
            content_hash = hashlib.md5(body_text.encode()).hexdigest()
            
            # 构建目标格式
            result = {
                "url": article_data['webUrl'],
                "title": article_data['webTitle'],
                "publisher": "The Guardian",
                "author": author,
                "date": article_data['webPublicationDate'],
                "fetch_date": datetime.now().isoformat() + 'Z',
                "language": fields.get('lang', 'en'),
                "location": "",  # 空着，等大模型解析
                "source_section": article_data.get('sectionName', ''),
                "description": "",  # 空着
                "headline": fields.get('headline', ''),
                "trailText": fields.get('trailText', ''),
                "tags": tag_names,
                "entities": {
                    "persons": [],      # 空着，等大模型解析
                    "organizations": [], # 空着，等大模型解析
                    "locations": []     # 空着，等大模型解析
                },
                "categories": [],  # 空着
                "document": {
                    "title": article_data['webTitle'],
                    "content": content_array,
                    "raw_html": ""  # 空着，因为是API不是爬虫
                },
                "crawler_meta": {
                    "status_code": 200,
                    "response_time_ms": 0,  # 批量处理，无单独计时
                    "raw_html_length": 0,   # 空着，因为是API
                    "hash": content_hash
                }
            }
            
            return result
            
        except Exception as e:
            print(f"格式化文章失败 {article_data.get('id', 'unknown')}: {e}")
            return None

    def fetch_articles_by_pages(self, start_page: int = None, end_page: int = None, 
                                page_size: int = None, request_delay: float = None, 
                                request_timeout: int = None) -> List[Dict]:
        """获取指定页数范围的文章，每篇都和数据库比对去重
        
        Args:
            start_page: 起始页（从1开始），默认从环境变量读取
            end_page: 结束页（包含），默认从环境变量读取
            page_size: 每页文章数，默认从环境变量读取
            request_delay: 请求延迟（秒），默认从环境变量读取
            request_timeout: 请求超时（秒），默认从环境变量读取
            
        Examples:
            fetch_articles_by_pages(1, 1)  # 只获取第1页
            fetch_articles_by_pages(1, 7)  # 获取第1-7页
            fetch_articles_by_pages(3, 5)  # 获取第3-5页
        """
        # 从环境变量或参数获取配置
        start_page = start_page if start_page is not None else int(os.getenv('GUARDIAN_START_PAGE', 1))
        end_page = end_page if end_page is not None else int(os.getenv('GUARDIAN_END_PAGE', 1))
        page_size = page_size if page_size is not None else int(os.getenv('GUARDIAN_PAGE_SIZE', 200))
        request_delay = request_delay if request_delay is not None else float(os.getenv('GUARDIAN_REQUEST_DELAY', 0.1))
        request_timeout = request_timeout if request_timeout is not None else int(os.getenv('GUARDIAN_REQUEST_TIMEOUT', 30))
        
        all_new_articles = []
        total_pages_to_fetch = end_page - start_page + 1
        
        print(f"获取第 {start_page}-{end_page} 页文章（共 {total_pages_to_fetch} 页，每页{page_size}篇）")
        print(f"只获取类型: article（普通文章）和 feature（专题文章）")
        print(f"去重方式: 每篇文章都和现有 {len(self.existing_urls)} 个URL比对")
        
        for current_page in range(start_page, end_page + 1):
            params = {
                'order-by': 'newest',
                'show-fields': 'all',  # 获取所有字段包括正文
                'show-tags': 'all',    # 获取所有标签
                'page-size': page_size,
                'page': current_page,
                'api-key': self.api_key,
                'format': 'json'
            }
            
            print(f"\n第 {current_page} 页:")
            
            try:
                # 添加延迟避免触及速率限制
                time.sleep(request_delay)
                
                response = requests.get(f"{self.base_url}/search", params=params, timeout=request_timeout)
                response.raise_for_status()
                
                data = response.json()
                
                if data['response']['status'] != 'ok':
                    print(f"API返回错误状态: {data['response']['status']}")
                    break
                
                results = data['response']['results']
                total_pages = data['response']['pages']
                total_results = data['response']['total']
                
                print(f"第 {current_page}/{total_pages} 页，本页 {len(results)} 篇内容，总计 {total_results} 篇")
                
                if not results:
                    print("没有内容")
                    continue
                
                # 处理当前页的文章
                page_filtered = 0
                page_duplicates = 0
                page_new_articles = []
                
                for i, article_data in enumerate(results):
                    article_title = article_data['webTitle']
                    article_type = article_data.get('type', 'unknown')
                    article_url = article_data['webUrl']
                    
                    # 只要普通文章和专题文章，过滤其他类型
                    if article_type not in ['article', 'feature']:
                        page_filtered += 1
                        print(f"  内容 {i+1}/{len(results)}: [{article_type}] {article_title[:40]}... [过滤]")
                        continue
                    
                    # 检查URL是否已存在于数据库中
                    if article_url in self.existing_urls:
                        page_duplicates += 1
                        print(f"  文章 {i+1}/{len(results)}: {article_title[:40]}... [重复]")
                        continue
                    
                    # 格式化新文章
                    print(f"  文章 {i+1}/{len(results)}: {article_title[:40]}... [新文章]")
                    formatted_article = self.format_article(article_data)
                    
                    if formatted_article:
                        page_new_articles.append(formatted_article)
                        # 立即添加到已存在URL集合，避免重复
                        self.existing_urls.add(article_url)
                        print(f"    成功: {formatted_article['title'][:40]}...")
                    else:
                        print(f"    失败: 格式化错误")
                
                # 将当前页的新文章添加到总列表
                all_new_articles.extend(page_new_articles)
                print(f"  本页统计: 新增 {len(page_new_articles)} 篇，重复 {page_duplicates} 篇，过滤 {page_filtered} 篇")
                
                # 检查是否超出总页数
                if current_page >= total_pages:
                    print(f"已到达最后一页 ({total_pages})")
                    break
                
            except requests.RequestException as e:
                retry_delay = int(os.getenv('GUARDIAN_RETRY_DELAY', 5))
                print(f"网络请求失败: {e}")
                print(f"等待{retry_delay}秒后重试...")
                time.sleep(retry_delay)
                continue
            except json.JSONDecodeError as e:
                print(f"JSON解析错误: {e}")
                break
            except Exception as e:
                print(f"未知错误: {e}")
                break
        
        print(f"\n总共获取 {len(all_new_articles)} 篇新文章（第{start_page}-{end_page}页，仅article类型）")
        return all_new_articles

    def get_statistics(self) -> Dict:
        """获取统计信息 - 从数据库获取"""
        if self.collection_articles is None:
            return {"total": 0, "sections": {}, "latest_date": None}
        
        try:
            # 从数据库查询Guardian文章统计
            guardian_articles = list(self.collection_articles.find(
                {'publisher': 'The Guardian'}, 
                {'source_section': 1, 'date': 1, '_id': 0}
            ))
            
            if not guardian_articles:
                return {"total": 0, "sections": {}, "latest_date": None}
            
            # 按版块统计
            sections = {}
            dates = []
            
            for article in guardian_articles:
                section = article.get('source_section', '未知')
                sections[section] = sections.get(section, 0) + 1
                
                if article.get('date'):
                    dates.append(article['date'])
            
            # 最新文章日期
            latest_date = max(dates) if dates else None
            
            return {
                "total": len(guardian_articles),
                "sections": dict(sorted(sections.items(), key=lambda x: x[1], reverse=True)),
                "latest_date": latest_date
            }
        except Exception as e:
            print(f"获取统计信息失败: {e}")
            return {"total": 0, "sections": {}, "latest_date": None}

def main():
    print("=" * 60)
    print("Guardian新闻爬虫 - 可设置页数范围版本")
    print("=" * 60)
    
    # 创建爬虫实例（所有配置从环境变量读取）
    try:
        crawler = GuardianCrawler()
        crawler.logger.info("Guardian爬虫实例创建成功")
    except ValueError as e:
        print(f"错误: {e}")
        return
    
    # 显示现有统计
    stats = crawler.get_statistics()
    print(f"现有文章统计:")
    print(f"- 总文章数: {stats['total']}")
    print(f"- 最新文章日期: {stats['latest_date']}")
    
    if stats['sections']:
        print("- 版块分布（前5名）:")
        for section, count in list(stats['sections'].items())[:5]:
            print(f"  {section}: {count} 篇")











    
    # 从环境变量读取页数范围配置
    start_page = int(os.getenv('GUARDIAN_START_PAGE', 1))
    end_page = int(os.getenv('GUARDIAN_END_PAGE', 1))
    
    crawler.logger.info(f"开始获取新文章（第{start_page}-{end_page}页）")
    print(f"\n开始获取新文章（第{start_page}-{end_page}页）...")
    new_articles = crawler.fetch_articles_by_pages()
    
    crawler.logger.info(f"本次获取结果: 新文章数量 {len(new_articles)}")
    print(f"\n本次获取结果:")
    print(f"- 新文章数量: {len(new_articles)}")
    
    # 保存文章
    if new_articles:
        crawler.logger.info("开始保存新文章")
        
        # 保存到本地文件
        local_save_success = crawler.save_articles(new_articles)
        
        # 保存到MongoDB
        db_save_count = crawler.batch_save_to_mongodb(new_articles)
        
        if local_save_success:
            crawler.logger.info("本地文件保存成功")
            print(f"- 本地保存状态: 成功")
        else:
            crawler.logger.error("本地文件保存失败")
            print(f"- 本地保存状态: 失败")
            
        crawler.logger.info(f"数据库保存结果: {db_save_count}/{len(new_articles)} 篇成功")
        print(f"- 数据库保存状态: {db_save_count}/{len(new_articles)} 篇成功")
        
        # 更新统计
        final_stats = crawler.get_statistics()
        crawler.logger.info(f"最终统计: 数据库中Guardian文章总数 {final_stats['total']} 篇")
        print(f"- 数据库中Guardian文章总数: {final_stats['total']} (本次新增 {len(new_articles)} 篇)")
        
        # 显示最新几篇文章
        print(f"\n本次新增的文章:")
        for i, article in enumerate(new_articles[:5], 1):
            pub_date = article['date'][:10] if article.get('date') else '未知'
            title = article['title'][:60] + ('...' if len(article['title']) > 60 else '')
            print(f"{i}. [{pub_date}] {title}")
        
        if len(new_articles) > 5:
            print(f"... 还有 {len(new_articles) - 5} 篇文章")
            
    else:
        crawler.logger.info("没有获取到新文章（没有更新或遇到重复）")
        print("- 没有获取到新文章（没有更新或遇到重复）")
    
    # 关闭MongoDB连接和SSH隧道
    if crawler.mongodb_client:
        crawler.mongodb_client.close()
        crawler.logger.info("MongoDB连接已关闭")
        print("MongoDB连接已关闭")
    
    # 关闭SSH隧道
    crawler.ssh_tunnel.stop_tunnel()
    
    crawler.logger.info("=" * 60)
    crawler.logger.info("Guardian爬虫任务完成")
    crawler.logger.info("=" * 60)
    print(f"\n爬虫任务完成!")


if __name__ == "__main__":
    main()
