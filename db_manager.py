import sqlite3
import hashlib
import json
import os
from datetime import datetime

DB_MAIN = "miniapp.db"
DB_BROADCAST = "broadcast.db"

def get_conn(db_file):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def init_dbs():
    # Создание базы пользователей
    if not os.path.exists(DB_MAIN):
        conn = get_conn(DB_MAIN)
        conn.execute('''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                first_name TEXT,
                username TEXT,
                comment TEXT,
                subscribe_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

    # Создание базы рассылок
    if not os.path.exists(DB_BROADCAST):
        conn = get_conn(DB_BROADCAST)
        conn.execute('''
            CREATE TABLE broadcast_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT,
                recipient_type TEXT,
                user_ids TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

def save_user(user_id, first_name, username, comment):
    try:
        conn = get_conn(DB_MAIN)
        cursor = conn.cursor()
        # Если юзер есть - обновляем, нет - создаем
        cursor.execute('''
            INSERT INTO users (user_id, first_name, username, comment)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
            first_name=excluded.first_name, username=excluded.username, comment=excluded.comment
        ''', (user_id, first_name, username, comment))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Error save_user: {e}")
        return False

def save_broadcast(message, recipient_type, user_ids):
    try:
        conn = get_conn(DB_BROADCAST)
        ids_str = json.dumps(user_ids) if isinstance(user_ids, list) else str(user_ids)
        conn.execute('''
            INSERT INTO broadcast_log (message, recipient_type, user_ids)
            VALUES (?, ?, ?)
        ''', (message, recipient_type, ids_str))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"DB Error save_broadcast: {e}")
        return False

def manage_table(table_name, action, filters=None):
    db_file = DB_MAIN if table_name == 'users' else DB_BROADCAST
    conn = get_conn(db_file)
    result = []
    
    try:
        if action == 'get':
            query = f"SELECT * FROM {table_name}"
            params = []
            
            # Фильтрация
            if filters and filters.get('search'):
                search_term = f"%{filters['search']}%"
                query += " WHERE "
                if table_name == 'users':
                    query += "user_id LIKE ? OR first_name LIKE ? OR username LIKE ? OR comment LIKE ?"
                    params.extend([search_term] * 4)
                else:
                    query += "message LIKE ? OR user_ids LIKE ?"
                    params.extend([search_term] * 2)
            
            # Сортировка
            sort_by = 'id'
            order = 'DESC'
            if filters:
                if filters.get('sort_by'): sort_by = filters.get('sort_by')
                if filters.get('order'): order = filters.get('order')

            allowed_sort = {
                'users': ['id', 'user_id', 'first_name', 'subscribe_date'],
                'broadcast_log': ['id', 'timestamp', 'recipient_type']
            }
            
            if sort_by in allowed_sort.get(table_name, []):
                query += f" ORDER BY {sort_by} {order}"
            
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]

        elif action == 'delete':
            ids = filters.get('ids', [])
            if ids:
                placeholders = ','.join(['?'] * len(ids))
                cursor = conn.cursor()
                cursor.execute(f"DELETE FROM {table_name} WHERE id IN ({placeholders})", ids)
                conn.commit()
                result = True

    except Exception as e:
        print(f"DB Manager Error ({action}): {e}")
    finally:
        conn.close()
    
    return result

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()