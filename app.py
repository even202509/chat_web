import os

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
)
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash

from tools import login_required, authenticated_only

app = Flask(__name__)


app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:314159@localhost/chat_web'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # type: ignore


class User(UserMixin):
    def __init__(self, id, username):
        self.id = str(id)
        self.username = username


@login_manager.user_loader
def load_user(user_id):
    row = db.session.execute(text("SELECT id, username FROM users WHERE id = :id"), {"id": int(user_id)}).fetchone()
    if row:
        return User(row[0], row[1])
    return None


def get_current_user_id():
    return int(current_user.id) if current_user.is_authenticated else None


def message_sender(msg,target_type='global', target_id='global'):
    if target_type == 'global':
        emit('global_message', msg, to='global', skip_sid=request.sid)  # type: ignore
    elif target_type == 'private' and target_id:
        if target_id in online_users:
            emit('private_message', msg, to=target_id)
    elif target_type == 'group' and target_id:
        emit('group_message', msg, to=target_id, skip_sid=request.sid) # type: ignore


def get_users_with_relationships(user_id):
    rows = db.session.execute(text(
        """
        SELECT f.incoming_id AS friend_id, 
                u.username,
                CASE
                    WHEN f.status = 'pending' THEN 'pending'
                    when f.status = 'accepted' THEN 'chat'
                    END AS friendStates
        FROM friends f
        LEFT JOIN users u ON f.incoming_id = u.id
        WHERE f.outgoing_id = :user_id
        
        UNION ALL
        
        SELECT f.outgoing_id AS friend_id,
        u.username,
        CASE
            WHEN f.status = 'pending' THEN 'incoming'
            when f.status = 'accepted' THEN 'chat'
            END AS friendStates
        FROM friends f
        LEFT JOIN users u ON f.outgoing_id = u.id
        WHERE f.incoming_id = :user_id
        
        ORDER BY username
        """
    ), {"user_id": user_id}).fetchall()

    users = []
    for row in rows:
        users.append(
            {
                "id": row[0],
                "name": row[1],
                "avatar": row[1][0].upper(),
                "friendStates": row[2]
            }
        )
    return users


def get_username_by_id(user_id):
    row = db.session.execute(text("SELECT username FROM users WHERE id = :id"), {"id": user_id}).fetchone()
    return row[0] if row else None


def are_friends(user_id, target_id):
    row = db.session.execute(text(
        """
        SELECT status FROM friends
        WHERE (outgoing_id = :uid AND incoming_id = :fid)
           OR (outgoing_id = :fid AND incoming_id = :uid)
        """
    ), {"uid": user_id, "fid": target_id}).fetchone()
    return bool(row and row[0] == 'accepted')


# ==================== 群组辅助函数 ====================

def get_user_groups(user_id):
    """获取用户所属的所有群组及成员数"""
    rows = db.session.execute(text("""
        SELECT g.id, g.group_name, g.creator_id, g.created_at,
               COUNT(gm2.user_id) AS member_count
        FROM groups g
        JOIN group_members gm ON gm.chat_id = 'group:' || g.id AND gm.user_id = :uid
        LEFT JOIN group_members gm2 ON gm2.chat_id = 'group:' || g.id
        GROUP BY g.id, g.group_name, g.creator_id, g.created_at
        ORDER BY g.created_at
    """), {"uid": user_id}).fetchall()

    groups = []
    for row in rows:
        groups.append({
            "id": row[0],
            "name": row[1],
            "creator_id": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
            "members": row[4],
            "avatar": row[1][:2].upper() if row[1] else "??"
        })
    return groups


def is_group_member(group_id, user_id):
    row = db.session.execute(text("""
        SELECT 1 FROM group_members
        WHERE chat_id = 'group:' || :gid AND user_id = :uid
    """), {"gid": group_id, "uid": user_id}).fetchone()
    return bool(row)


def is_group_creator(group_id, user_id):
    row = db.session.execute(text("""
        SELECT 1 FROM groups
        WHERE id = :gid AND creator_id = :uid
    """), {"gid": group_id, "uid": user_id}).fetchone()
    return bool(row)


app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-secret-key')
socketio = SocketIO(app, manage_session=False)
online_users = {}
user_to_sid = {}
user_id_to_sid = {}

PUBLIC_CHAT_CACHE = []  # 存储全局聊天消息的缓存列表，格式为 [{'from': username, 'text': message, 'created_at': timestamp}, ...]
MAX_PUBLIC_MSGS = 50


