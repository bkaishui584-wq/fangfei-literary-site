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

`render.yaml` 默认使用免费 Web Service，SQLite 位于服务实例的临时磁盘中。实例不被重建时可以保留数据；Render 重建、迁移或重新部署实例后，临时磁盘中的数据可能丢失。长期保存需要使用 Render 持久化磁盘（通常为付费）或其他持久化数据库，并把 `DATABASE_PATH` 指向对应存储路径。

## 环境变量

- `FLASK_ENV=production`
- `DATABASE_PATH=/var/data/fangfei.sqlite3`
- `ADMIN_USERNAME=玉年`
- `ADMIN_DISPLAY_NAME=玉年`
- `ADMIN_PASSWORD=仅通过安全环境变量提供`
- `ADMIN_UPDATE_FROM=旧用户名`：仅用于一次性管理员凭据迁移；匹配现有管理员后更新用户名和密码，迁移完成即可删除

不要把真实密码、Token 或 API Key 写入仓库。

## 数据与权限

业务数据保存在服务端 SQLite 数据库。前端只负责展示，认证、角色和管理操作由服务端校验。当前 T01 已完成基础架构、用户注册登录、Session、CSRF、管理员权限、作品、评论、点赞、收藏、关注、私信、举报和公告的服务端化迁移。

浏览器旧版 `localStorage` 数据不会被自动删除，但 T01 不自动导入这些数据，避免把无身份归属的数据写入错误账号。
