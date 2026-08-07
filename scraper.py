"""
Shopee 商品数据抓取模块
支持通过公开 API、HTML 解析等方式获取商品价格、销量、评分等信息
"""

import re
import json
import time
import logging
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse, urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup

from config import SHOPEE_DOMAINS, REQUEST_TIMEOUT, MAX_RETRIES, REQUEST_DELAY

logger = logging.getLogger(__name__)

# 更完善的浏览器请求头
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "X-Requested-With": "XMLHttpRequest",
}


# ============ URL 解析 ============

def parse_shopee_url(url: str) -> Optional[Dict[str, str]]:
    """
    解析 Shopee 商品链接，提取 region、item_id、shop_id

    支持的 URL 格式：
    - https://shopee.com.my/product/123/456/
    - https://shopee.sg/Product-Name-i.123.456
    - https://shopee.co.id/product/123/456/
    - https://shopee.tw/商品名-i.123.456
    """
    url = url.strip()
    parsed = urlparse(url)

    # 识别区域
    region = None
    for key, domain in SHOPEE_DOMAINS.items():
        if domain in parsed.netloc:
            region = key
            break

    if not region:
        raise ValueError(
            f"无法识别 Shopee 站点，请确认链接格式。支持的站点："
            f"{', '.join(SHOPEE_DOMAINS.values())}"
        )

    item_id, shop_id = None, None

    # 格式1: /product/{shop_id}/{item_id}/
    product_match = re.search(r'/product/(\d+)/(\d+)', parsed.path)
    if product_match:
        shop_id = product_match.group(1)
        item_id = product_match.group(2)

    # 格式2: i.{shop_id}.{item_id}
    if not item_id:
        i_match = re.search(r'i\.(\d+)\.(\d+)', url)
        if i_match:
            shop_id = i_match.group(1)
            item_id = i_match.group(2)

    # 格式3: 从查询参数提取
    if not item_id:
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        item_id = qs.get("itemid", [None])[0]
        shop_id = qs.get("shopid", [None])[0]

    if not item_id or not shop_id:
        raise ValueError(
            f"无法从链接中提取商品ID，请确认链接格式正确。\n"
            f"支持的格式: shopee.xx/product/shop_id/item_id/ 或 shopee.xx/...-i.shop_id.item_id"
        )

    return {
        "region": region,
        "domain": SHOPEE_DOMAINS[region],
        "item_id": item_id,
        "shop_id": shop_id,
    }


# ============ Session & Request ============

def _create_session(domain: str) -> requests.Session:
    """创建带 cookie 的 session，使用 curl_cffi 模拟 Chrome TLS 指纹绕过 Cloudflare"""
    session = requests.Session(impersonate="chrome131")
    session.headers.update(BROWSER_HEADERS)

    try:
        # 先访问首页获取 cookie
        session.get(
            f"https://{domain}/",
            headers=BROWSER_HEADERS,
            timeout=15,
        )
    except Exception as e:
        logger.debug(f"获取首页 cookie 失败（可忽略）: {e}")

    return session


