/**
 * Основной JavaScript файл для клиентской части системы трансляции экрана
 */

// Утилиты для работы с WebSocket соединением
const ScreenShare = {
    socket: null,

    // Инициализация соединения
    init: function() {
        this.socket = io();
        this.setupEventListeners();
        console.log('ScreenShare: Инициализация завершена');
    },

    // Настройка слушателей событий
    setupEventListeners: function() {
        this.socket.on('connect', this.handleConnect.bind(this));
        this.socket.on('disconnect', this.handleDisconnect.bind(this));
        this.socket.on('screen_update', this.handleScreenUpdate.bind(this));
        this.socket.on('notification', this.handleNotification.bind(this));
        this.socket.on('connection_status', this.handleConnectionStatus.bind(this));
    },

    // Обработчик успешного подключения
    handleConnect: function() {
        console.log('ScreenShare: Соединение установлено');
        this.updateConnectionStatus('Подключено', 'success');
    },

    // Обработчик отключения
    handleDisconnect: function() {
        console.log('ScreenShare: Соединение разорвано');
        this.updateConnectionStatus('Отключено', 'danger');
    },

    // Обработчик обновления статуса соединения
    handleConnectionStatus: function(data) {
        if (data.status === 'connected') {
            this.updateConnectionStatus('Подключено', 'success');
        } else {
            this.updateConnectionStatus('Ошибка', 'warning');
        }
    },

    // Обновление индикатора состояния соединения
    updateConnectionStatus: function(text, statusClass) {
        const connectionStatus = document.getElementById('connection-status');
        const statusText = document.getElementById('status-text');

        if (connectionStatus) {
            connectionStatus.textContent = text;
            connectionStatus.className = `badge bg-${statusClass}`;
        }

        if (statusText) {
            statusText.textContent = text;
        }
    },

    // Обработчик уведомлений от сервера
    handleNotification: function(data) {
        console.log('ScreenShare: Уведомление:', data.message);
        this.showNotification(data.message);
    },

    // Отображение уведомления
    showNotification: function(message) {
        // Проверка наличия встроенной функции уведомлений
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('Система трансляции экрана', {
                body: message,
                icon: '/static/img/favicon.ico'
            });
        } else {
            // Создание временного уведомления внутри страницы
            const notificationDiv = document.createElement('div');
            notificationDiv.className = 'notification-toast';
            notificationDiv.innerHTML = `
                <div class="toast show" role="alert" aria-live="assertive" aria-atomic="true">
                    <div class="toast-header">
                        <strong class="me-auto">Уведомление</strong>
                        <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                    <div class="toast-body">
                        ${message}
                    </div>
                </div>
            `;

            document.body.appendChild(notificationDiv);

            // Удаление уведомления через 3 секунды
            setTimeout(() => {
                document.body.removeChild(notificationDiv);
            }, 3000);
        }
    },

    // Обработка обновления экрана
    handleScreenUpdate: function(data) {
        const screenDisplay = document.getElementById('screen-display');
        if (screenDisplay) {
            screenDisplay.src = 'data:image/jpeg;base64,' + data.image;

            // Обновление счетчика FPS и размера изображения
            this.updateStats(data);
        }
    },

    // Обновление статистики (FPS, размер изображения)
    updateStats: function(data) {
        // Обновление размера изображения
        const imageSize = document.getElementById('image-size');
        if (imageSize) {
            const byteSize = (data.image.length * 3) / 4; // Base64 размер в байтах
            imageSize.textContent = this.formatSize(byteSize);
        }

        // Обновление счетчика FPS
        if (!this._fpsData) {
            this._fpsData = {
                frameCount: 0,
                lastTime: performance.now()
            };
        }

        this._fpsData.frameCount++;

        const now = performance.now();
        const elapsed = now - this._fpsData.lastTime;

        if (elapsed >= 1000) {  // Обновляем значение FPS раз в секунду
            const fps = Math.round((this._fpsData.frameCount * 1000) / elapsed);
            const fpsElement = document.getElementById('fps');
            if (fpsElement) {
                fpsElement.textContent = fps;
            }

            this._fpsData.frameCount = 0;
            this._fpsData.lastTime = now;
        }
    },

    // Форматирование размера файла
    formatSize: function(bytes) {
        if (bytes < 1024) {
            return bytes + ' B';
        } else if (bytes < 1048576) {
            return (bytes / 1024).toFixed(2) + ' KB';
        } else {
            return (bytes / 1048576).toFixed(2) + ' MB';
        }
    },

    // Изменение качества трансляции (для админов)
    changeQuality: function(quality) {
        console.log('ScreenShare: Изменение качества на', quality);
        this.socket.emit('change_quality', { quality: quality });
    },

    // Изменение целевого FPS (для админов)
    changeFPS: function(fps) {
        console.log('ScreenShare: Изменение FPS на', fps);
        this.socket.emit('change_fps', { fps: fps });
    }
};

// Настройка страницы при загрузке
document.addEventListener('DOMContentLoaded', function() {
    // Инициализация WebSocket соединения
    if (document.getElementById('screen-display')) {
        ScreenShare.init();
    }

    // Обработчики элементов управления для админов
    setupAdminControls();

    // Обработчики для админ-панели пользователей
    setupUserAdminPanel();
});

// Настройка элементов управления на странице трансляции для админов
function setupAdminControls() {
    const qualityRange = document.getElementById('quality-range');
    const fpsRange = document.getElementById('fps-range');

    if (qualityRange) {
        qualityRange.addEventListener('change', function() {
            const quality = this.value;
            document.getElementById('quality-value').textContent = quality;
            ScreenShare.changeQuality(parseInt(quality));
        });
    }

    if (fpsRange) {
        fpsRange.addEventListener('change', function() {
            const fps = this.value;
            document.getElementById('fps-target-value').textContent = fps;
            ScreenShare.changeFPS(parseInt(fps));
        });
    }
}

// Настройка интерфейса управления пользователями в админ-панели
function setupUserAdminPanel() {
    // Обработчик подтверждения удаления пользователя
    const deleteButtons = document.querySelectorAll('.delete-user-btn');
    if (deleteButtons) {
        deleteButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                if (!confirm('Вы действительно хотите удалить этого пользователя?')) {
                    e.preventDefault();
                }
            });
        });
    }

    // Обработчик сброса пароля пользователя
    const resetButtons = document.querySelectorAll('.reset-password-btn');
    if (resetButtons) {
        resetButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                if (!confirm('Сбросить пароль этого пользователя на временный?')) {
                    e.preventDefault();
                }
            });
        });
    }

    // Обработчик смены статуса администратора
    const adminToggleButtons = document.querySelectorAll('.toggle-admin-btn');
    if (adminToggleButtons) {
        adminToggleButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                const isAdmin = button.getAttribute('data-is-admin') === 'true';
                const message = isAdmin
                    ? 'Убрать права администратора у этого пользователя?'
                    : 'Предоставить права администратора этому пользователю?';

                if (!confirm(message)) {
                    e.preventDefault();
                }
            });
        });
    }
}