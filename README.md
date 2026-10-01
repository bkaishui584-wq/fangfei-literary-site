# 芳菲文学社

芳菲文学社是一个独立的文学作品创作、阅读与交流平台，与 ProjectHub 分开。

## 当前技术栈

- Flask
- SQLite
- 原生 HTML、CSS、JavaScript
- 服务端 Session 和 CSRF 校验

## 本地运行

```powershell
python -m pip install -r requirements.txt
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="请设置一个至少 12 位的强密码"
python app.py
```

访问 `http://127.0.0.1:8787/`。

生产环境必须设置 `ADMIN_PASSWORD`。首次启动只创建一次管理员账号，后续启动不会重设已有管理员密码。

## Render 部署

`render.yaml` 默认仍保留 SQLite 路径，旧部署不会因为代码更新直接改变数据源。生产环境长期保存请添加 Render PostgreSQL，并把 `DATABASE_URL` 配置为数据库连接串；代码会优先使用 PostgreSQL。若暂时继续使用 SQLite，需要给 Web Service 挂载持久化磁盘，并把 `DATABASE_PATH` 指向磁盘路径。

SQLite 迁移到 PostgreSQL 前先生成备份，再运行 `python migrate_to_postgres.py --target "postgresql://..."`。脚本只新增或跳过冲突记录，不执行 DROP、TRUNCATE 或清空表。

## 环境变量

- `FLASK_ENV=production`
- `DATABASE_PATH=/var/data/fangfei.sqlite3`：SQLite 回退路径
- `DATABASE_URL=postgresql://...`：配置后优先使用 PostgreSQL
- `STORAGE_PATH=/var/data`：头像等本地文件的持久化目录
- `ADMIN_USERNAME=玉年`
- `ADMIN_DISPLAY_NAME=玉年`
- `ADMIN_PASSWORD=仅通过安全环境变量提供`
- `ADMIN_UPDATE_FROM=旧用户名`：仅用于一次性管理员凭据迁移；匹配现有管理员后更新用户名和密码，迁移完成即可删除

不要把真实密码、Token 或 API Key 写入仓库。

## 数据与权限

业务数据保存在服务端 SQLite 或 PostgreSQL。前端只负责展示，认证、角色和管理操作由服务端校验。头像文件保存在 `STORAGE_PATH/avatars`，数据库只记录 `/avatars/<随机文件名>`，迁移时需要同时迁移该目录。

投稿提交后进入规则型 Agent 审核：LOW 自动发布，其余等级转人工复核；Agent 异常一律回到人工复核，不会自动发布。Agent 记录只保存运行状态、风险等级、建议和耗时，不保存系统提示词、密钥或敏感配置。

浏览器旧版 `localStorage` 数据不会被自动删除，但 T01 不自动导入这些数据，避免把无身份归属的数据写入错误账号。