@app.route('/')
@login_required
def index():
     user_id = get_current_user_id()
     username = current_user.username
     return render_template('chat.html', user_id=user_id, username=username) 


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Check
        if not username or not password:
            return {"success": False, "error": "username and password are required"}
        
        user = db.session.execute(text("SELECT * FROM users WHERE username = :username"), {"username": username}).fetchall()
        
        if len(user) != 1 or not check_password_hash(user[0][2], password):
            return {"success": False, "error": "Invalid username or password"}

        user_obj = User(user[0][0], user[0][1])
        login_user(user_obj)
        db.session.execute(text("UPDATE users SET last_login = NOW() WHERE username = :username"), {"username": username})
        db.session.commit()
        return {"success": True, "redirect": "/"}
    else:
        return render_template('login.html')
    

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirmation = request.form.get('confirmation')

        # Check
        if not username or not password or not confirmation:
            return {"success": False, "error": "username, password and confirmation are required"}

        if all([username, password, confirmation]) and password != confirmation:
            return {"success": False, "error": "Passwords do not match"}

        # Check if username already exists
        existing_user = db.session.execute(text("SELECT * FROM users WHERE username = :username LIMIT 1"), {"username": username}).fetchone()
        if existing_user:
            return {"success": False, "error": "Username already exists"}

        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = db.session.execute(text("INSERT INTO users (username, password_hash) VALUES (:username, :password_hash) RETURNING id"), {"username": username, "password_hash": hashed_password}).scalar()
        user_obj = User(new_user, username)
        login_user(user_obj)
        db.session.commit()

        return {"success": True, "redirect": "/"}

    else:
        return render_template('register.html')


@app.route('/api/users')
@login_required
def api_users():
    user_id = get_current_user_id()
    users = get_users_with_relationships(user_id)
    friend_states = {user['id']: user['friendStates'] for user in users}
    return {"users": users, "friendStates": friend_states}


def get_group_count(group_id):
    """返回群组当前成员数"""
    row = db.session.execute(text(
        "SELECT COUNT(*) FROM group_members WHERE chat_id = 'group:' || :gid"
    ), {"gid": group_id}).fetchone()
    return row[0] if row else 0


def emit_group_count(group_id):
    """向群组房间广播最新成员数"""
    count = get_group_count(group_id)
    socketio.emit('group_info_updated', {"id": group_id, "members": count}, to=str(group_id))


def get_group_name(group_id):
    row = db.session.execute(text(
        "SELECT group_name FROM groups WHERE id = :gid"
    ), {"gid": group_id}).fetchone()
    return row[0] if row else "Unknown"


# ==================== 群组 API 路由 ====================

@app.route('/api/groups')
@login_required
def api_groups():
    """获取当前用户所属的所有群组"""
    user_id = get_current_user_id()
    groups = get_user_groups(user_id)
    return {"groups": groups}


@app.route('/api/groups/<int:group_id>/members')
@login_required
def api_group_members(group_id):
    """获取群组成员列表"""
    user_id = get_current_user_id()
    if not is_group_member(group_id, user_id):
        return {"error": "Not a member of this group"}, 403

    rows = db.session.execute(text("""
        SELECT u.id, u.username, gm.joined_at,
               CASE WHEN gm.role = 'owner' THEN TRUE ELSE FALSE END AS is_creator
        FROM group_members gm
        JOIN users u ON gm.user_id = u.id
        WHERE gm.chat_id = 'group:' || :gid
        ORDER BY gm.joined_at
    """), {"gid": group_id}).fetchall()

    members = [{
        "id": row[0],
        "username": row[1],
        "joined_at": row[2].isoformat() if row[2] else None,
        "is_creator": row[3]
    } for row in rows]
    return {"members": members, "group_id": group_id}


@app.route('/api/global_messages')
@login_required
def api_global_messages():
    print(f"API called: /api/global_messages: 返回消息{PUBLIC_CHAT_CACHE}")
    return {"messages": PUBLIC_CHAT_CACHE}

