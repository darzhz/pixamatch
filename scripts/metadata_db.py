import sqlite3
import os
from datetime import datetime
from .logger import debug_log

DB_PATH = "metadata.db"

def init_db():
    debug_log(f"Initializing SQLite DB at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS baskets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            image_count INTEGER DEFAULT 0,
            faces_indexed INTEGER DEFAULT 0,
            is_live BOOLEAN DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

class MetadataDB:
    def __init__(self):
        if not os.path.exists(DB_PATH):
            init_db()
    
    def _get_conn(self):
        return sqlite3.connect(DB_PATH)

    def create_basket(self, basket_id, name):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO baskets (id, name) VALUES (?, ?)", (basket_id, name))
        conn.commit()
        conn.close()
        debug_log(f"Basket {basket_id} saved to SQLite.")

    def get_basket(self, basket_id):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, created_at, image_count, faces_indexed, is_live FROM baskets WHERE id = ?", (basket_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "created_at": row[2],
                "image_count": row[3],
                "faces_indexed": row[4],
                "is_live": bool(row[5])
            }
        return None

    def update_stats(self, basket_id, image_count, faces_indexed):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("UPDATE baskets SET image_count = ?, faces_indexed = ? WHERE id = ?", (image_count, faces_indexed, basket_id))
        conn.commit()
        conn.close()

    def delete_basket(self, basket_id):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("DELETE FROM baskets WHERE id = ?", (basket_id,))
        conn.commit()
        conn.close()
        debug_log(f"Basket {basket_id} deleted from SQLite.")

    def list_baskets(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, created_at FROM baskets ORDER BY created_at DESC")
        rows = c.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]
