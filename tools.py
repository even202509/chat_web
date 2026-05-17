from functools import wraps
import re
from io import BytesIO

from flask import redirect, url_for, request, jsonify
from flask_login import current_user
from flask_socketio import disconnect
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$')
PASSWORD_PATTERN = re.compile(r'^[\x21-\x7E]{6,128}$')
BIO_MAX_LENGTH = 220
ALLOWED_AVATAR_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
ALLOWED_FILE_UPLOAD_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

IMAGE_MAGIC_HEADERS = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'webp': [b'RIFF'],
}


def validate_username(username):
    if not username or not isinstance(username, str):
        return False, 'Username is required'
    if not USERNAME_PATTERN.match(username):
        return False, 'Username must be 3-32 chars and may contain letters, digits, dot, underscore, or hyphen'
    return True, None


def validate_password(password):
    if not password or not isinstance(password, str):
        return False, 'Password is required'
    if not PASSWORD_PATTERN.match(password):
        return False, 'Password must be 6-128 printable ASCII characters'
    return True, None


def validate_bio(bio):
    if bio is None:
        return True, None, ''
    if not isinstance(bio, str):
        return False, 'Bio must be a string', None
    clean_bio = bio.strip()
    if len(clean_bio) > BIO_MAX_LENGTH:
        return False, f'Bio must be at most {BIO_MAX_LENGTH} characters', None
    return True, None, clean_bio


def allowed_file(filename, allowed_extensions):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def get_image_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


def validate_image_magic(file, filename):
    ext = get_image_extension(filename)
    if ext not in IMAGE_MAGIC_HEADERS:
        return False, 'Unsupported image extension'

    try:
        file.stream.seek(0)
        header = file.stream.read(12)
    finally:
        file.stream.seek(0)

    if ext == 'webp':
        if len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP':
            return True, None
        return False, 'File magic does not match WEBP'

    for magic in IMAGE_MAGIC_HEADERS[ext]:
        if header.startswith(magic):
            return True, None
    return False, 'File magic does not match image type'


def normalize_image_file(file, filename):
    ext = get_image_extension(filename)
    if ext not in ALLOWED_FILE_UPLOAD_EXTENSIONS:
        return False, None, 'Unsupported image extension'

    try:
        file.stream.seek(0)
        image = Image.open(file.stream)
        image.load()
    except (UnidentifiedImageError, OSError):
        return False, None, 'Invalid image file'

    output = BytesIO()
    output_format = 'PNG'
    save_kwargs = {'optimize': True}

    if ext in ('jpg', 'jpeg'):
        output_format = 'JPEG'
        image = image.convert('RGB')
        save_kwargs['quality'] = 85
    elif ext == 'png':
        output_format = 'PNG'
    elif ext == 'gif':
        output_format = 'GIF'
    elif ext == 'webp':
        output_format = 'WEBP'

    try:
        image.save(output, format=output_format, **save_kwargs)
    except OSError:
        return False, None, 'Failed to process image'

    output.seek(0)
    return True, output, None


def validate_upload_file(file, allowed_extensions=None):
    if file is None:
        return False, None, 'No file provided'
    if not getattr(file, 'filename', None):
        return False, None, 'Empty filename'
    safe_name = secure_filename(file.filename)
    if allowed_extensions is None:
        allowed_extensions = ALLOWED_FILE_UPLOAD_EXTENSIONS
    if not allowed_file(safe_name, allowed_extensions):
        return False, None, 'File type not allowed'
    return True, safe_name, None


def socket_error(message, code=None, details=None):
    payload = {
        'success': False,
        'error': message,
    }
    if code:
        payload['code'] = code
    if details is not None:
        payload['details'] = details
    return payload


def socket_success(**kwargs):
    payload = {'success': True}
    payload.update(kwargs)
    return payload


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if the user is logged in
        if not current_user.is_authenticated:
            # For API or XHR requests return JSON 401; normal browser page loads should redirect
            is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            is_api = request.path.startswith('/api')
            if request.is_json or is_xhr or is_api:
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def authenticated_only(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
            return None
        return f(*args, **kwargs)
    return wrapped