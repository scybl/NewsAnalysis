# Bloomberg 文章爬虫

使用HTTP/2完全模拟真实浏览器请求，从Chrome获取Cookie，爬取Bloomberg文章。

---

## ⏰ 定时运行

**运行时间：** 每小时10分触发，延迟0-10分钟启动（8:10-20:10，共13次/天）
- 例如：8:10-8:20, 9:10-9:20, 10:10-10:20... 20:10-20:20
- 每次爬16篇，预计16-40分钟完成
- 每篇文章间隔60-150秒

---

## ⚠️ 重要提醒

### Cookie状态检查
- **Cookie小于等于64个会认为未登录，程序会立即停止**
- 程序每篇文章前都会重新从Chrome获取最新Cookie
- Cookie数量不足会生成`warning_*.log`日志文件
- **请保持Chrome登录窗口开在前面，不要关闭**

### 数据一致性检查
- **本地和数据库不一致会生成warning**
- 程序会自动对比服务器和本地文件
- 新文章会同时保存到MongoDB和本地JSON

### Chrome窗口要求
- **必须保持Chrome打开**（调试端口9222）
- **必须保持登录状态**
- 建议窗口放在可见位置，不要最小化
- 窗口关闭会导致程序报错

### 其他注意事项
- **网络：** 需要稳定的网络连接
- **日志：** 定期检查logs目录，关注WARNING信息
- **备份：** 定期备份`bloomberg_articles.json`主文件
- **反爬虫：** 如遇403错误，检查Cookie是否过期，必要时重新登录

---

## 📋 功能说明

- 从Chrome实时获取Cookie（56+个）
- 使用HTTP/2协议（curl_cffi）
- 完全模拟真实浏览器指纹
- 解析文章并保存到MongoDB
- 支持批量爬取
- 自动标记URL状态

---

## 🚀 使用方法

### 1. 启动Chrome调试模式

```powershell
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\Administrator\chrome-debug"
```

### 2. 在Chrome中登录Bloomberg

打开 https://www.bloomberg.com/asia 并登录

### 3. 运行爬虫

```bash
cd Bloomberg/final_article
python ultimate_crawler.py
```

---

## 📂 文件说明

- `ultimate_crawler.py` - 主程序
- `data/bloomberg_articles.json` - 本地主文件（所有文章）
- `data/bloomberg_articles_new_*.json` - 增量文件（每次新增）
- `logs/` - 日志目录
- `logs/warning_*.log` - Cookie不足时的警告日志

---

## 🔍 HTTP/2请求特点

本脚本实现了与真实浏览器100%一致的HTTP/2请求：

1. **Protocol**: HTTP/2（不是HTTP/1.1）
2. **TLS**: 1.3 + Chrome指纹
3. **Headers**: 完全按照真实浏览器顺序
4. **Cookies**: 所有56+个Cookie（从Chrome实时获取）
5. **伪头部**: `:method`, `:authority`, `:scheme`, `:path`
6. **压缩**: gzip, deflate, br, zstd全支持

---

## 🔧 常见问题

### Q1: Cookie数量不足（≤64个）
**原因：** 未登录或Cookie过期
**解决：**
1. 在Chrome中重新登录Bloomberg
2. 确保窗口不要关闭
3. 查看`logs/warning_*.log`了解详情

### Q2: pychrome连接失败
**原因：** Chrome未以调试模式运行
**解决：**
1. 确保Chrome以`--remote-debugging-port=9222`启动
2. 检查端口9222是否被占用
3. 重启Chrome

### Q3: 仍然403错误
**原因：** Cookie过期或IP被封
**解决：**
1. 重新登录Bloomberg
2. 检查网络连接
3. 等待一段时间后重试

### Q4: curl_cffi安装失败
**解决：**
```powershell
pip install curl-cffi --prefer-binary
```