@app.route('/api/private_messages/<int:target_id>')
@login_required
def api_private_messages(target_id):
    user_id = get_current_user_id()
    if not are_friends(user_id, target_id):
        return {"error": "Not friends"}
    # 私聊 chat_id: 两个用户ID排序后用冒号连接
    uid1, uid2 = sorted([user_id, target_id]) # type: ignore
    chat_id = f"{uid1}:{uid2}"
    messages = db.session.execute(text(
        """
        SELECT m.id, m.sender_id, m.content, m.created_at, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.chat_type = 'private'
          AND m.chat_id = :chat_id
          AND m.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM user_message_status ums
              WHERE ums.message_id = m.id
                AND ums.user_id = :uid
                AND ums.is_deleted = TRUE
          )
        ORDER BY m.created_at
        """
    ), {"chat_id": chat_id, "uid": user_id}).fetchall()
    return {"messages": [{"id": m[0], "sender_id": m[1], "content": m[2], "created_at": m[3].isoformat() if m[3] else None, "sender_username": m[4]} for m in messages]}

@app.route('/api/group_messages/<int:group_id>')
@login_required
def api_group_messages(group_id):
    user_id = get_current_user_id()
    # 校验用户是否为群组成员
    if not is_group_member(group_id, user_id):
        return {"error": "Not a member of this group"}
    chat_id = f"group:{group_id}"
    messages = db.session.execute(text(
        """
        SELECT m.id, m.sender_id, m.content, m.created_at, u.username
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.chat_type = 'group'
          AND m.chat_id = :chat_id
          AND m.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM user_message_status ums
              WHERE ums.message_id = m.id
                AND ums.user_id = :uid
                AND ums.is_deleted = TRUE
          )
        ORDER BY m.created_at
        """
    ), {"chat_id": chat_id, "uid": user_id}).fetchall()
    return {"messages": [{"id": m[0], "sender_id": m[1], "content": m[2], "created_at": m[3].isoformat() if m[3] else None, "sender_username": m[4]} for m in messages]}

@app.route('/api/unread_counts')
@login_required
def api_unread_counts():
    user_id = get_current_user_id()
    rows = db.session.execute(text(
        """
        SELECT 
            CASE 
                WHEN SPLIT_PART(ums.chat_id, ':', 1)::int = :uid 
                THEN SPLIT_PART(ums.chat_id, ':', 2)::int 
                ELSE SPLIT_PART(ums.chat_id, ':', 1)::int 
            END AS other_user_id,
            COUNT(*) as unread_count
        FROM user_message_status ums
        WHERE ums.user_id = :uid
          AND ums.is_read = FALSE
          AND ums.chat_type = 'private'
        GROUP BY ums.chat_id
        """
    ), {"uid": user_id}).fetchall()
    return {"unread": {str(row[0]): row[1] for row in rows}}



@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))


@socketio.on('connect')
@authenticated_only
def handle_connect():
    sid = request.sid  # type: ignore
    user_id = int(current_user.id)
    username = current_user.username
    online_users[sid] = {"user_id": user_id, "username": username}
    user_to_sid[username] = sid
    user_id_to_sid[user_id] = sid
    print(f"用户{username}已连接, Session ID: {user_id}")
    emit('user_online', broadcast=True, include_self=False)

@socketio.on('get_online_users')
@authenticated_only
def handle_get_online_users():
    user_list = []
    for user in online_users.values():
        user_list.append({
            'user_id': user['user_id'],
            'username': user['username']
        })
    emit('get_online_users', user_list)


@socketio.on('get_my_info')
@authenticated_only
def handle_get_my_info():
    user = online_users.get(request.sid)  # type: ignore
    if user:
        emit('get_my_info', {'username': user['username'], 'user_id': user['user_id']})


@socketio.on('join_global')
@authenticated_only
def handle_join_global():
    join_room('global')
    
@socketio.on('join_group')    
@authenticated_only
def handle_join_group(group_id):
    user_id = int(current_user.id)
    try:
        gid = int(group_id)
    except (TypeError, ValueError):
        return
    if not is_group_member(gid, user_id):
        return
    join_room(group_id)


# ==================== 群组管理 SocketIO ====================

@socketio.on('create_group')
@authenticated_only
def handle_create_group_socket(data):
    user_id = int(current_user.id)
    group_name = data.get('name', '').strip() if isinstance(data, dict) else ''
    if not group_name:
        return {"error": "Group name is required"}
    if len(group_name) > 100:
        return {"error": "Group name too long (max 100)"}

    result = db.session.execute(text("""
        INSERT INTO groups (group_name, creator_id)
        VALUES (:name, :uid)
        RETURNING id, created_at
    """), {"name": group_name, "uid": user_id})
    row = result.fetchone()
    if not row:
        return {"error": "Failed to create group"}
    group_id = row[0]
    db.session.execute(text("""
        INSERT INTO group_members (chat_id, user_id, role)
        VALUES ('group:' || :gid, :uid, 'owner')
    """), {"gid": group_id, "uid": user_id})
    db.session.commit()
    join_room(str(group_id))
    return {"success": True, "group": {"id": group_id, "name": group_name, "creator_id": user_id, "members": 1, "avatar": group_name[:2].upper()}}

