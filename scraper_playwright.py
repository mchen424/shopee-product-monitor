"""
Shopee 商品数据抓取 — Playwright 浏览器渲染版本
使用 browser automation + stealth 绕过检测

注意: Shopee 反爬较强，此方法在某些网络环境下可能仍然失败。
建议配合代理/VPS 使用，或使用手动输入模式。
"""

import re
import json
import os
import time
import logging
from typing import Optional, Dict

from config import SHOPEE_DOMAINS

logger = logging.getLogger(__name__)

# 从环境变量加载 Shopee Cookie（JSON 格式）
def _load_cookies() -> list:
    raw = os.environ.get("SHOPEE_COOKIES", "")
    if not raw:
        return []
    try:
        cookies = json.loads(raw)
        # 补充 domain 和 path
        for c in cookies:
            if "domain" not in c:
                c["domain"] = ".shopee.com.my"
            if "path" not in c:
                c["path"] = "/"
            if "httpOnly" not in c:
                c["httpOnly"] = True
            if "secure" not in c:
                c["secure"] = True
            if "sameSite" not in c:
                c["sameSite"] = "Lax"
        return cookies
    except json.JSONDecodeError:
        return []

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    from playwright_stealth import Stealth
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False


def fetch_product_info(item_id: str, shop_id: str, region: str) -> Dict:
    """
    使用 Playwright 获取商品信息
    策略: 拦截 PDP API 响应 → DOM 解析 → 页面文本正则
    """
    if not HAS_PLAYWRIGHT:
        return _empty_result("Playwright 未安装。运行: pip install playwright && playwright install chromium")

    domain = SHOPEE_DOMAINS[region]
    product_url = f"https://{domain}/product/{shop_id}/{item_id}/"

    p = None
    try:
        p = sync_playwright().start()
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        # 注入 Shopee Cookie（从环境变量加载）
        cookies = _load_cookies()
        if cookies:
            context.add_cookies(cookies)
            logger.info(f"已注入 {len(cookies)} 个 Shopee Cookie")

        # Stealth 模式
        if HAS_STEALTH:
            try:
                stealth = Stealth()
                stealth.apply_stealth_sync(page)
            except Exception as e:
                logger.debug(f"Stealth 应用失败: {e}")

        # 拦截非必要资源
        page.route(
            re.compile(r"\.(png|jpg|jpeg|gif|svg|webp|ico|woff2?|ttf|mp4|webm)(\?.*)?$"),
            lambda route: route.abort(),
        )

        # 拦截 API 响应
        api_items = []

        def handle_response(response):
            url = response.url
            if response.status != 200:
                return
            # PDP 商品详情 API
            if "/api/v4/pdp/get_pc" in url or "/api/v4/item/get" in url:
                try:
                    data = response.json()
                    # 检查是否有 data 字段且不包含错误
                    if "data" in data and data["data"] and not data.get("error"):
                        api_items.append(data["data"])
                        logger.info(f"截获 API: {url.split('?')[0].split('/')[-1]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        # 加载页面
        logger.info(f"加载: {product_url}")
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning(f"页面加载异常: {e}")

        # 等待 API 完成
        page.wait_for_timeout(8000)

        # 检查是否被重定向到验证页
        if "/verify/" in page.url:
            logger.warning("页面被重定向到验证页，API 数据可能不完整")

            # 即使被重定向，API 也可能已返回数据
            if api_items:
                item = api_items[0]
                result = _parse_item(item, region)
                if result["title"] or result["price"]:
                    result["success"] = True
                    return result

            # 尝试加载更多时间
            page.wait_for_timeout(5000)

        # 处理 API 数据
        if api_items:
            item = api_items[0]
            result = _parse_item(item, region)
            if result["title"] or result["price"]:
                result["success"] = True
                return result

        # 备用方案: 从页面提取
        result = _parse_from_page(page, region)
        if result["title"] or result["price"]:
            result["success"] = True
            return result

        result = _empty_result("无法从页面提取数据，请检查链接是否有效，或使用手动输入模式")

    except Exception as e:
        result = _empty_result(f"Playwright 错误: {e}")
        logger.error(f"抓取异常: {e}")
    finally:
        if p:
            try:
                p.stop()
            except Exception:
                pass

    return result


def _parse_item(item: dict, region: str) -> dict:
    """解析 API 返回的商品数据"""
    result = {}

    result["title"] = item.get("name") or item.get("title")

    price_raw = item.get("price", 0)
    if price_raw:
        try:
            result["price"] = round(int(price_raw) / 100000, 2)
        except (ValueError, TypeError):
            pass

    price_before = item.get("price_before_discount") or item.get("original_price", 0)
    if price_before and price_before > price_raw:
        try:
            result["original_price"] = round(int(price_before) / 100000, 2)
        except (ValueError, TypeError):
            pass

    result["stock"] = item.get("stock") or item.get("total_stock", 0)

    sold = item.get("historical_sold") or item.get("sold", 0)
    result["historical_sold"] = sold if sold else 0

    rating = item.get("item_rating") or item.get("rating", {})
    if rating:
        result["rating_star"] = rating.get("rating_star")
        rc = rating.get("rating_count")
        if rc:
            result["rating_count"] = sum(rc) if isinstance(rc, list) else rc

    image = item.get("image", "")
    if image and not str(image).startswith("http"):
        result["image_url"] = f"https://cf.shopee.{region}/file/{image}"
    elif image:
        result["image_url"] = str(image)

    return result


def _parse_from_page(page, region: str) -> dict:
    """从渲染后的页面提取数据"""
    result = {}
    try:
        page_text = page.inner_text("body")

        # 标题
        page_title = page.title()
        if page_title:
            title = re.sub(r'\s*\|\s*Shopee\s+\w+.*$', '', page_title).strip()
            if title and "Shopee" not in title[:10]:
                result["title"] = title

        # 价格 - 根据区域匹配货币符号
        currency_patterns = {
            "my": r'RM\s*([\d,]+\.?\d*)',
            "sg": r'S\$\s*([\d,]+\.?\d*)',
            "th": r'฿\s*([\d,]+\.?\d*)',
            "ph": r'₱\s*([\d,]+\.?\d*)',
            "id": r'Rp\s*([\d,]+\.?\d*)',
            "vn": r'₫\s*([\d,]+\.?\d*)',
            "tw": r'NT\$\s*([\d,]+\.?\d*)',
            "br": r'R\$\s*([\d,]+\.?\d*)',
        }
        pat = currency_patterns.get(region, r'[\$\u00A3\u20AC\u00A5]\s*([\d,]+\.?\d*)')
        match = re.search(pat, page_text)
        if match:
            try:
                result["price"] = float(match.group(1).replace(',', ''))
            except ValueError:
                pass

        # 销量
        sold_match = re.search(r'([\d,.]+[kK]?)\s*(?:sold|Sold|terjual|đã bán)', page_text)
        if sold_match:
            s = sold_match.group(1).replace(',', '')
            if 'k' in s.lower():
                result["historical_sold"] = int(float(s.lower().replace('k', '')) * 1000)
            else:
                try:
                    result["historical_sold"] = int(s)
                except ValueError:
                    pass

        # 评分
        rating_match = re.search(r'([\d.]+)\s*(?:\/\s*5|★)', page_text)
        if rating_match:
            try:
                result["rating_star"] = float(rating_match.group(1))
            except ValueError:
                pass

    except Exception as e:
        logger.debug(f"页面解析失败: {e}")

    return result


def _empty_result(error: str = None) -> dict:
    return {
        "title": None, "price": None, "original_price": None,
        "stock": None, "historical_sold": None,
        "rating_star": None, "rating_count": None,
        "image_url": None, "success": False, "error": error,
    }
