# Bloomberg URL 获取器

从Bloomberg API批量获取最新文章URL并存储到MongoDB，自动去重。

---

## ⏰ 定时运行

**运行时间：** 每小时整点延迟2-10分钟启动（00:00-23:00，共24次/天）
- 例如：0:02-0:10, 1:02-1:10, 2:02-2:10... 23:02-23:10
- 避免整点高峰期，减少被检测概率

---

## ⚠️ 重要提醒

### 数据一致性检查
- **URL遇到本地和数据库不一样会生成warning**
- 程序会自动对比服务器和本地文件
- 如果发现不一致，会在日志中显示WARNING信息
- 新URL会同时保存到服务器和本地

### Chrome窗口位置
- **窗口位置：** (850, 0)
- **窗口大小：** 160x120
- 避开左上角800x600区域，避免遮挡login/logout窗口

### 其他注意事项
- **端口：** 使用9225端口，避免与final_article的9222端口冲突
- **网络：** 需要稳定的网络连接访问Bloomberg API
- **日志：** 定期检查logs目录，关注WARNING信息
- **备份：** 定期备份`bloomberg_all_urls.json`主文件

---

## 📋 功能说明

- 一次性获取25个最新文章URL
- 批量比对去重后存入MongoDB
- 自动启动Chrome（9225端口）
- 使用Chrome DevTools Protocol获取Cookie
- 直接调用Bloomberg API：`/lineup-next/api/stories`
- 只接受`/news/articles/`的文章URL
- 双重存储：MongoDB + 本地JSON文件

---

## 🚀 使用方法

```bash
cd Bloomberg/get_url
python bloomberg_url_fetcher.py
```

### 运行流程
1. 自动启动Chrome（9225端口）
2. 获取Cookie
3. 调用API获取文章列表
4. 过滤URL
5. 对比服务器和本地数据
6. 保存新URL到MongoDB和本地

---

## 📂 文件说明

- `bloomberg_url_fetcher.py` - 主程序
- `bloomberg_all_urls.json` - 本地主文件（累积所有URL）
- `bloomberg_urls_YYYYMMDD_HHMMSS.json` - 增量文件（每次新增）
- `logs/` - 日志目录

---

## 🔧 常见问题

### Q1: Chrome启动失败？
检查Chrome是否安装在标准路径：
- `C:\Program Files\Google\Chrome\Application\chrome.exe`
- `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`

### Q2: Cookie获取失败？
1. 确认Chrome已启动（端口9225）
2. 检查是否有多个Chrome实例占用端口

### Q3: 服务器和本地数据不一致？
- 查看日志中的WARNING信息
- 新URL会同时保存到两边，逐渐恢复一致

### Q4: API请求失败？
- 增加延迟时间
- 检查网络连接