@socketio.on('invite_to_group')
@authenticated_only
def handle_invite_to_group(data):
    user_id = int(current_user.id)
    group_id = int(data.get('group_id'))
    target_id = int(data.get('user_id'))
    if not is_group_creator(group_id, user_id):
        return {"error": "Only the group creator can invite members"}
    target = db.session.execute(text("SELECT 1 FROM users WHERE id = :uid"), {"uid": target_id}).fetchone()
    if not target:
        return {"error": "User not found"}
    if is_group_member(group_id, target_id):
        return {"error": "User is already a member"}
    db.session.execute(text("INSERT INTO group_members (chat_id, user_id, role) VALUES ('group:' || :gid, :uid, 'member')"), {"gid": group_id, "uid": target_id})
    db.session.commit()
    target_sid = user_id_to_sid.get(target_id)
    if target_sid:
        gi = db.session.execute(text("SELECT g.group_name, g.creator_id, COUNT(gm.user_id)::int AS mc FROM groups g JOIN group_members gm ON gm.chat_id = 'group:' || g.id WHERE g.id = :gid GROUP BY g.id"), {"gid": group_id}).fetchone()
        if gi:
            socketio.emit('added_to_group', {"id": group_id, "name": gi[0], "creator_id": gi[1], "members": gi[2], "avatar": gi[0][:2].upper()}, to=target_sid)
    emit_group_count(group_id)  # 广播最新成员数给群组所有人
    return {"success": True}

@socketio.on('remove_from_group')
@authenticated_only
def handle_remove_from_group(data):
    user_id = int(current_user.id)
    group_id = int(data.get('group_id'))
    target_id = int(data.get('target_id'))
    # 群主不能被踢，不能自己离开
    if is_group_creator(group_id, target_id) and target_id != user_id:
        return {"error": "Cannot remove the group creator"}
    if is_group_creator(group_id, target_id) and target_id == user_id:
        return {"error": "Group creator cannot leave; transfer ownership first"}
    if target_id != user_id and not is_group_creator(group_id, user_id):
        return {"error": "Only the group creator can remove members"}
    if not is_group_member(group_id, target_id):
        return {"error": "User is not a member of this group"}
    db.session.execute(text("DELETE FROM group_members WHERE chat_id = 'group:' || :gid AND user_id = :uid"), {"gid": group_id, "uid": target_id})
    db.session.commit()
    emit_group_count(group_id)  # 广播最新成员数
    if target_id != user_id:
        ts = user_id_to_sid.get(target_id)
        if ts:
            socketio.emit('removed_from_group', {"id": group_id, "name": get_group_name(group_id)}, to=ts)
    return {"success": True}

@socketio.on('delete_group')
@authenticated_only
def handle_delete_group_socket(data):
    user_id = int(current_user.id)
    group_id = int(data.get('group_id'))
    if not is_group_creator(group_id, user_id):
        return {"error": "Only the group creator can delete the group"}
    members = db.session.execute(text("SELECT user_id FROM group_members WHERE chat_id = 'group:' || :gid"), {"gid": group_id}).fetchall()
    gn = get_group_name(group_id)
    db.session.execute(text("DELETE FROM group_members WHERE chat_id = 'group:' || :gid"), {"gid": group_id})
    db.session.execute(text("DELETE FROM groups WHERE id = :gid"), {"gid": group_id})
    db.session.commit()
    for m in members:
        if m[0] != user_id:
            ms = user_id_to_sid.get(m[0])
            if ms:
                socketio.emit('group_deleted', {"id": group_id, "name": gn}, to=ms)
    return {"success": True}


