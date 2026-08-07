"""
通知模块 — 企业微信机器人 + PushPlus 双通道
抓取完成后自动推送报告
"""

import os
import logging
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# 企业微信 Webhook（默认使用环境变量，无 7 天限制）
WECOM_WEBHOOK = os.environ.get("WECOM_WEBHOOK", "")

# PushPlus 备用通道
PUSHPLUS_URL = "http://www.pushplus.plus/send"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("PUSHPLUS_KEY")


def send_wecom_markdown(content: str) -> bool:
    """通过企业微信机器人发送 Markdown 消息"""
    if not WECOM_WEBHOOK:
        return False

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }

    try:
        resp = requests.post(WECOM_WEBHOOK, json=payload, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("企业微信通知发送成功")
            return True
        else:
            logger.warning(f"企业微信发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"企业微信请求异常: {e}")
        return False


def send_pushplus(title: str, content: str) -> bool:
    """通过 PushPlus 发送通知（备用）"""
    if not PUSHPLUS_TOKEN:
        return False

    payload = {
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "html",
    }

    try:
        resp = requests.post(PUSHPLUS_URL, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 200:
            logger.info("PushPlus 通知发送成功")
            return True
        else:
            logger.warning(f"PushPlus 发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"PushPlus 请求异常: {e}")
        return False


def send_scrape_report(
    success_count: int,
    error_count: int,
    total: int,
    errors: Optional[list] = None,
) -> tuple:
    """
    发送抓取结果报告，同时尝试企微和 PushPlus

    返回: (企微成功, PushPlus成功)
    """
    today = date.today().isoformat()

    # 生成企微 Markdown 消息
    if error_count == 0 and success_count == total:
        md = (
            f"## Shopee 监控报告 ({today})\n"
            f"> 监控商品: **{total}** 个\n"
            f"> 成功: <font color=\"info\">{success_count}</font>\n"
            f"> 失败: <font color=\"info\">{error_count}</font>\n"
            f"\n<font color=\"info\">全部商品数据更新正常</font>"
        )
        title = f"Shopee 监控 - {total}/{total} 全部成功"
        html = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个 | 成功: <b style='color:green'>{success_count}</b> | 失败: {error_count}</p>"
            f"<p style='color:green'>全部商品数据更新正常</p>"
        )
    elif error_count > 0 and success_count > 0:
        md = (
            f"## Shopee 监控报告 ({today})\n"
            f"> 监控商品: **{total}** 个\n"
            f"> 成功: <font color=\"info\">{success_count}</font>\n"
            f"> 失败: <font color=\"warning\">{error_count}</font>\n"
        )
        if errors:
            md += "\n**失败详情:**\n"
            for err in errors[:5]:
                md += f"> - **{err['product']}**: {err['error'][:80]}\n"
            if len(errors) > 5:
                md += f"> - ...还有 {len(errors) - 5} 个\n"
            md += "\n自动抓取被 Shopee 反爬拦截是正常现象，请打开 Streamlit 使用手动录入补充数据。"

        title = f"Shopee 监控 - {success_count}/{total} 成功，{error_count} 失败"
        html = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个</p>"
            f"<p>成功: <b style='color:green'>{success_count}</b></p>"
            f"<p>失败: <b style='color:red'>{error_count}</b></p>"
        )
        if errors:
            html += "<hr><h4>失败详情:</h4><ul>"
            for err in errors[:5]:
                html += f"<li><b>{err['product']}</b>: <span style='color:red'>{err['error']}</span></li>"
            if len(errors) > 5:
                html += f"<li>...还有 {len(errors) - 5} 个商品失败</li>"
            html += "</ul>"
            html += "<p style='color:gray'>自动抓取被 Shopee 反爬拦截是正常现象，请打开 Streamlit 使用手动录入补充数据。</p>"
    else:
        md = (
            f"## Shopee 监控报告 ({today})\n"
            f"> 监控商品: **{total}** 个\n"
            f"> 成功: <font color=\"info\">0</font>\n"
            f"> 失败: <font color=\"warning\">{total}</font>\n"
            f"\n<font color=\"warning\">所有商品均被 Shopee 反爬拦截</font>\n"
            f"\n请打开 Streamlit 使用手动录入功能补充今日数据。"
        )
        title = f"Shopee 监控 - {total} 个商品全部抓取失败"
        html = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个</p>"
            f"<p>成功: <b style='color:green'>0</b></p>"
            f"<p>失败: <b style='color:red'>{total}</b></p>"
            f"<p style='color:red'>所有商品均被 Shopee 反爬拦截</p>"
            f"<p style='color:gray'>请打开 Streamlit 使用手动录入功能补充今日数据。</p>"
        )

    wecom_ok = send_wecom_markdown(md)
    pushplus_ok = send_pushplus(title, html)

    if not wecom_ok and not pushplus_ok:
        logger.warning("所有通知渠道均发送失败，请检查配置")

    return wecom_ok, pushplus_ok
