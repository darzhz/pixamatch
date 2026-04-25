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
    c.execute('''
        CREATE TABLE IF NOT EXISTS folders (
            id TEXT PRIMARY KEY,
            basket_id TEXT NOT NULL,
            name TEXT NOT NULL,
            image_paths TEXT NOT NULL, -- JSON array
            is_new BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (basket_id) REFERENCES baskets (id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cull_links (
            token TEXT PRIMARY KEY,
            basket_id TEXT NOT NULL,
            config TEXT, -- JSON config (e.g. filter by person)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (basket_id) REFERENCES baskets (id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

class MetadataDB:
    def __init__(self):
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

    # Folders
    def create_folder(self, folder_id, basket_id, name, image_paths):
        import json
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO folders (id, basket_id, name, image_paths) VALUES (?, ?, ?, ?)",
            (folder_id, basket_id, name, json.dumps(image_paths))
        )
        conn.commit()
        conn.close()

    def list_folders(self, basket_id):
        import json
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, image_paths, is_new, created_at FROM folders WHERE basket_id = ? ORDER BY created_at DESC", (basket_id,))
        rows = c.fetchall()
        conn.close()
        return [{
            "id": r[0],
            "name": r[1],
            "image_paths": json.loads(r[2]),
            "is_new": bool(r[3]),
            "created_at": r[4]
        } for r in rows]

    def get_folder(self, folder_id):
        import json
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT id, name, image_paths, is_new, created_at FROM folders WHERE id = ?", (folder_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "id": row[0],
                "name": row[1],
                "image_paths": json.loads(row[2]),
                "is_new": bool(row[3]),
                "created_at": row[4]
            }
        return None

    def mark_folder_read(self, folder_id):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("UPDATE folders SET is_new = 0 WHERE id = ?", (folder_id,))
        conn.commit()
        conn.close()

    # Cull Links
    def create_cull_link(self, token, basket_id, config=None):
        import json
        conn = self._get_conn()
        c = conn.cursor()
        c.execute(
            "INSERT INTO cull_links (token, basket_id, config) VALUES (?, ?, ?)",
            (token, basket_id, json.dumps(config) if config else None)
        )
        conn.commit()
        conn.close()

    def get_cull_link(self, token):
        import json
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("SELECT basket_id, config FROM cull_links WHERE token = ?", (token,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "basket_id": row[0],
                "config": json.loads(row[1]) if row[1] else None
            }
        return None
