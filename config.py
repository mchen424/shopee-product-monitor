"""
Shopee Monitor 配置文件
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent

# 数据目录
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# 数据库路径
DATABASE_PATH = DATA_DIR / "shopee_monitor.db"

# Shopee 各站点域名映射
SHOPEE_DOMAINS = {
    "my": "shopee.com.my",      # 马来西亚
    "sg": "shopee.sg",           # 新加坡
    "th": "shopee.co.th",        # 泰国
    "ph": "shopee.ph",           # 菲律宾
    "id": "shopee.co.id",        # 印尼
    "vn": "shopee.vn",           # 越南
    "tw": "shopee.tw",           # 中国台湾
    "br": "shopee.com.br",       # 巴西
}

# 请求头模板
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
}

# 请求超时（秒）
REQUEST_TIMEOUT = 30

# 请求重试次数
MAX_RETRIES = 3

# 请求间隔（秒）
REQUEST_DELAY = 2

# 数据保留天数（超过后归档）
DATA_RETENTION_DAYS = 365