def _make_request_with_session(session: requests.Session, url: str,
                                headers: dict = None, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    """使用 session 发送请求，带重试"""
    if headers is None:
        headers = API_HEADERS.copy()

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(url, headers=headers, timeout=timeout)
            if response.status_code == 403:
                logger.warning(f"收到 403，等待后重试...")
                time.sleep(REQUEST_DELAY * (attempt + 2))
                continue
            response.raise_for_status()
            return response
        except Exception as e:
            last_error = e
            logger.warning(f"请求失败 (第 {attempt + 1}/{MAX_RETRIES} 次): {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(REQUEST_DELAY * (attempt + 1))

    if last_error:
        raise last_error
    raise Exception("Max retries exceeded")


# ============ 数据抓取 ============

def fetch_product_info(item_id: str, shop_id: str, region: str) -> Dict:
    """
    获取 Shopee 商品详细信息
    尝试多种方式：API → HTML 解析

    返回:
    {
        "title": str,
        "price": float,          # 当前价格（已换算为显示价格）
        "original_price": float,  # 原价
        "stock": int,
        "historical_sold": int,   # 历史销量
        "rating_star": float,
        "rating_count": int,
        "image_url": str,
        "success": bool,
        "error": str or None,
    }
    """
    domain = SHOPEE_DOMAINS[region]

    result = {
        "title": None,
        "price": None,
        "original_price": None,
        "stock": None,
        "historical_sold": None,
        "rating_star": None,
        "rating_count": None,
        "image_url": None,
        "success": False,
        "error": None,
    }

    session = _create_session(domain)

    # ====== 方式1: Playwright 浏览器渲染 (最可靠) ======
    try:
        from scraper_playwright import fetch_product_info as fetch_pw
        pw_result = fetch_pw(item_id, shop_id, region)
        if pw_result["success"]:
            return pw_result
        logger.info(f"Playwright 未获取到数据: {pw_result.get('error')}")
    except ImportError:
        logger.debug("scraper_playwright 不可用，跳过")
    except Exception as e:
        logger.warning(f"Playwright 抓取出错: {e}")

    # ====== 方式2: API 请求 ======
    api_result = _try_api_fetch(session, item_id, shop_id, domain, region)
    if api_result["success"]:
        return api_result

    # ====== 方式3: HTML 页面解析 ======
    html_result = _try_html_fetch(session, item_id, shop_id, domain, region)
    if html_result["success"]:
        return html_result

    # 都失败了
    result["error"] = api_result.get("error") or html_result.get("error") or "所有抓取方式均失败"
    return result


def _try_api_fetch(session: requests.Session, item_id: str, shop_id: str,
                   domain: str, region: str) -> Dict:
    """通过 Shopee API 获取商品信息"""
    api_url = f"https://{domain}/api/v4/item/get?itemid={item_id}&shopid={shop_id}"

    headers = API_HEADERS.copy()
    headers["Referer"] = f"https://{domain}/product/{shop_id}/{item_id}/"

    # 从 cookie 中提取 CSRF token 并添加到请求头
    csrf_token = None
    for cookie in session.cookies:
        if 'csrf' in cookie.name.lower():
            csrf_token = cookie.value
            break

    if csrf_token:
        headers["x-csrftoken"] = csrf_token

    result = {
        "title": None, "price": None, "original_price": None,
        "stock": None, "historical_sold": None,
        "rating_star": None, "rating_count": None,
        "image_url": None, "success": False, "error": None,
    }

    try:
        resp = _make_request_with_session(session, api_url, headers=headers)
        data = resp.json()

        if "data" not in data or data.get("error"):
            error_msg = data.get("error_msg", data.get("error", "API 返回空数据"))
            result["error"] = f"API 错误: {error_msg}"
            return result

        item = data["data"]
        _parse_item_data(item, region, result)
        result["success"] = True

    except Exception as e:
        result["error"] = f"API 请求/解析失败: {e}"

    return result


def _try_html_fetch(session: requests.Session, item_id: str, shop_id: str,
                    domain: str, region: str) -> Dict:
    """通过 HTML 页面解析商品信息（正则提取嵌入的 JSON 数据）"""
    product_url = f"https://{domain}/product/{shop_id}/{item_id}/"

    result = {
        "title": None, "price": None, "original_price": None,
        "stock": None, "historical_sold": None,
        "rating_star": None, "rating_count": None,
        "image_url": None, "success": False, "error": None,
    }

    try:
        resp = _make_request_with_session(session, product_url, headers=BROWSER_HEADERS)
        html = resp.text

        # 方法A: 从 __NEXT_DATA__ 或 window.__INITIAL_STATE__ 提取
        # Shopee 在页面中嵌入 JSON 初始状态
        json_data = _extract_json_from_html(html)
        if json_data:
            # 尝试从不同可能的路径提取数据
            item = _find_item_in_json(json_data, item_id, shop_id)
            if item:
                _parse_item_data(item, region, result)
                result["success"] = True
                return result

        # 方法B: 正则从 HTML 提取关键信息
        soup = BeautifulSoup(html, "lxml")

        # 标题
        title_tag = soup.find("title")
        if title_tag:
            title_text = title_tag.text.strip()
            # 去掉 " | Shopee Malaysia" 等后缀
            title_text = re.sub(r'\s*\|?\s*Shopee\s+\w+.*$', '', title_text)
            if title_text and "Shopee" not in title_text[:10]:
                result["title"] = title_text

        # 尝试从 meta 标签提取
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            result["title"] = og_title["content"]

        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            result["image_url"] = og_image["content"]

        og_price = soup.find("meta", property="product:price:amount")
        if og_price and og_price.get("content"):
            try:
                result["price"] = float(og_price["content"])
            except ValueError:
                pass

        if result["title"]:
            result["success"] = True
        else:
            result["error"] = "HTML 解析未获取到有效数据"

    except Exception as e:
        result["error"] = f"HTML 请求/解析失败: {e}"

    return result


def _extract_json_from_html(html: str) -> Optional[Dict]:
    """从 HTML 中提取嵌入的 JSON 数据"""
    # Shopee SPA 页面通常嵌入在 __INITIAL_STATE__ 或特定 script 中
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>',
        r'"item":\s*(\{.+?\})\s*[,;\}]',
        r'__NEXT_DATA__\s*=\s*({.+?});\s*</script>',
        r'<script[^>]*type="application/json"[^>]*>({.+?})</script>',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                json_str = match.group(1)
                # 修复可能的转义问题
                json_str = json_str.replace('\\"', '"')
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                continue

    # 尝试更宽松的提取
    start_markers = ['window.__INITIAL_STATE__=', '__NEXT_DATA__=']
    for marker in start_markers:
        idx = html.find(marker)
        if idx != -1:
            idx = html.find('{', idx)
            if idx != -1:
                depth = 0
                end = idx
                for i in range(idx, min(idx + 500000, len(html))):
                    if html[i] == '{':
                        depth += 1
                    elif html[i] == '}':
                        depth -= 1
                        if depth == 0:
                            end = i + 1
                            break
                if end > idx:
                    try:
                        return json.loads(html[idx:end])
                    except json.JSONDecodeError:
                        pass

    return None


def _find_item_in_json(data: Dict, item_id: str, shop_id: str):
    """在嵌套 JSON 中寻找商品数据"""
    if not isinstance(data, dict):
        return None

    # 直接匹配
    if str(data.get("itemid")) == str(item_id) and str(data.get("shopid")) == str(shop_id):
        return data

    # 递归搜索
    for key in ["item", "product", "data", "props", "pageProps", "initialState", "state"]:
        if key in data and isinstance(data[key], dict):
            result = _find_item_in_json(data[key], item_id, shop_id)
            if result:
                return result

    # 深度搜索（限制深度）
    for key, value in data.items():
        if isinstance(value, dict):
            result = _find_item_in_json(value, item_id, shop_id)
            if result:
                return result

    return None


def _parse_item_data(item: Dict, region: str, result: Dict):
    """从 item 数据中提取字段"""
    # 标题
    result["title"] = item.get("name", item.get("title", result.get("title")))

    # 价格
    price_raw = item.get("price", 0)
    if price_raw:
        result["price"] = _convert_price(price_raw, region)

    # 原价
    price_before = item.get("price_before_discount", item.get("original_price", 0))
    if price_before and price_before > price_raw:
        result["original_price"] = _convert_price(price_before, region)

    # 库存
    result["stock"] = item.get("stock", item.get("total_stock", 0))

    # 历史销量
    sold = item.get("historical_sold", item.get("sold", item.get("total_sold", 0)))
    result["historical_sold"] = sold if sold else 0

    # 评分
    rating_data = item.get("item_rating", item.get("rating", {}))
    if rating_data:
        result["rating_star"] = rating_data.get("rating_star", rating_data.get("star", None))
        rc = rating_data.get("rating_count", rating_data.get("count", None))
        if rc:
            if isinstance(rc, list):
                result["rating_count"] = sum(rc)
            else:
                result["rating_count"] = rc

    # 图片
    image = item.get("image", item.get("image_url", ""))
    if image and not str(image).startswith("http"):
        result["image_url"] = f"https://cf.shopee.{region}/file/{image}"
    elif image:
        result["image_url"] = str(image)


def _convert_price(price_raw: int, region: str) -> float:
    """
    将 Shopee API 返回的原始价格转换为实际显示价格
    Shopee 价格存储规则: price / 100000
    """
    try:
        price_raw = int(price_raw)
    except (ValueError, TypeError):
        return float(price_raw) if price_raw else 0.0
    return round(price_raw / 100000, 2)


def test_connection(region: str = "my") -> bool:
    """测试与 Shopee 的连接"""
    domain = SHOPEE_DOMAINS.get(region, "shopee.com.my")
    try:
        session = _create_session(domain)
        resp = session.get(
            f"https://{domain}/",
            headers=BROWSER_HEADERS,
            timeout=15,
        )
        return resp.status_code < 500
    except Exception:
        return False
