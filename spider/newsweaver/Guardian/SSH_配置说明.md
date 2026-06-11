# Guardian爬虫SSH隧道配置说明

## 重要更新

程序现在**自动管理SSH隧道**，不再需要在PowerShell中手动运行`ssh`命令！

SSH隧道会在程序启动时自动建立，程序结束时自动关闭，避免了外部PowerShell窗口断开导致的问题。

## 环境变量配置

请在Guardian目录下创建`.env`文件，包含以下配置：

```env
# Guardian API 配置
GUARDIAN_API_KEY=<guardian-api-key>
GUARDIAN_BASE_URL=https://content.guardianapis.com
GUARDIAN_START_PAGE=1
GUARDIAN_END_PAGE=1

# SSH隧道配置
SSH_HOST=example.com
SSH_PORT=7022
SSH_USER=tunnel
SSH_KEY_PATH=<path-to-private-key>

# MongoDB配置（通过SSH隧道）
MONGO_HOST=127.0.0.1
MONGO_PORT=37017
MONGO_DB=news
MONGO_COLLECTION=articles
MONGO_USER=admin
MONGO_PASSWORD=<mongo-password>
MONGO_AUTHSOURCE=admin
```

## SSH隧道命令

程序内部使用的SSH命令等同于：
```bash
ssh -vv -N -T -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:37017:127.0.0.1:27017 \
  -p 7022 -i "<path-to-private-key>" \
  tunnel@example.com
```

## 工作原理

1. **程序启动**: 自动建立SSH隧道 `example.com:7022` -> `127.0.0.1:37017`
2. **MongoDB连接**: 通过本地隧道端口 `127.0.0.1:37017` 连接到远程 MongoDB
3. **程序结束**: 自动关闭SSH隧道

## 优势

✅ **自动管理**: 无需手动维护PowerShell窗口  
✅ **稳定连接**: 避免外部SSH进程断开的问题  
✅ **调试输出**: 使用 `-vv` 参数提供详细的SSH连接信息  
✅ **资源清理**: 程序结束时确保隧道关闭

## 注意事项

- 确保SSH密钥文件路径正确（支持正斜杠`/`和反斜杠`\`）
- 确保本地端口 `37017` 空闲（不要手动运行SSH命令占用此端口）
- 如遇连接问题，查看日志文件中的SSH调试输出
