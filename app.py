import datetime

from flask import Flask, request, jsonify, render_template, send_file, make_response
import requests
import hashlib
import csv
import io
import config
import db_manager as db

app = Flask(__name__, template_folder='templates')

# --- Telegram API Helper ---
def send_telegram_message(chat_id, text):
    if not config.BOT_TOKEN or config.BOT_TOKEN == "ВАШ_ТОКЕН_БОТА":
        print(f"--- SIMULATION: Sending to {chat_id} ---\n{text}\n---")
        return True
        
    url = f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        return response.json()
    except Exception as e:
        print(f"Error sending: {e}")
        return None

# --- API User (Mini App) ---
@app.route('/api/subscribe', methods=['POST'])
def api_subscribe():
    data = request.json
    user_id = data.get('user_id')
    first_name = data.get('first_name')
    username = data.get('username')
    comment = data.get('comment')

    if not user_id:
        return jsonify({"status": "error", "message": "User ID missing"}), 400

    if db.save_user(user_id, first_name, username, comment):
        # Отправка уведомления админу (или самому юзеру)
        admin_msg = f"✅ Новая заявка!\nОт: {first_name} (@{username})\nID: {user_id}\nТекст: {comment}"
        # В реальности отправьте ID админа вместо user_id ниже:
        send_telegram_message(user_id, f"✅ Заявка принята! Наш менеджер свяжется с вами.\nВаш ID: {user_id}")
        # Логирование
        db.save_broadcast(admin_msg, 'admin_notify', [user_id])
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error"}), 500

# --- API Admin: Login ---
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if not data: return jsonify({"status": "error", "message": "No JSON"}), 400
    
    password = data.get('password')
    if not password: return jsonify({"status": "error"}), 400

    entered_hash = db.hash_password(password)

    if config.ADMIN_PASSWORD_HASH is None:
        config.ADMIN_PASSWORD_HASH = entered_hash
        # В реальном проекте это не сохранится в файл config.py автоматически,
        # но для локального теста сработает в памяти.
        # Для продакшена нужно обновлять файл или использовать .env
        return jsonify({"status": "new_password_set"})

    if entered_hash == config.ADMIN_PASSWORD_HASH:
        return jsonify({"status": "success"})
    
    return jsonify({"status": "error"}), 401

# --- API Admin: Change Password ---
@app.route('/api/admin/change_password', methods=['POST'])
def admin_change_password():
    data = request.json
    if not data: return jsonify({"status": "error"}), 400

    old = data.get('old_password')
    new = data.get('new_password')
    
    if not old or not new: return jsonify({"status": "error", "message": "Missing fields"}), 400
    
    if db.hash_password(old) == config.ADMIN_PASSWORD_HASH:
        config.ADMIN_PASSWORD_HASH = db.hash_password(new)
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401

# --- Универсальный API Управления ---
@app.route('/api/admin/manage/<table_name>', methods=['GET', 'POST', 'DELETE'])
def admin_manage(table_name):
    # Простая проверка авторизации (в продакшене лучше через сессии)
    if not config.ADMIN_PASSWORD_HASH:
        return jsonify({"status": "error", "message": "Not logged in"}), 401

    if request.method == 'GET':
        search = request.args.get('search')
        sort_by = request.args.get('sort_by')
        order = request.args.get('order')
        
        filters = {'search': search, 'sort_by': sort_by, 'order': order}
        data = db.manage_table(table_name, 'get', filters)
        return jsonify(data)

    if request.method == 'DELETE':
        data = request.json
        ids = data.get('ids')
        if not ids:
            return jsonify({"status": "error", "message": "No IDs provided"}), 400
        
        db.manage_table(table_name, 'delete', {'ids': ids})
        return jsonify({"status": "success"})

    if request.method == 'POST':
        data = request.json
        message = data.get('message')
        target_ids = data.get('target_ids')

        # Если ID не переданы, берем всех пользователей
        recipients = []
        if target_ids:
            recipients = target_ids
        else:
            all_users = db.manage_table('users', 'get', {})
            # target_ids может быть строкой ID, а не числом из БД. 
            # В нашем случае ID пользователя это user_id, а не id записи.
            # Логика: берем user_id из target_ids (если они пришли как user_id)
            # Но в HTML мы передаем user_id при клике. Здесь надо уточнить.
            # Предположим, что target_ids - это список user_id (как в HTML value="${u.user_id}")
            recipients = target_ids 

        if not recipients:
             return jsonify({"status": "error", "message": "No recipients"}), 400

        sent_count = 0
        for uid in recipients:
            if send_telegram_message(uid, message):
                sent_count += 1
        
        type_str = 'all' if not target_ids else 'specific'
        db.save_broadcast(message, type_str, recipients)
        
        return jsonify({"status": "success", "sent_to": sent_count})

# --- Экспорт данных (CSV) ---
@app.route('/api/admin/export/<table_name>', methods=['GET'])
def export_data(table_name):
    if not config.ADMIN_PASSWORD_HASH:
        return jsonify({"error": "Auth required"}), 401

    try:
        # Получаем параметры из GET запроса
        search = request.args.get('search')
        sort_by = request.args.get('sort_by')
        order = request.args.get('order')
        
        filters = {'search': search, 'sort_by': sort_by, 'order': order}
        data = db.manage_table(table_name, 'get', filters)
        
        if not data:
            response = make_response("ID;Message\n")
            response.headers["Content-Type"] = "text/csv; charset=utf-8"
            return response

        # Генерация CSV в памяти
        output = io.StringIO()
        fieldnames = data[0].keys()
        writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=';', restval='')
        writer.writeheader()
        writer.writerows(data)
        
        output.seek(0)
        # Добавляем BOM для корректного открытия в Excel
        csv_bytes = io.BytesIO(output.getvalue().encode('utf-8-sig'))
        
        filename = f'export_{table_name}_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
        
        response = make_response(send_file(
            csv_bytes,
            mimetype='text/csv; charset=utf-8',
            as_attachment=True,
            download_name=filename
        ))
        
        # Заголовки для скачивания
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        
        return response

    except Exception as e:
        print(f"CSV export error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# --- HTML Routes ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin(): return render_template('admin.html')

if __name__ == '__main__':
    db.init_dbs()
    app.run(host='0.0.0.0', port=8000, debug=True)