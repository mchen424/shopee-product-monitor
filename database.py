"""
Shopee Monitor 数据库模块
管理商品信息和每日监控快照
"""

import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from config import DATABASE_PATH


def get_connection():
    """获取数据库连接"""
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """数据库上下文管理器"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """初始化数据库，创建表"""
    with get_db() as conn:
        conn.executescript("""
            -- 监控商品表
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                item_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                region TEXT NOT NULL,
                title TEXT,
                image_url TEXT,
                current_price REAL,
                original_price REAL,
                current_stock INTEGER,
                current_sold INTEGER,
                rating_star REAL,
                rating_count INTEGER,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_check_at TIMESTAMP,
                check_error TEXT
            );

            -- 每日快照表
            CREATE TABLE IF NOT EXISTS daily_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                snapshot_date DATE NOT NULL,
                price REAL,
                original_price REAL,
                stock INTEGER,
                sold_count INTEGER,
                rating_star REAL,
                rating_count INTEGER,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                UNIQUE(product_id, snapshot_date)
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
            CREATE INDEX IF NOT EXISTS idx_products_region ON products(region);
            CREATE INDEX IF NOT EXISTS idx_snapshots_product_date ON daily_snapshots(product_id, snapshot_date);
            CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date);
        """)


# ============ 商品 CRUD ============

def add_product(url: str, item_id: str, shop_id: str, region: str,
                title: str = None, image_url: str = None,
                price: float = None, original_price: float = None,
                stock: int = None, sold: int = None,
                rating_star: float = None, rating_count: int = None) -> int:
    """添加监控商品"""
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO products (url, item_id, shop_id, region, title, image_url,
                current_price, original_price, current_stock, current_sold,
                rating_star, rating_count, updated_at, last_check_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (url, item_id, shop_id, region, title, image_url,
              price, original_price, stock, sold, rating_star, rating_count))
        return cursor.lastrowid


def get_all_products(status: str = "active") -> List[Dict]:
    """获取所有监控商品"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM products WHERE status = ? ORDER BY created_at DESC",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_product(product_id: int) -> Optional[Dict]:
    """获取单个商品"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return dict(row) if row else None


def update_product(product_id: int, **kwargs):
    """更新商品信息"""
    if not kwargs:
        return
    kwargs["updated_at"] = datetime.now().isoformat()
    fields = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [product_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE products SET {fields} WHERE id = ?", values
        )


def delete_product(product_id: int):
    """删除商品（软删除）"""
    with get_db() as conn:
        conn.execute(
            "UPDATE products SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (product_id,)
        )


# ============ 快照 CRUD ============

def save_snapshot(product_id: int, snapshot_date: date = None,
                  price: float = None, original_price: float = None,
                  stock: int = None, sold_count: int = None,
                  rating_star: float = None, rating_count: int = None,
                  title: str = None) -> bool:
    """保存每日快照，避免重复"""
    if snapshot_date is None:
        snapshot_date = date.today()
    with get_db() as conn:
        try:
            conn.execute("""
                INSERT INTO daily_snapshots (product_id, snapshot_date, price, original_price,
                    stock, sold_count, rating_star, rating_count, title)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (product_id, snapshot_date.isoformat(), price, original_price,
                  stock, sold_count, rating_star, rating_count, title))
            return True
        except sqlite3.IntegrityError:
            # 今天已存在快照，更新
            conn.execute("""
                UPDATE daily_snapshots SET
                    price = ?, original_price = ?, stock = ?, sold_count = ?,
                    rating_star = ?, rating_count = ?, title = ?
                WHERE product_id = ? AND snapshot_date = ?
            """, (price, original_price, stock, sold_count,
                  rating_star, rating_count, title,
                  product_id, snapshot_date.isoformat()))
            return False


def get_snapshots(product_id: int, days: int = 30) -> List[Dict]:
    """获取商品历史快照"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM daily_snapshots
            WHERE product_id = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (product_id, days)).fetchall()
        return [dict(r) for r in rows]


def get_latest_snapshot(product_id: int) -> Optional[Dict]:
    """获取最新快照"""
    with get_db() as conn:
        row = conn.execute("""
            SELECT * FROM daily_snapshots
            WHERE product_id = ?
            ORDER BY snapshot_date DESC
            LIMIT 1
        """, (product_id,)).fetchone()
        return dict(row) if row else None


def get_snapshot_count(product_id: int) -> int:
    """获取快照数量"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM daily_snapshots WHERE product_id = ?",
            (product_id,)
        ).fetchone()
        return row["cnt"]


# ============ 统计 ============

def get_price_change(product_id: int, days: int = 1) -> Optional[Dict]:
    """计算价格变化"""
    with get_db() as conn:
        # 取最早和最晚的快照
        rows = conn.execute("""
            SELECT snapshot_date, price FROM daily_snapshots
            WHERE product_id = ? AND price IS NOT NULL
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (product_id, days + 1)).fetchall()
        if len(rows) >= 2:
            latest = rows[0]["price"]
            earliest = rows[-1]["price"]
            change = latest - earliest
            change_pct = (change / earliest * 100) if earliest != 0 else 0
            return {
                "latest_price": latest,
                "change": change,
                "change_pct": change_pct,
                "direction": "up" if change > 0 else ("down" if change < 0 else "flat")
            }
        return None


def get_sales_change(product_id: int, days: int = 1) -> Optional[Dict]:
    """计算销量变化"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT snapshot_date, sold_count FROM daily_snapshots
            WHERE product_id = ? AND sold_count IS NOT NULL
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (product_id, days + 1)).fetchall()
        if len(rows) >= 2:
            latest = rows[0]["sold_count"]
            earliest = rows[-1]["sold_count"]
            change = latest - earliest
            return {
                "latest_sold": latest,
                "daily_sold": change,
                "direction": "up" if change > 0 else ("down" if change < 0 else "flat")
            }
        return None
