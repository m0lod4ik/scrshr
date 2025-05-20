import socket
import threading
import sqlite3
import hashlib
import base64
import os
import json
import mss
import time
import uuid
import random
import string
import numpy as np
import cv2
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

active_connections = set()
active_users = {}

def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_admin BOOLEAN DEFAULT 0
    )
    ''')

    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        admin_password_plain = 'admin'
        admin_password = generate_password_hash(admin_password_plain)
        cursor.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                      ('admin', admin_password, True))
        print("\n" + "="*50)
        print(f"[ADMIN CREDENTIALS] Username: admin, Password: {admin_password_plain}")
        print("="*50 + "\n")

    conn.commit()
    conn.close()

class User(UserMixin):
    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()

    if user_data:
        return User(user_data[0], user_data[1], user_data[2])
    return None

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, is_admin FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        conn.close()

        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1], user_data[3])
            login_user(user)
            return redirect(url_for('dashboard'))

        return render_template('login.html', error="Неверное имя пользователя или пароль")

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))

        if cursor.fetchone():
            conn.close()
            return render_template('register.html', error="Пользователь с таким именем уже существует")

        hashed_password = generate_password_hash(password)
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        conn.close()

        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', username=current_user.username, is_admin=current_user.is_admin)

@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, is_admin FROM users")
    users = cursor.fetchall()
    conn.close()

    return render_template('admin.html', users=users)

@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
@login_required
def reset_password(user_id):
    if not current_user.is_admin:
        return jsonify({"error": "Отказано в доступе"}), 403

    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    hashed_password = generate_password_hash(temp_password)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, user_id))
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    username = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    flash(f'Пароль пользователя {username} сброшен на: {temp_password}')
    return redirect(url_for('admin'))

@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        return jsonify({"error": "Отказано в доступе"}), 403

    username = request.form.get('username')
    password = request.form.get('password')
    is_admin = request.form.get('is_admin') == 'on'

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))

    if cursor.fetchone():
        conn.close()
        flash('Пользователь с таким именем уже существует', 'danger')
        return redirect(url_for('admin'))

    hashed_password = generate_password_hash(password)
    cursor.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                   (username, hashed_password, is_admin))
    conn.commit()
    conn.close()

    flash(f'Пользователь {username} успешно добавлен', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({"error": "Отказано в доступе"}), 403

    if int(user_id) == current_user.id:
        flash('Вы не можете удалить свою учетную запись', 'danger')
        return redirect(url_for('admin'))

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE id = ?", (user_id,))
    username = cursor.fetchone()

    if username:
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash(f'Пользователь {username[0]} успешно удален', 'success')
    else:
        flash('Пользователь не найден', 'danger')

    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        return jsonify({"error": "Отказано в доступе"}), 403

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT username, is_admin FROM users WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()

    if user_data:
        username, is_admin = user_data
        new_status = not bool(is_admin)

        cursor.execute("UPDATE users SET is_admin = ? WHERE id = ?", (new_status, user_id))
        conn.commit()

        status_text = "предоставлены" if new_status else "отозваны"
        flash(f'Права администратора для пользователя {username} {status_text}', 'success')
    else:
        flash('Пользователь не найден', 'danger')

    conn.close()
    return redirect(url_for('admin'))

class ScreenCapture:
    def __init__(self):
        self.sct = mss.mss()
        self.running = False
        self.capture_thread = None
        self.clients = set()
        self.quality = 80
        self.fps = 30
        self.resolution_scale = 1.0
        self.adaptive_quality = True
        self.denoise = False
        self.sharpen = False
        self.last_frame_time = time.time()
        self.frame_times = []
        self.compressed_sizes = []

    def start_capture(self):
        if not self.running:
            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop)
            self.capture_thread.daemon = True
            self.capture_thread.start()

    def stop_capture(self):
        self.running = False
        if self.capture_thread:
            self.capture_thread.join()

    def _adaptive_quality_adjustment(self):
        if len(self.frame_times) >= 10 and self.adaptive_quality:
            avg_frame_time = sum(self.frame_times[-10:]) / 10
            current_fps = 1.0 / avg_frame_time if avg_frame_time > 0 else 30
            avg_frame_size = sum(self.compressed_sizes[-10:]) / 10 if self.compressed_sizes else 0

            if current_fps < self.fps * 0.8:
                self.quality = max(30, self.quality - 5)
                self.resolution_scale = max(0.5, self.resolution_scale - 0.05)
            elif current_fps > self.fps * 1.2 and avg_frame_size < 500000:
                self.quality = min(95, self.quality + 5)
                self.resolution_scale = min(1.0, self.resolution_scale + 0.05)

    def _capture_loop(self):
        import mss
        import cv2
        import numpy as np

        sct = mss.mss()
        monitor = sct.monitors[1]
        prev_frame = None
        sharpen_kernel = np.array([[-1, -1, -1],
                                   [-1, 9, -1],
                                   [-1, -1, -1]])

        while self.running:
            current_time = time.time()
            elapsed = current_time - self.last_frame_time

            if elapsed < 1.0 / self.fps:
                time.sleep(0.001)
                continue

            frame_start_time = time.time()
            img = sct.grab(monitor)

            if self.clients:
                img_np = np.array(img)
                img_np = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)

                if self.resolution_scale != 1.0:
                    h, w = img_np.shape[:2]
                    new_h, new_w = int(h * self.resolution_scale), int(w * self.resolution_scale)
                    img_np = cv2.resize(img_np, (new_w, new_h), interpolation=cv2.INTER_AREA)

                if self.denoise:
                    img_np = cv2.fastNlMeansDenoisingColored(img_np, None, 5, 5, 7, 21)

                if self.sharpen:
                    img_np = cv2.filter2D(img_np, -1, sharpen_kernel)

                encode_param = [cv2.IMWRITE_JPEG_QUALITY, self.quality]
                success, buffer = cv2.imencode('.jpg', img_np, encode_param)

                if success:
                    self.compressed_sizes.append(len(buffer))
                    if len(self.compressed_sizes) > 30:
                        self.compressed_sizes.pop(0)

                    img_base64 = base64.b64encode(buffer).decode('utf-8')
                    socketio.emit('screen_update', {'image': img_base64, 'quality': self.quality})
                    prev_frame = img_np.copy()

            frame_end_time = time.time()
            frame_time = frame_end_time - frame_start_time

            self.frame_times.append(frame_time)
            if len(self.frame_times) > 30:
                self.frame_times.pop(0)

            self._adaptive_quality_adjustment()
            self.last_frame_time = current_time

screen_capture = ScreenCapture()

@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False

    screen_capture.clients.add(request.sid)

    if len(screen_capture.clients) == 1:
        screen_capture.start_capture()

    emit('stream_settings', {
        'quality': screen_capture.quality,
        'fps': screen_capture.fps,
        'resolution_scale': screen_capture.resolution_scale,
        'denoise': screen_capture.denoise,
        'sharpen': screen_capture.sharpen,
        'adaptive_quality': screen_capture.adaptive_quality
    })

    emit('connection_status', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        if request.sid in screen_capture.clients:
            screen_capture.clients.remove(request.sid)

        if not screen_capture.clients:
            screen_capture.stop_capture()

@socketio.on('change_quality')
def handle_quality_change(data):
    if current_user.is_authenticated and current_user.is_admin:
        quality = int(data.get('quality', 80))
        screen_capture.quality = max(1, min(100, quality))
        emit('notification', {'message': f'Качество изменено на {screen_capture.quality}%'})

@socketio.on('change_fps')
def handle_fps_change(data):
    if current_user.is_authenticated and current_user.is_admin:
        fps = int(data.get('fps', 30))
        screen_capture.fps = max(1, min(60, fps))
        emit('notification', {'message': f'FPS изменен на {screen_capture.fps}'})

@socketio.on('change_resolution_scale')
def handle_resolution_change(data):
    if current_user.is_authenticated and current_user.is_admin:
        scale = float(data.get('scale', 1.0))
        screen_capture.resolution_scale = max(0.1, min(1.0, scale))
        emit('notification', {'message': f'Масштаб разрешения изменен на {screen_capture.resolution_scale:.2f}'})

@socketio.on('toggle_denoise')
def handle_denoise_toggle(data):
    if current_user.is_authenticated and current_user.is_admin:
        screen_capture.denoise = bool(data.get('enabled', False))
        status = "включено" if screen_capture.denoise else "выключено"
        emit('notification', {'message': f'Шумоподавление {status}'})

@socketio.on('toggle_sharpen')
def handle_sharpen_toggle(data):
    if current_user.is_authenticated and current_user.is_admin:
        screen_capture.sharpen = bool(data.get('enabled', False))
        status = "включено" if screen_capture.sharpen else "выключено"
        emit('notification', {'message': f'Повышение резкости {status}'})

@socketio.on('toggle_adaptive_quality')
def handle_adaptive_quality_toggle(data):
    if current_user.is_authenticated and current_user.is_admin:
        screen_capture.adaptive_quality = bool(data.get('enabled', True))
        status = "включено" if screen_capture.adaptive_quality else "выключено"
        emit('notification', {'message': f'Адаптивное качество {status}'})

@socketio.on('admin_get_connections')
def handle_get_connections():
    if current_user.is_authenticated and current_user.is_admin:
        emit('admin_connections_info', {
            'count': len(screen_capture.clients),
            'fps': 1.0 / (sum(screen_capture.frame_times) / len(
                screen_capture.frame_times)) if screen_capture.frame_times else 0,
            'avg_frame_size': sum(screen_capture.compressed_sizes) / len(
                screen_capture.compressed_sizes) if screen_capture.compressed_sizes else 0
        })

if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=8080, debug=False, allow_unsafe_werkzeug=True)