"""
Shopee 商品监控工具 - Streamlit 主应用
功能：添加商品链接监控、查看价格/销量趋势、每日自动更新
"""

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import time

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from database import (
    init_database, add_product, get_all_products, get_product,
    update_product, delete_product, save_snapshot, get_snapshots,
    get_snapshot_count, get_price_change, get_sales_change
)
from scraper import parse_shopee_url, fetch_product_info
from sync import download_db, upload_db

# ============ 页面配置 ============
st.set_page_config(
    page_title="Shopee 商品监控",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化数据库
init_database()

# 从私有仓库下载最新数据库（如果配置了）
download_db()

# ============ 密码认证 ============

def get_password():
    """从环境变量或 Streamlit Secrets 获取密码"""
    # Streamlit Cloud: st.secrets
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        pass
    # 本地: 环境变量
    return os.environ.get("APP_PASSWORD", "")

def check_login():
    """检查登录状态"""
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    password = get_password()
    if not password:
        # 未设置密码，跳过认证
        st.session_state["authenticated"] = True
        return

    if st.session_state["authenticated"]:
        return

    # 登录表单
    st.markdown("<h2 style='text-align:center;margin-top:80px'>Shopee 商品监控</h2>", unsafe_allow_html=True)
    with st.form("login_form"):
        pwd = st.text_input("请输入访问密码", type="password", placeholder="输入密码后回车")
        if st.form_submit_button("登录", type="primary", use_container_width=True):
            if pwd == password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("密码错误")
    st.stop()

check_login()

# ============ 自定义样式 ============
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        color: #EE4D2D;
    }
    .product-card {
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
        margin-bottom: 0.5rem;
    }
    .price-up { color: #FF4D4F; font-weight: bold; }
    .price-down { color: #52C41A; font-weight: bold; }
    .price-flat { color: #8C8C8C; }
    .metric-label { font-size: 0.8rem; color: #8C8C8C; }
    .metric-value { font-size: 1.4rem; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ============ 辅助函数 ============

def format_price(price, region="my"):
    """格式化价格显示"""
    if price is None:
        return "N/A"
    currency_map = {
        "my": "RM", "sg": "S$", "th": "฿", "ph": "₱",
        "id": "Rp", "vn": "₫", "tw": "NT$", "br": "R$"
    }
    symbol = currency_map.get(region, "$")
    return f"{symbol} {price:,.2f}"


def format_number(n):
    """格式化大数字"""
    if n is None:
        return "N/A"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"


def create_price_chart(snapshots, title="价格趋势"):
    """创建价格趋势图"""
    if not snapshots:
        return None

    df = pd.DataFrame(snapshots)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.sort_values("snapshot_date")

    fig = go.Figure()

    # 当前价格线
    if "price" in df.columns and df["price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["snapshot_date"], y=df["price"],
            mode="lines+markers",
            name="当前价格",
            line=dict(color="#EE4D2D", width=2),
            marker=dict(size=6),
        ))

    # 原价线
    if "original_price" in df.columns and df["original_price"].notna().any():
        fig.add_trace(go.Scatter(
            x=df["snapshot_date"], y=df["original_price"],
            mode="lines",
            name="原价",
            line=dict(color="#CCCCCC", width=1, dash="dash"),
        ))

    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="价格",
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )

    return fig


def create_sales_chart(snapshots, title="销量趋势"):
    """创建销量趋势图"""
    if not snapshots:
        return None

    df = pd.DataFrame(snapshots)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.sort_values("snapshot_date")

    if "sold_count" not in df.columns or df["sold_count"].isna().all():
        return None

    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=df["snapshot_date"], y=df["sold_count"],
        name="销量",
        marker_color="#EE4D2D",
    ))

    fig.update_layout(
        title=title,
        xaxis_title="日期",
        yaxis_title="销量",
        height=300,
        margin=dict(l=20, r=20, t=40, b=20),
    )

    return fig


def create_combined_chart(snapshots, title="综合趋势"):
    """创建价格+销量双轴图"""
    if not snapshots:
        return None

    df = pd.DataFrame(snapshots)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    df = df.sort_values("snapshot_date")

    has_price = "price" in df.columns and df["price"].notna().any()
    has_sold = "sold_count" in df.columns and df["sold_count"].notna().any()

    if not has_price and not has_sold:
        return None

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if has_price:
        fig.add_trace(
            go.Scatter(
                x=df["snapshot_date"], y=df["price"],
                mode="lines+markers",
                name="价格",
                line=dict(color="#EE4D2D", width=2),
                marker=dict(size=5),
            ),
            secondary_y=False,
        )

    if has_sold:
        fig.add_trace(
            go.Bar(
                x=df["snapshot_date"], y=df["sold_count"],
                name="销量",
                marker_color="#FF9800",
                opacity=0.6,
            ),
            secondary_y=True,
        )

    fig.update_layout(
        title=title,
        hovermode="x unified",
        height=350,
        margin=dict(l=20, r=20, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="价格", secondary_y=False)
    fig.update_yaxes(title_text="销量", secondary_y=True)

    return fig


# ============ 页面导航 ============

def page_add_product():
    """添加商品页面"""
    st.header("➕ 添加监控商品")

    # 处理确认添加（独立于表单，防止页面刷新丢失数据）
    if st.session_state.get("pending_add"):
        pending = st.session_state["pending_add"]
        st.success(f"✅ 识别到站点: {pending['domain']} | 商品ID: {pending['item_id']}")

        info = pending["info"]
        parsed = pending["parsed"]

        if not info["success"]:
            st.warning(f"⚠️ 抓取未成功，但可以先添加监控，稍后通过「手动录入」补充数据。")
            st.caption(f"错误详情: {info.get('error', '未知')}")
            info["title"] = f"待获取商品 ({parsed['item_id']})"

        # 展示已有信息
        col1, col2, col3 = st.columns([1, 2, 1])
        with col1:
            if info.get("image_url"):
                st.image(info["image_url"], width=200)
            else:
                st.markdown("📷 暂无图片")
        with col2:
            st.markdown(f"### {info.get('title') or '未知商品'}")
            st.markdown(f"**站点:** {parsed['domain']} | 商品ID: {parsed['item_id']}")
            price_col1, price_col2 = st.columns(2)
            with price_col1:
                st.metric("当前价格", format_price(info.get("price"), parsed["region"]))
            with price_col2:
                if info.get("original_price"):
                    st.metric("原价", format_price(info["original_price"], parsed["region"]))
        with col3:
            st.metric("📦 库存", format_number(info.get("stock")))
            st.metric("📈 历史销量", format_number(info.get("historical_sold")))
            if info.get("rating_star"):
                st.metric("⭐ 评分", f"{info['rating_star']:.1f} ({format_number(info.get('rating_count'))}评价)")

        # 确认添加按钮
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("✅ 确认添加监控", type="primary", use_container_width=True):
                product_id = add_product(
                    url=pending["url"],
                    item_id=parsed["item_id"],
                    shop_id=parsed["shop_id"],
                    region=parsed["region"],
                    title=info["title"],
                    image_url=info.get("image_url"),
                    price=info.get("price"),
                    original_price=info.get("original_price"),
                    stock=info.get("stock"),
                    sold=info.get("historical_sold"),
                    rating_star=info.get("rating_star"),
                    rating_count=info.get("rating_count"),
                )
                save_snapshot(
                    product_id=product_id,
                    snapshot_date=date.today(),
                    price=info.get("price"),
                    original_price=info.get("original_price"),
                    stock=info.get("stock"),
                    sold_count=info.get("historical_sold"),
                    rating_star=info.get("rating_star"),
                    rating_count=info.get("rating_count"),
                    title=info["title"],
                )
                del st.session_state["pending_add"]
                st.success("✅ 商品已添加到监控列表！")
                upload_db()
                st.balloons()
                time.sleep(1)
                st.rerun()
        with col_btn2:
            if st.button("❌ 取消", use_container_width=True):
                del st.session_state["pending_add"]
                st.rerun()
        return

    # 输入表单
    with st.form("add_product_form", clear_on_submit=True):
        url = st.text_input(
            "Shopee 商品链接",
            placeholder="https://shopee.com.my/product/123456/78901234/",
            help="支持所有 Shopee 站点（马来西亚、新加坡、泰国、菲律宾、印尼、越南、中国台湾、巴西）"
        )

        submitted = st.form_submit_button("🔍 抓取商品信息", type="primary", use_container_width=True)

        if submitted and url:
            try:
                with st.spinner("正在解析商品链接..."):
                    parsed = parse_shopee_url(url)

                with st.spinner("正在从 Shopee 获取商品数据..."):
                    info = fetch_product_info(parsed["item_id"], parsed["shop_id"], parsed["region"])

                # 存入 session state，等用户确认
                st.session_state["pending_add"] = {
                    "url": url,
                    "parsed": parsed,
                    "info": info,
                    "domain": parsed["domain"],
                    "item_id": parsed["item_id"],
                }
                st.rerun()

            except ValueError as e:
                st.error(f"❌ 链接解析失败: {e}")
            except Exception as e:
                st.error(f"❌ 发生未知错误: {e}")


def page_dashboard():
    """监控大盘页面"""
    st.header("📊 监控大盘")

    products = get_all_products()

    if not products:
        st.info("👋 还没有监控任何商品，快去「添加商品」页面添加吧！")
        return

    # 顶部统计卡片
    total = len(products)
    today_new = sum(1 for p in products if p.get("last_check_at"))
    with_errors = sum(1 for p in products if p.get("check_error"))

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📦 监控中商品", total)
    with col2:
        st.metric("🔄 已更新", today_new)
    with col3:
        st.metric("⚠️ 异常", with_errors, delta=None if with_errors == 0 else f"-{with_errors}")

    st.markdown("---")

    # 商品列表
    st.subheader("📋 监控列表")

    for product in products:
        with st.container():
            cols = st.columns([1, 3, 1.5, 1.5, 1.2, 1.3])

            with cols[0]:
                if product.get("image_url"):
                    st.image(product["image_url"], width=80)
                else:
                    st.markdown("📷")

            with cols[1]:
                title = product.get("title") or "未知商品"
                st.markdown(f"**{title[:50]}{'...' if len(title) > 50 else ''}**")
                st.caption(f"ID: {product['item_id']} | {product['region'].upper()}")

            with cols[2]:
                price = product.get("current_price")
                if price is not None:
                    st.metric("价格", format_price(price, product["region"]))
                else:
                    st.markdown("*N/A*")

            with cols[3]:
                sold = product.get("current_sold")
                st.metric("销量", format_number(sold) if sold is not None else "N/A")

            with cols[4]:
                snap_count = get_snapshot_count(product["id"])
                last_check = product.get("last_check_at")
                st.metric("快照", f"{snap_count}天")
                if last_check:
                    st.caption(f"更新: {last_check[:10]}")

            with cols[5]:
                if st.button("📊 详情", key=f"detail_{product['id']}"):
                    st.session_state["selected_product"] = product["id"]
                    st.session_state["page"] = "商品详情"
                    st.rerun()
                if st.button("🔄 刷新", key=f"refresh_{product['id']}"):
                    with st.spinner("更新中..."):
                        refresh_product(product)
                    st.rerun()
                if st.button("✏️ 手动", key=f"manual_{product['id']}"):
                    st.session_state["manual_product"] = product["id"]
                    st.session_state["page"] = "手动录入"
                    st.rerun()

            # 错误提示
            if product.get("check_error"):
                st.warning(f"⚠️ 上次更新失败: {product['check_error']}")

        st.markdown("---")


def page_product_detail(product_id: int):
    """商品详情页面"""
    product = get_product(product_id)
    if not product:
        st.error("商品不存在")
        return

    # 返回按钮
    if st.button("⬅️ 返回大盘"):
        st.session_state["page"] = "监控大盘"
        st.rerun()

    st.header(f"📊 {product.get('title', '商品详情')}")

    # 产品信息卡片
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if product.get("image_url"):
            st.image(product["image_url"], width=150)

    with col2:
        st.metric("💰 当前价格", format_price(product.get("current_price"), product["region"]))
        if product.get("original_price"):
            st.caption(f"原价: {format_price(product['original_price'], product['region'])}")

    with col3:
        st.metric("📦 库存", format_number(product.get("current_stock")))

    with col4:
        st.metric("📈 历史销量", format_number(product.get("current_sold")))

    with col5:
        if product.get("rating_star"):
            st.metric("⭐ 评分", f"{product['rating_star']:.1f}")
            st.caption(f"{format_number(product.get('rating_count'))} 评价")

    # 链接
    st.caption(f"🔗 [在 Shopee 查看]({product['url']})")
    st.caption(f"站点: {product['region'].upper()} | 上次更新: {product.get('last_check_at', 'N/A')}")

    st.markdown("---")

    # 时间范围选择
    col1, col2 = st.columns([1, 3])
    with col1:
        days = st.selectbox("时间范围", [7, 14, 30, 60, 90], index=2)

    # 获取快照数据
    snapshots = get_snapshots(product_id, days=days)

    if not snapshots:
        st.info("暂无历史数据，数据将在每日自动更新后积累。点击「刷新」按钮立即获取一次。")
        if st.button("🔄 立即刷新数据", type="primary"):
            refresh_product(product)
            st.rerun()
        return

    # 综合趋势图（价格+销量）
    st.subheader("📈 价格 & 销量综合趋势")
    combined_chart = create_combined_chart(snapshots)
    if combined_chart:
        st.plotly_chart(combined_chart, use_container_width=True)

    # 价格趋势
    col1, col2 = st.columns(2)
    with col1:
        price_chart = create_price_chart(snapshots)
        if price_chart:
            st.plotly_chart(price_chart, use_container_width=True)

    with col2:
        sales_chart = create_sales_chart(snapshots)
        if sales_chart:
            st.plotly_chart(sales_chart, use_container_width=True)

    # 数据表格
    st.subheader("📋 历史数据明细")
    df = pd.DataFrame(snapshots)
    df = df.rename(columns={
        "snapshot_date": "日期",
        "price": "价格",
        "original_price": "原价",
        "stock": "库存",
        "sold_count": "销量",
        "rating_star": "评分",
        "rating_count": "评价数",
    })

    # 计算日变化
    if len(df) >= 2 and "价格" in df.columns:
        df["价格变化"] = df["价格"].diff()
        df["销量变化"] = df["销量"].diff()

    display_cols = ["日期", "价格", "原价", "库存", "销量", "评分", "评价数"]
    display_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(
        df[display_cols].sort_values("日期", ascending=False),
        use_container_width=True,
        hide_index=True,
    )

    # 价格统计
    if len(snapshots) >= 2 and snapshots[0].get("price") and snapshots[-1].get("price"):
        st.markdown("---")
        st.subheader("📊 统计数据")

        prices = [s["price"] for s in snapshots if s.get("price")]
        if prices:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("最高价", format_price(max(prices), product["region"]))
            with col2:
                st.metric("最低价", format_price(min(prices), product["region"]))
            with col3:
                st.metric("平均价", format_price(sum(prices) / len(prices), product["region"]))
            with col4:
                change = prices[-1] - prices[0]
                st.metric(
                    "期间变化",
                    f"{'+' if change > 0 else ''}{change:.2f}",
                    delta=f"{change/prices[0]*100:+.1f}%"
                )

    # 删除按钮
    st.markdown("---")
    if st.button("🗑️ 停止监控此商品", type="secondary"):
        delete_product(product_id)
        st.success("已停止监控")
        st.session_state["page"] = "监控大盘"
        st.rerun()


def refresh_product(product: dict):
    """刷新单个商品数据"""
    try:
        info = fetch_product_info(product["item_id"], product["shop_id"], product["region"])

        if info["success"]:
            # 更新商品信息
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

            # 保存快照
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
        else:
            update_product(
                product["id"],
                last_check_at=datetime.now().isoformat(),
                check_error=info.get("error", "未知错误"),
            )
    except Exception as e:
        update_product(
            product["id"],
            last_check_at=datetime.now().isoformat(),
            check_error=str(e),
        )


def page_batch_refresh():
    """批量刷新页面"""
    st.header("🔄 批量刷新")

    products = get_all_products()
    if not products:
        st.info("没有需要刷新的商品")
        return

    if st.button("🔄 刷新全部商品", type="primary"):
        progress = st.progress(0)
        status_text = st.empty()

        for i, product in enumerate(products):
            status_text.text(f"正在更新: {product.get('title', '未知')}...")
            refresh_product(product)
            progress.progress((i + 1) / len(products))
            import time
            time.sleep(1)  # 避免请求过快

        progress.empty()
        status_text.empty()
        st.success("✅ 全部刷新完成！")
        upload_db()
        st.balloons()


def page_manual_input():
    """手动录入数据页面"""
    product_id = st.session_state.get("manual_product")
    if not product_id:
        st.session_state["page"] = "监控大盘"
        st.rerun()
        return

    product = get_product(product_id)
    if not product:
        st.error("商品不存在")
        st.session_state["page"] = "监控大盘"
        st.rerun()
        return

    if st.button("⬅️ 返回大盘"):
        st.session_state["page"] = "监控大盘"
        st.rerun()

    st.header(f"✏️ 手动录入 - {product.get('title', '未知商品')}")
    st.info("当自动抓取失败时，可以在此手动输入当前的价格和销量数据。")

    with st.form("manual_input_form"):
        col1, col2 = st.columns(2)

        with col1:
            price = st.number_input(
                "当前价格",
                min_value=0.0,
                value=float(product.get("current_price") or 0),
                step=0.01,
                help=f"输入当前售价（单位请与 Shopee 页面一致）"
            )
            stock = st.number_input(
                "库存数量",
                min_value=0,
                value=int(product.get("current_stock") or 0),
                step=1,
            )

        with col2:
            sold = st.number_input(
                "历史销量",
                min_value=0,
                value=int(product.get("current_sold") or 0),
                step=1,
                help="商品页面显示的累计销量"
            )
            rating = st.number_input(
                "评分",
                min_value=0.0,
                max_value=5.0,
                value=float(product.get("rating_star") or 0),
                step=0.1,
            )

        submitted = st.form_submit_button("💾 保存数据", type="primary", use_container_width=True)

        if submitted:
            update_product(
                product_id,
                current_price=price if price > 0 else None,
                current_stock=stock if stock >= 0 else None,
                current_sold=sold if sold >= 0 else None,
                rating_star=rating if rating > 0 else None,
                last_check_at=datetime.now().isoformat(),
                check_error=None,
            )
            save_snapshot(
                product_id=product_id,
                snapshot_date=date.today(),
                price=price if price > 0 else None,
                stock=stock if stock >= 0 else None,
                sold_count=sold if sold >= 0 else None,
                rating_star=rating if rating > 0 else None,
            )
            st.success("✅ 数据已保存！")
            upload_db()
            st.session_state["page"] = "监控大盘"
            time.sleep(0.5)
            st.rerun()


def page_settings():
    """设置页面"""
    st.header("⚙️ 设置与说明")

    st.subheader("📖 使用说明")

    st.markdown("""
    ### 如何使用？

    1. **添加商品**: 在「添加商品」页面输入 Shopee 商品链接
    2. **查看数据**: 在「监控大盘」查看所有监控商品
    3. **详情分析**: 点击「详情」查看单个商品的价格/销量趋势
    4. **自动更新**: 配置 GitHub Actions 可实现每日自动抓取

    ### 支持的站点

    | 站点 | 域名 | 货币 |
    |------|------|------|
    | 马来西亚 | shopee.com.my | RM |
    | 新加坡 | shopee.sg | S$ |
    | 泰国 | shopee.co.th | ฿ |
    | 菲律宾 | shopee.ph | ₱ |
    | 印尼 | shopee.co.id | Rp |
    | 越南 | shopee.vn | ₫ |
    | 中国台湾 | shopee.tw | NT$ |
    | 巴西 | shopee.com.br | R$ |

    ### 数据更新频率

    - **手动**: 点击页面上「刷新」按钮
    - **自动**: 通过 GitHub Actions 每日定时运行
    - 建议频率: 每天 1-2 次，高频请求可能触发反爬机制

    ### 关于数据准确性

    - 价格数据来源于 Shopee 公开 API
    - 销量数据为 Shopee 展示的「历史销量」
    - 每日销量来自两次快照的差值计算
    """)

    st.markdown("---")
    st.subheader("🗄️ 数据管理")

    col1, col2 = st.columns(2)
    with col1:
        product_count = len(get_all_products())
        st.metric("监控商品数", product_count)

    with col2:
        import sqlite3
        db_path = Path(__file__).resolve().parent / "data" / "shopee_monitor.db"
        if db_path.exists():
            size_mb = db_path.stat().st_size / 1024 / 1024
            st.metric("数据库大小", f"{size_mb:.2f} MB")
        else:
            st.metric("数据库大小", "0 MB")


# ============ 主入口 ============

def main():
    """主程序入口"""

    # 侧边栏导航
    with st.sidebar:
        st.markdown('<p class="main-header">🛒 Shopee 监控</p>', unsafe_allow_html=True)
        st.markdown("---")

        # 初始化 session state
        if "page" not in st.session_state:
            st.session_state["page"] = "监控大盘"

        # 导航按钮
        nav_options = ["监控大盘", "添加商品", "批量刷新", "设置"]
        selected = st.radio(
            "导航",
            nav_options,
            index=nav_options.index(st.session_state["page"]) if st.session_state["page"] in nav_options else 0,
            label_visibility="collapsed",
        )

        if selected != st.session_state.get("page"):
            st.session_state["page"] = selected
            st.rerun()

        st.markdown("---")
        st.caption(f"📅 今天: {date.today()}")
        st.caption("Made with ❤️ by WorkBuddy")

    # 页面路由
    page = st.session_state.get("page", "监控大盘")

    if page == "监控大盘":
        page_dashboard()
    elif page == "添加商品":
        page_add_product()
    elif page == "批量刷新":
        page_batch_refresh()
    elif page == "设置":
        page_settings()
    elif page == "商品详情":
        product_id = st.session_state.get("selected_product")
        if product_id:
            page_product_detail(product_id)
        else:
            st.session_state["page"] = "监控大盘"
            st.rerun()
    elif page == "手动录入":
        page_manual_input()


if __name__ == "__main__":
    main()
