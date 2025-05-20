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
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Инициализация Flask и SocketIO
app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Глобальные переменные для отслеживания подключений
active_connections = set()
active_users = {}


# Инициализация базы данных
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

    # Создаем админа по умолчанию, если его нет
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        admin_password = generate_password_hash('admin')
        cursor.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                       ('admin', admin_password, True))

    conn.commit()
    conn.close()


# Модель пользователя для Flask-Login
class User(UserMixin):
    def __init__(self, id, username, is_admin=False):
        self.id = id
        self.username = username
        self.is_admin = is_admin


# Загрузка пользователя для Flask-Login
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


# Маршруты для аутентификации
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

        # Проверяем, существует ли пользователь
        conn = sqlite3.connect('users.db')
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))

        if cursor.fetchone():
            conn.close()
            return render_template('register.html', error="Пользователь с таким именем уже существует")

        # Хешируем пароль и создаем пользователя
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


# Маршрут для административной панели
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


# Маршрут для сброса пароля пользователя
@app.route('/admin/reset_password/<int:user_id>', methods=['POST'])
@login_required
def reset_password(user_id):
    if not current_user.is_admin:
        return jsonify({"error": "Отказано в доступе"}), 403

    # Генерируем временный пароль
    temp_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    hashed_password = generate_password_hash(temp_password)

    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, user_id))

    # Получаем имя пользователя для отображения в сообщении
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

    # Проверяем, существует ли пользователь
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))

    if cursor.fetchone():
        conn.close()
        flash('Пользователь с таким именем уже существует', 'danger')
        return redirect(url_for('admin'))

    # Хешируем пароль и создаем пользователя
    hashed_password = generate_password_hash(password)
    cursor.execute("INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)",
                   (username, hashed_password, is_admin))
    conn.commit()
    conn.close()

    flash(f'Пользователь {username} успешно добавлен', 'success')
    return redirect(url_for('admin'))


# Классы для захвата экрана и трансляции
class ScreenCapture:
    def __init__(self):
        self.sct = mss.mss()
        self.running = False
        self.capture_thread = None
        self.clients = set()
        self.quality = 50  # Качество JPEG от 1 до 100
        self.fps = 999  # Целевой FPS

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

    def _capture_loop(self):
        import mss
        import cv2
        import numpy as np

        sct = mss.mss()
        monitor = sct.monitors[1]
        last_frame_time = time.time()

        while self.running:
            current_time = time.time()
            elapsed = current_time - last_frame_time

            if elapsed < 1.0 / self.fps:
                time.sleep(1.0 / self.fps - elapsed)
                continue

            last_frame_time = time.time()

            img = sct.grab(monitor)
            if self.clients:
                # Конвертируем BGRA -> BGR (без альфа-канала)
                img_np = np.array(img)[..., :3]

                # Уменьшаем разрешение (если хочется ускорить)
                # img_np = cv2.resize(img_np, (1280, 720))  # Пример

                encode_param = [cv2.IMWRITE_JPEG_QUALITY, self.quality]
                success, buffer = cv2.imencode('.jpg', img_np, encode_param)

                if success:
                    img_base64 = base64.b64encode(buffer).decode('utf-8')
                    socketio.emit('screen_update', {'image': img_base64})


screen_capture = ScreenCapture()


# Обработчики WebSocket
@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False

    # Добавляем клиента в список получателей
    screen_capture.clients.add(request.sid)

    # Запускаем захват экрана, если это первый клиент
    if len(screen_capture.clients) == 1:
        screen_capture.start_capture()

    emit('connection_status', {'status': 'connected'})


@socketio.on('disconnect')
def handle_disconnect():
    # Удаляем клиента из списка получателей
    if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
        if request.sid in screen_capture.clients:
            screen_capture.clients.remove(request.sid)

        # Останавливаем захват экрана, если клиентов больше нет
        if not screen_capture.clients:
            screen_capture.stop_capture()


@socketio.on('change_quality')
def handle_quality_change(data):
    if current_user.is_authenticated and current_user.is_admin:
        quality = int(data.get('quality', 100))
        screen_capture.quality = max(1, min(100, quality))
        emit('notification', {'message': f'Качество изменено на {screen_capture.quality}%'})


@socketio.on('change_fps')
def handle_fps_change(data):
    if current_user.is_authenticated and current_user.is_admin:
        fps = int(data.get('fps', 999))
        screen_capture.fps = max(1, min(999, fps))
        emit('notification', {'message': f'FPS изменен на {screen_capture.fps}'})


# Инициализация и запуск сервера
if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)