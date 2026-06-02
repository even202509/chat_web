# Vibe Chat
#### Video Demo:  https://youtu.be/OV26dBNKZ8s?si=OqM94Pug_6bIImZJ
#### Description

English README — A simple Flask + Vue + Socket.IO real-time chat example.

Project Overview

Vibe Chat is a lightweight real-time chat application that supports: a global chat room, private messages, groups (create/invite/permission management), friend requests, file/image uploads, user profiles and avatars, unread message counts and @mentions. The backend uses Flask + Flask-SocketIO and persists data to PostgreSQL via SQLAlchemy (using raw SQL queries).

Key Features

- Real-time messaging (global / private / group)
- Group management: create, invite, remove, transfer ownership, admin roles
- Friend system: send / accept / reject / remove requests
- File and image uploads with server-side validation and normalization (Pillow)
- User profiles and avatar upload
- CSRF protection and rate limiting (Flask-WTF, Flask-Limiter)

Tech Stack

- Python 3.9+
- Flask
- Flask-SocketIO
- Flask-Login
- Flask-WTF
- Flask-Limiter
- SQLAlchemy (native SQL targeting PostgreSQL)
- Pillow

Prerequisites

- PostgreSQL instance (recommended)
- Python 3.9+ and virtual environment
- Optional: `eventlet` or `gevent` for improved SocketIO concurrency

Environment Variables

Create a `.env` file at the project root (`FinalProject`) or set the following environment variables:

```
DATABASE_URL=postgresql://USER:PASS@HOST:PORT/DBNAME
SECRET_KEY=your_secret_key_here
```

`app.py` requires `DATABASE_URL` and `SECRET_KEY` at startup and will raise an error if they're not set.

Install Dependencies

Recommended in a virtualenv:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

Database Initialization

The app expects tables such as `users`, `friends`, `groups`, `group_members`, `messages`, and `user_message_status`. Below is a minimal illustrative PostgreSQL schema — adapt it for your needs and add indexes/constraints as required:

```sql
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

Apply the SQL to your PostgreSQL instance (for example via `psql`). The project does not include migrations; consider using Alembic for schema management.

Run (development)

1. Activate the virtual environment and install dependencies.
2. Set `DATABASE_URL` and `SECRET_KEY` in `.env`.
3. Start the app:

```bash
# install eventlet if needed
python -m pip install eventlet
python -c "import eventlet; import app"
# or
python app.py
```

For production, run behind a reverse proxy (Nginx) and use Gunicorn with `eventlet`/`gevent` workers.

Notes & Configuration

- `SESSION_COOKIE_SECURE = True` is enabled in `app.py`. Ensure `X-Forwarded-Proto` is forwarded by your proxy or configure `ProxyFix` to avoid session/CSRF issues.
- Uploaded files are stored in `static/uploads/`. Max upload size is set by `app.config['MAX_CONTENT_LENGTH']` (default 16MB).
- Some SQL in `app.py` uses PostgreSQL-specific syntax (e.g. `COUNT(...)::int`). PostgreSQL is the recommended DB.
- Keep `.env` out of version control.

Frontend

Templates are in the `templates/` directory (see `templates/chat.html`). Static assets live under `static/`.

Contributing

Issues and pull requests are welcome. To test locally, prepare a PostgreSQL database using the example schema and create test users.

Support

Open an issue or contact the maintainer for help.