@socketio.on('mark_read')
@authenticated_only
def handle_mark_read(data):
    user_id = int(current_user.id)
    sender_id = data.get('from_id')
    if not sender_id:
        return {"error": "sender_id is required"}
    # 计算 chat_id
    uid1, uid2 = sorted([user_id, int(sender_id)])
    chat_id = f"{uid1}:{uid2}"
    db.session.execute(text(
        """
        UPDATE user_message_status
        SET is_read = TRUE, read_at = NOW()
        WHERE user_id = :uid
          AND is_read = FALSE
          AND chat_type = 'private'
          AND chat_id = :chat_id
        """
    ), {"uid": user_id, "chat_id": chat_id})
    db.session.commit()
    return {"success": True}

@socketio.on('transfer_ownership')
@authenticated_only
def handle_transfer_ownership(data):
    user_id = int(current_user.id)
    group_id = int(data.get('group_id'))
    target_id = int(data.get('target_id'))
    if not is_group_creator(group_id, user_id):
        return {"error": "Only the group creator can transfer ownership"}
    if not is_group_member(group_id, target_id):
        return {"error": "Target user is not a member of this group"}
    if target_id == user_id:
        return {"error": "You are already the owner"}
    db.session.execute(text("UPDATE groups SET creator_id = :tid WHERE id = :gid"), {"tid": target_id, "gid": group_id})
    # 更新 group_members 中的角色
    db.session.execute(text("UPDATE group_members SET role = 'member' WHERE chat_id = 'group:' || :gid AND user_id = :uid AND role = 'owner'"), {"gid": group_id, "uid": user_id})
    db.session.execute(text("UPDATE group_members SET role = 'owner' WHERE chat_id = 'group:' || :gid AND user_id = :tid"), {"gid": group_id, "tid": target_id})
    db.session.commit()
    gn = get_group_name(group_id)
    socketio.emit('ownership_transferred', {"id": group_id, "name": gn, "new_creator_id": target_id}, to=str(group_id))
    return {"success": True}


