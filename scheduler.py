"""
Shopee Monitor 定时任务脚本
供 GitHub Actions 每日调用，自动刷新所有监控商品数据
"""

import sys
import time
import logging
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import (
    init_database, get_all_products, update_product, save_snapshot
)
from scraper import fetch_product_info
from notify import send_scrape_report

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).resolve().parent / "data" / "scheduler.log"),
    ],
)
logger = logging.getLogger(__name__)


def run_daily_check():
    """执行每日检查，刷新所有活跃商品的监控数据"""
    logger.info("=" * 50)
    logger.info(f"开始每日检查 - {date.today()}")

    init_database()
    products = get_all_products(status="active")

    if not products:
        logger.info("没有需要监控的商品")
        return

    logger.info(f"共 {len(products)} 个商品需要更新")

    success_count = 0
    error_count = 0
    error_details = []

    for i, product in enumerate(products):
        product_name = product.get("title") or f"ID:{product['item_id']}"
        logger.info(f"[{i+1}/{len(products)}] 正在获取: {product_name}")

        try:
            info = fetch_product_info(
                product["item_id"], product["shop_id"], product["region"]
            )

            if info["success"]:
                # 更新商品当前信息
                update_product(
                    product["id"],
                    title=info["title"],
                    current_price=info["price"],
                    original_price=info["original_price"],
                    current_stock=info["stock"],
                    current_sold=info["historical_sold"],
                    rating_star=info["rating_star"],
                    rating_count=info["rating_count"],
                    image_url=info["image_url"],
                    last_check_at=datetime.now().isoformat(),
                    check_error=None,
                )

                # 保存今日快照
                save_snapshot(
                    product_id=product["id"],
                    snapshot_date=date.today(),
                    price=info["price"],
                    original_price=info["original_price"],
                    stock=info["stock"],
                    sold_count=info["historical_sold"],
                    rating_star=info["rating_star"],
                    rating_count=info["rating_count"],
                    title=info["title"],
                )

                logger.info(f"  ✅ 成功: 价格={info['price']}, 销量={info['historical_sold']}")
                success_count += 1
            else:
                error_msg = info.get("error", "未知错误")
                update_product(
                    product["id"],
                    last_check_at=datetime.now().isoformat(),
                    check_error=error_msg,
                )
                logger.warning(f"  ⚠️ 失败: {error_msg}")
                error_count += 1
                error_details.append({"product": product_name, "error": error_msg[:100]})

        except Exception as e:
            error_msg = str(e)
            update_product(
                product["id"],
                last_check_at=datetime.now().isoformat(),
                check_error=error_msg,
            )
            logger.error(f"  ❌ 异常: {e}")
            error_count += 1
            error_details.append({"product": product_name, "error": error_msg[:100]})

        # 避免请求过快
        if i < len(products) - 1:
            time.sleep(2)

    logger.info(f"每日检查完成 - 成功: {success_count}, 失败: {error_count}")
    logger.info("=" * 50)

    # 发送通知（企微 + PushPlus 双通道）
    wecom_ok, pushplus_ok = send_scrape_report(
        success_count=success_count,
        error_count=error_count,
        total=len(products),
        errors=error_details if error_details else None,
    )
    logger.info(f"通知发送: 企微={'OK' if wecom_ok else 'SKIP'}, PushPlus={'OK' if pushplus_ok else 'SKIP'}")


if __name__ == "__main__":
    run_daily_check()
