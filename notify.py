"""
PushPlus 微信推送通知模块
当自动抓取失败时，通过微信发送告警通知
"""

import os
import json
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PUSHPLUS_URL = "http://www.pushplus.plus/send"


def get_token() -> Optional[str]:
    """获取 PushPlus Token（环境变量或配置文件）"""
    return os.environ.get("PUSHPLUS_TOKEN") or os.environ.get("PUSHPLUS_KEY")


def send_notification(title: str, content: str, template: str = "html") -> bool:
    """
    发送 PushPlus 微信推送通知

    参数:
        title: 通知标题
        content: 通知内容（支持 HTML）
        template: 消息模板类型 (html / txt / json / markdown)

    返回:
        是否发送成功
    """
    token = get_token()
    if not token:
        logger.warning("未配置 PUSHPLUS_TOKEN，跳过通知发送")
        return False

    payload = {
        "token": token,
        "title": title,
        "content": content,
        "template": template,
    }

    try:
        resp = requests.post(PUSHPLUS_URL, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 200:
            logger.info(f"PushPlus 通知发送成功: {title}")
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
) -> bool:
    """
    发送抓取结果报告

    参数:
        success_count: 成功数量
        error_count: 失败数量
        total: 总商品数
        errors: 错误详情列表，每个元素为 {"product": "商品名", "error": "错误信息"}

    返回:
        是否发送成功
    """
    if error_count == 0 and success_count == total:
        title = f"Shopee 监控 - {total}/{total} 全部成功"
        content = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个</p>"
            f"<p>成功: <b style='color:green'>{success_count}</b></p>"
            f"<p>失败: <b>{error_count}</b></p>"
            f"<p style='color:green'>全部商品数据更新正常</p>"
        )
    elif error_count > 0 and success_count > 0:
        title = f"Shopee 监控 - {success_count}/{total} 成功，{error_count} 失败"
        content = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个</p>"
            f"<p>成功: <b style='color:green'>{success_count}</b></p>"
            f"<p>失败: <b style='color:red'>{error_count}</b></p>"
        )
        if errors:
            content += "<hr><h4>失败详情:</h4><ul>"
            for err in errors[:5]:  # 最多显示5条
                content += (
                    f"<li><b>{err['product']}</b>: "
                    f"<span style='color:red'>{err['error']}</span></li>"
                )
            if len(errors) > 5:
                content += f"<li>...还有 {len(errors) - 5} 个商品失败</li>"
            content += "</ul>"
            content += (
                "<p style='color:gray'>"
                "自动抓取被 Shopee 反爬拦截是正常现象，"
                "请打开 Streamlit 使用「手动录入」补充数据。</p>"
            )
    else:
        title = f"Shopee 监控 - {total} 个商品全部抓取失败"
        content = (
            f"<h3>今日抓取报告</h3>"
            f"<p>监控商品: <b>{total}</b> 个</p>"
            f"<p>成功: <b style='color:green'>0</b></p>"
            f"<p>失败: <b style='color:red'>{total}</b></p>"
            f"<p style='color:red'>所有商品均被 Shopee 反爬拦截</p>"
            f"<p style='color:gray'>"
            f"请打开 Streamlit 使用「手动录入」功能补充今日数据。</p>"
        )

    return send_notification(title, content)