@socketio.on('global_message')
@authenticated_only
def handle_global_message(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return
    global PUBLIC_CHAT_CACHE
    
    msg = {
        'from': user['username'],
        'from_id': user['user_id'],
        'text': data['text'],
        'created_at': data.get('timestamp')
    }
    PUBLIC_CHAT_CACHE.append(msg)
    print(f"Received global message from {user['username']}: {data['text']}")
    if len(PUBLIC_CHAT_CACHE) > MAX_PUBLIC_MSGS:
        PUBLIC_CHAT_CACHE.pop(0)

    message_sender(msg)

@socketio.on('private_message')
@authenticated_only
def handle_private_message(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return
    target_id = data.get('targetId')
    if not are_friends(user['user_id'], target_id):
        return
    # 计算 chat_id：两个用户ID排序后用冒号连接
    uid1, uid2 = sorted([user['user_id'], target_id])
    chat_id = f"{uid1}:{uid2}"
    # 存储消息到数据库
    result = db.session.execute(text(
        """
        INSERT INTO messages (chat_id, chat_type, sender_id, msg_type, content)
        VALUES (:chat_id, 'private', :sender_id, 'text', :content)
        RETURNING id, created_at
        """
    ), {
        'chat_id': chat_id,
        'sender_id': user['user_id'],
        'content': data['text']
    })
    row = result.fetchone()
    db.session.commit()
    if not row:
        return
    message_id = row[0]
    # 插入 user_message_status：发送者已读，接收者未读
    db.session.execute(text(
        """
        INSERT INTO user_message_status (user_id, message_id, chat_id, chat_type, is_read, read_at)
        VALUES (:sender_id, :message_id, :chat_id, 'private', TRUE, NOW()),
               (:receiver_id, :message_id, :chat_id, 'private', FALSE, NULL)
        """
    ), {
        'sender_id': user['user_id'],
        'receiver_id': target_id,
        'message_id': message_id,
        'chat_id': chat_id
    })
    db.session.commit()
    msg = {
        'id': message_id,
        'from': user['username'],
        'from_id': user['user_id'],
        'to_id': target_id,
        'text': data['text'],
        'msg_type': 'private',
        'created_at': row[1].isoformat() if row[1] else None
    }
    target_sid = user_id_to_sid.get(target_id)
    if target_sid:
        message_sender(msg, target_type='private', target_id=target_sid)


@socketio.on('group_message')
@authenticated_only
def handle_group_message(data):
    group_id = data.get('groupId')
    chat_id = f"group:{group_id}"
    # 存储消息到数据库
    result = db.session.execute(text(
        """
        INSERT INTO messages (chat_id, chat_type, sender_id, msg_type, content)
        VALUES (:chat_id, 'group', :sender_id, 'text', :content)
        RETURNING id, created_at
        """
    ), {
        'chat_id': chat_id,
        'sender_id': int(current_user.id),
        'content': data['text']
    })
    row = result.fetchone()
    db.session.commit()
    if not row:
        return
    msg = {
        'id': row[0],
        'from': current_user.username,
        'from_id': int(current_user.id),
        'group_id': group_id,
        'text': data['text'],
        'msg_type': 'group',
        'created_at': row[1].isoformat() if row[1] else None
    }
    message_sender(msg, target_type='group', target_id=group_id)


@socketio.on('friend_add')
@authenticated_only
def handle_friend_add(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return
    target_id = data.get('from')
    if target_id == user['user_id']:
        return
    userName = get_username_by_id(user['user_id'])
    db.session.execute(text(
        "INSERT INTO friends (outgoing_id, incoming_id, status) VALUES (:uid, :fid, 'pending')"
    ), {"uid": user['user_id'], "fid": target_id})
    db.session.commit()
    socketio.emit('friend_add', {"userId": user['user_id'], "userName": userName}, to=user_id_to_sid.get(target_id))


@socketio.on('friend_accept')
@authenticated_only
def handle_friend_accept(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return
    target_id = data.get('from')
    userName = get_username_by_id(user['user_id'])
    db.session.execute(text(
        "UPDATE friends SET status = 'accepted' WHERE outgoing_id = :uid AND incoming_id = :fid AND status = 'pending'"
    ), {"uid": target_id, "fid": user['user_id']})
    db.session.commit()
    socketio.emit('friend_accept', {"userId": user['user_id'], "userName": userName}, to=user_id_to_sid.get(target_id))


@socketio.on('friend_reject')
@authenticated_only
def handle_friend_reject(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return

    target_id = data.get('from')
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return

    current_id = user['user_id']
    if target_id == current_id:
        return

    existing = db.session.execute(text(
        """
        SELECT outgoing_id, incoming_id, status FROM friends
        WHERE (outgoing_id = :uid AND incoming_id = :fid)
           OR (outgoing_id = :fid AND incoming_id = :uid)
        """
    ), {"uid": current_id, "fid": target_id}).fetchone()

    if existing and existing[2] == 'pending':
        db.session.execute(text(
            "DELETE FROM friends WHERE (outgoing_id = :uid AND incoming_id = :fid) or (outgoing_id = :fid AND incoming_id = :uid)"
        ), {"uid": existing[0], "fid": existing[1]})
        db.session.commit()
        target_sid = user_id_to_sid.get(target_id)
        if target_sid:
            emit('friend_reject', {"userId": current_id}, to=target_sid)


@socketio.on('friend_remove')
@authenticated_only
def handle_friend_remove(data):
    user = online_users.get(request.sid)  # type: ignore
    if not user:
        return

    target_id = data.get('from')
    try:
        target_id = int(target_id)
    except (TypeError, ValueError):
        return

    current_id = user['user_id']
    if target_id == current_id:
        return

    existing = db.session.execute(text(
        """
        SELECT outgoing_id, incoming_id, status FROM friends
        WHERE (outgoing_id = :uid AND incoming_id = :fid)
           OR (outgoing_id = :fid AND incoming_id = :uid)
        """
    ), {"uid": current_id, "fid": target_id}).fetchone()

    if existing and existing[2] in ('accepted', 'agree'):
        db.session.execute(text(
            "DELETE FROM friends WHERE (outgoing_id = :uid AND incoming_id = :fid) or (outgoing_id = :fid AND incoming_id = :uid)"
        ), {"uid": existing[0], "fid": existing[1]})
        db.session.commit()
        target_sid = user_id_to_sid.get(target_id)
        if target_sid:
            emit('friend_remove', {"userId": current_id}, to=target_sid) # type: ignore


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接时触发
    """
    user = online_users.get(request.sid)  # type: ignore
    if user:
        username = user.get('username')
        user_id = user.get('user_id')
        print(f"Client disconnected: {username} reason: {request.environ.get('socketio.disconnect_reason', 'Unknown')}")
        user_to_sid.pop(username, None)
        user_id_to_sid.pop(user_id, None)
        online_users.pop(request.sid, None)  # type: ignore
        emit('user_offline', broadcast=True, include_self=False)



if __name__ == '__main__':
    socketio.run(app)
