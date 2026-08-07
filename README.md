# 🛒 Shopee 商品监控工具

一个基于 Streamlit 的 Shopee 商品价格和销量监控工具，支持多站点，可部署到 GitHub 实现每日自动监控。

## ✨ 功能特性

- 🔗 **多站点支持**: 马来西亚、新加坡、泰国、菲律宾、印尼、越南、中国台湾、巴西
- 💰 **价格监控**: 追踪商品每日价格变化，可视化价格趋势
- 📈 **销量追踪**: 记录历史销量，计算每日销量变化
- 📊 **可视化图表**: 价格/销量趋势图、综合对比图
- ✏️ **手动录入**: 自动抓取失败时可手动输入数据，保证数据连续性
- ⏰ **自动更新**: GitHub Actions 每日定时自动抓取
- 🗄️ **本地存储**: SQLite 数据库，数据安全可控

## 🚀 快速开始

### 1. 克隆项目

```bash
git clone https://github.com/YOUR_USERNAME/shopee-monitor.git
cd shopee-monitor
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装 Playwright 浏览器（用于自动抓取）

```bash
playwright install chromium
```

### 4. 启动应用

```bash
streamlit run app.py
```

浏览器会自动打开 `http://localhost:8501`

### 5. 添加监控商品

在「添加商品」页面输入 Shopee 商品链接，系统会自动抓取商品信息并开始监控。

> **如果自动抓取失败**：Shopee 有较强的反爬保护，如果 Playwright 抓取失败，可以使用「手动录入」功能直接输入价格和销量数据。

## 📋 数据抓取模式

| 模式 | 说明 | 可靠性 |
|------|------|--------|
| Playwright 浏览器 | 无头浏览器渲染页面 + API 拦截 | 中等（受反爬影响） |
| curl_cffi 伪装 | TLS 指纹模拟浏览器 | 低（API 需登录态） |
| 手动录入 ✏️ | 手动输入价格/销量数据 | 100% |

## 📋 支持的 URL 格式

```
# 格式 1: 产品页面
https://shopee.com.my/product/123456/78901234/
https://shopee.sg/Product-Name-i.123456.78901234

# 格式 2: 带查询参数
https://shopee.co.id/product/123/456/?itemid=789&shopid=123
```

## ⚙️ GitHub Actions 自动监控

本项目已配置 GitHub Actions，每天自动运行 2 次（北京时间 8:00 和 20:00）。

### 启用自动监控

1. Fork 或推送本项目到你的 GitHub 仓库
2. 确保仓库 Settings → Actions → General 中开启了 Actions 权限
3. GitHub Actions 会自动按计划运行

也可以手动触发：进入 Actions 页面 → `每日 Shopee 商品监控` → `Run workflow`

### 配置通知 (企业微信 + PushPlus)

GitHub Actions 每次运行完会自动推送抓取报告。

**企业微信（推荐，无 7 天限制）：**

1. 在企业微信群里添加机器人，获取 Webhook 地址
2. 在 GitHub 仓库 Settings → Secrets → Actions 中新建 `WECOM_WEBHOOK`，粘贴完整 Webhook 地址

**PushPlus 微信推送（备用）：**

1. 前往 [pushplus.plus](http://www.pushplus.plus) 获取 Token
2. 同上新建 `PUSHPLUS_TOKEN` Secret

> 两种通知可同时配置，互不干扰。都不配置也不影响抓取功能。

## 📊 数据说明

| 数据项 | 说明 | 来源 |
|--------|------|------|
| 价格 | 商品当前售价 | 自动抓取 / 手动录入 |
| 原价 | 划线价/折扣前价格 | 自动抓取 / 手动录入 |
| 库存 | 当前库存数量 | 自动抓取 / 手动录入 |
| 历史销量 | 累计销售数量 | 自动抓取 / 手动录入 |
| 评分 | 商品评分 (1-5) | 自动抓取 / 手动录入 |

## 🗂️ 项目结构

```
shopee-monitor/
├── app.py                  # Streamlit 主应用
├── scraper.py              # 多策略抓取（Playwright + curl_cffi + HTML）
├── scraper_playwright.py   # Playwright 浏览器渲染抓取
├── database.py             # SQLite 数据库模块
├── scheduler.py            # GitHub Actions 定时任务
├── config.py               # 配置文件
├── requirements.txt        # Python 依赖
├── .github/workflows/
│   └── daily-check.yml     # GitHub Actions 定时任务
└── data/                   # 数据目录 (Git 跟踪)
    └── shopee_monitor.db
```

## ⚠️ 注意事项

1. **反爬机制**: Shopee 有较强的 Cloudflare 反爬保护，Playwright 抓取在某些网络环境下可能被拦截。建议配合住宅代理或 VPS 使用。
2. **手动备用**: 当自动抓取失败时，可以使用「手动录入」功能保证数据连续性
3. **请求频率**: 建议每天不超过 4 次数据抓取，频繁请求可能触发更严格的反爬
4. **仅供学习**: 本工具仅用于个人学习研究，请勿用于商业用途

## 📄 License

MIT License
