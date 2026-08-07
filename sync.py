"""
数据同步模块
从私有 GitHub 仓库下载/上传数据库文件，确保数据不丢且不公开
"""

import os
import base64
import logging
from pathlib import Path

import requests

from config import DATA_DIR, DATABASE_PATH

logger = logging.getLogger(__name__)

# 私有数据仓库配置
DATA_REPO = os.environ.get("DATA_REPO", "")  # 格式: owner/repo
GITHUB_TOKEN = os.environ.get("DATA_REPO_TOKEN", "")  # GitHub PAT
DB_PATH_IN_REPO = "shopee_monitor.db"  # 数据库在私有仓库中的路径


def _api_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def download_db():
    """从私有仓库下载最新数据库"""
    if not DATA_REPO or not GITHUB_TOKEN:
        return False

    url = f"https://api.github.com/repos/{DATA_REPO}/contents/{DB_PATH_IN_REPO}"
    try:
        resp = requests.get(url, headers=_api_headers(), timeout=15)
        if resp.status_code == 200:
            content = base64.b64decode(resp.json()["content"])
            with open(DATABASE_PATH, "wb") as f:
                f.write(content)
            logger.info(f"数据库已从私有仓库下载 ({len(content)} bytes)")
            return True
        elif resp.status_code == 404:
            logger.info("私有仓库中暂无数据库，使用本地新建")
            return False
        else:
            logger.warning(f"下载数据库失败: HTTP {resp.status_code}")
            return False
    except Exception as e:
        logger.warning(f"下载数据库异常: {e}")
        return False


def upload_db():
    """上传数据库到私有仓库（数据备份）"""
    if not DATA_REPO or not GITHUB_TOKEN:
        return False

    if not DATABASE_PATH.exists():
        return False

    with open(DATABASE_PATH, "rb") as f:
        content = f.read()

    encoded = base64.b64encode(content).decode()

    # 先获取当前文件 SHA（如果存在），用于更新
    url = f"https://api.github.com/repos/{DATA_REPO}/contents/{DB_PATH_IN_REPO}"
    sha = None
    try:
        resp = requests.get(url, headers=_api_headers(), timeout=10)
        if resp.status_code == 200:
            sha = resp.json()["sha"]
    except Exception:
        pass

    payload = {
        "message": f"数据库更新 {Path(DATABASE_PATH).stat().st_size} bytes",
        "content": encoded,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=_api_headers(), json=payload, timeout=15)
        if resp.status_code in (200, 201):
            logger.info("数据库已同步到私有仓库")
            return True
        else:
            logger.warning(f"上传数据库失败: HTTP {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"上传数据库异常: {e}")
        return False
