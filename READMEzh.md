# Vibe Chat

简体中文说明文档 — 基于 Flask + Socket.IO 的实时聊天应用样例。

**项目简介**

Vibe Chat 是一个轻量级的即时聊天服务，支持：全局聊天室、私聊、群组（创建/邀请/权限管理）、好友请求、文件/图片上传、用户资料与头像管理，以及未读消息/@提及通知等功能。后端使用 Flask + Flask-SocketIO，数据持久化使用 PostgreSQL（通过 SQLAlchemy 原生 SQL 语句）。

**主要特性**
- 实时消息（全局/私聊/群聊）
- 群组管理：创建、邀请、移除、转让、管理员权限
- 好友系统：请求、接受、拒绝、移除
- 文件/图片上传（Pillow 处理与类型校验）
- 用户资料页、头像上传与生成功能
- CSRF 保护与速率限制（Flask-WTF / Flask-Limiter）

**技术栈**
- Python 3.9+
- Flask
- Flask-SocketIO
- Flask-Login
- Flask-WTF
- Flask-Limiter
- SQLAlchemy (使用原生 SQL 与 PostgreSQL 特性)
- Pillow（图片处理）

**先决条件**
- PostgreSQL 实例（推荐）
- 在本机或虚拟环境中安装 Python 3.9+
- 推荐安装 `eventlet` 或 `gevent` 以改善 SocketIO 并发性能

**环境变量**
在项目根目录（FinalProject）创建一个 `.env` 文件，或在运行环境中设置：

```
DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DBNAME
SECRET_KEY=your_secret_key_here
```

注意：`app.py` 会在启动时检查 `DATABASE_URL` 和 `SECRET_KEY`，若未设置将抛出错误。

**安装依赖（示例）**

建议在虚拟环境中执行：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install flask flask-socketio flask-login flask-wtf flask-limiter flask-sqlalchemy python-dotenv pillow psycopg2-binary eventlet
```

（如果使用 Windows，优先用 `pip` 安装 `psycopg2-binary`，或使用 `wheel`）

**初始化数据库**

项目中使用了若干表（`users`, `friends`, `groups`, `group_members`, `messages`, `user_message_status` 等）。下面给出一个最小化示例 SQL（请根据需要扩展索引与字段类型）：

```sql
-- PostgreSQL 最简示例表结构（示意）
CREATE TABLE users (
	id SERIAL PRIMARY KEY,
	username TEXT UNIQUE NOT NULL,
	password_hash TEXT NOT NULL,
	avatar_url TEXT,
	bio TEXT,
	is_active BOOLEAN DEFAULT TRUE,
	created_at TIMESTAMP DEFAULT NOW(),
	last_login TIMESTAMP
);

CREATE TABLE friends (
	id SERIAL PRIMARY KEY,
	outgoing_id INT NOT NULL,
	incoming_id INT NOT NULL,
	status TEXT NOT NULL,
	created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE groups (
	id SERIAL PRIMARY KEY,
	group_name TEXT NOT NULL,
	creator_id INT NOT NULL,
	created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE group_members (
	id SERIAL PRIMARY KEY,
	chat_id TEXT NOT NULL,
	user_id INT NOT NULL,
	role TEXT DEFAULT 'member',
	alias TEXT,
	joined_at TIMESTAMP DEFAULT NOW(),
	UNIQUE (chat_id, user_id)
);

CREATE TABLE messages (
	id SERIAL PRIMARY KEY,
	chat_id TEXT NOT NULL,
	chat_type TEXT NOT NULL,
	sender_id INT NOT NULL,
	msg_type TEXT DEFAULT 'text',
	content TEXT,
	reply_to_id INT,
	created_at TIMESTAMP DEFAULT NOW(),
	deleted_at TIMESTAMP,
	deleted_by INT
);

CREATE TABLE user_message_status (
	id SERIAL PRIMARY KEY,
	user_id INT NOT NULL,
	message_id INT NOT NULL,
	chat_id TEXT NOT NULL,
	chat_type TEXT NOT NULL,
	is_read BOOLEAN DEFAULT FALSE,
	read_at TIMESTAMP,
	is_deleted BOOLEAN DEFAULT FALSE,
	deleted_at TIMESTAMP,
	mention_type TEXT,
	is_mentioned BOOLEAN DEFAULT FALSE,
	UNIQUE (user_id, message_id)
);
```

将上述 SQL 应用到你的 PostgreSQL 数据库（例如使用 psql 或数据库管理工具）。项目没有内置迁移文件；建议使用 Alembic 或手动维护 schema。

**运行（本地开发）**

1. 激活虚拟环境并安装依赖。
2. 设置 `.env` 中的 `DATABASE_URL` 与 `SECRET_KEY`。
3. 启动应用：

```bash
# 使用 eventlet（推荐）
python -m pip install eventlet
python -c "import eventlet; import app;"
# 或直接运行
python app.py
```

默认会通过 Flask-SocketIO 启动服务。若需要在生产环境中部署，建议使用 Gunicorn + eventlet/gevent，并在反向代理（如 Nginx）后面运行以正确处理 HTTPS 与 Cookie 设置。

**配置与注意事项**
- `SESSION_COOKIE_SECURE = True` 在 `app.py` 中被启用；在没有正确配置 HTTPS 代理（例如未设置 `X-Forwarded-Proto`）时会导致 session/csrf 问题。
- 文件上传会保存到 `static/uploads/`，单个文件大小上限由 `app.config['MAX_CONTENT_LENGTH']` 控制（默认为 16MB）。
- `app.py` 中使用了一些 PostgreSQL 特有的语法（例如 `COUNT(...)::int`），因此推荐使用 PostgreSQL。
- 请确保 `.env` 不要提交到版本库，包含敏感密钥。

**前端**
模板位于 `templates/`，使用轻量前端逻辑（在 `chat.html` 中可见）。静态文件与上传资源位于 `static/`。

**贡献**
欢迎提交 issue 或 PR。若要本地运行完整体验，请先准备 PostgreSQL 并导入上面的最小 schema，然后创建若干用户进行测试。

**联系方式**
如需帮助，请在仓库中打开 Issue 或联系维护者。

