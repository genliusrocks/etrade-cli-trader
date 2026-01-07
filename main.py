import sys
import configparser
import webbrowser
import json
from rauth import OAuth1Service, OAuth1Session

# --- 颜色代码 (用于美化输出) ---
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

# 读取配置文件
config = configparser.ConfigParser()
config.read('config.ini')

# 检查配置是否存在
if config["DEFAULT"]["CONSUMER_KEY"].startswith("PLEASE_ENTER"):
    print("错误: 请先在 config.ini 中填入您的 Sandbox Key 和 Secret。")
    sys.exit(1)

# 配置环境参数
CONSUMER_KEY = config["DEFAULT"]["CONSUMER_KEY"]
CONSUMER_SECRET = config["DEFAULT"]["CONSUMER_SECRET"]
# 自动选择 URL：优先读取 PROD，如果被注释则回退到 SANDBOX (根据您之前的修改，这里应该是 PROD)
BASE_URL = config["DEFAULT"].get("PROD_BASE_URL", "https://api.etrade.com")

def save_tokens(access_token, access_token_secret):
    """将获取到的 Token 保存到 config.ini"""
    config["DEFAULT"]["ACCESS_TOKEN"] = access_token
    config["DEFAULT"]["ACCESS_TOKEN_SECRET"] = access_token_secret
    with open('config.ini', 'w') as configfile:
        config.write(configfile)
    print(">>> 令牌已保存到 config.ini (有效期至今日美东时间午夜)")

def clear_tokens():
    """清理 config.ini 中的过期 Token"""
    if "ACCESS_TOKEN" in config["DEFAULT"]:
        del config["DEFAULT"]["ACCESS_TOKEN"]
    if "ACCESS_TOKEN_SECRET" in config["DEFAULT"]:
        del config["DEFAULT"]["ACCESS_TOKEN_SECRET"]
    with open('config.ini', 'w') as configfile:
        config.write(configfile)

def get_session():
    """获取会话：优先尝试读取本地 Token，如果没有则进行 OAuth 登录"""
    access_token = config["DEFAULT"].get("ACCESS_TOKEN")
    access_secret = config["DEFAULT"].get("ACCESS_TOKEN_SECRET")

    if access_token and access_secret:
        session = OAuth1Session(
            consumer_key=CONSUMER_KEY,
            consumer_secret=CONSUMER_SECRET,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        return session
    return oauth_login()

def oauth_login():
    """执行 OAuth 1.0a 认证流程"""
    print("\n正在连接 E*TRADE 进行认证...")
    
    etrade = OAuth1Service(
        name="etrade",
        consumer_key=CONSUMER_KEY,
        consumer_secret=CONSUMER_SECRET,
        request_token_url=f"{BASE_URL}/oauth/request_token",
        access_token_url=f"{BASE_URL}/oauth/access_token",
        authorize_url="https://us.etrade.com/e/t/etws/authorize?key={}&token={}",
        base_url=BASE_URL
    )

    request_token, request_token_secret = etrade.get_request_token(
        params={"oauth_callback": "oob", "format": "json"}
    )

    authorize_url = etrade.authorize_url.format(etrade.consumer_key, request_token)
    print(f"\n请在浏览器中打开以下链接进行授权:\n{authorize_url}")
    webbrowser.open(authorize_url)

    verifier = input("\n请输入浏览器页面显示的验证码 (Verifier Code): ")

    session = etrade.get_auth_session(
        request_token,
        request_token_secret,
        params={"oauth_verifier": verifier}
    )
    
    print("认证成功！")
    save_tokens(session.access_token, session.access_token_secret)
    return session

def retry_on_401(func):
    """装饰器：处理 401 过期重试"""
    def wrapper(session, *args, **kwargs):
        response = func(session, *args, **kwargs)
        if response.status_code == 401:
            print(f"\n{Colors.RED}[提示] 令牌已过期，正在重新登录...{Colors.RESET}")
            clear_tokens()
            new_session = oauth_login()
            # 更新引用，防止后续调用使用旧 session
            # 注意：这里的 session 是传值，无法直接修改外部变量，但在当前函数栈内有效
            return func(new_session, *args, **kwargs)
        return response
    return wrapper

@retry_on_401
def fetch_account_list(session):
    return session.get(f"{BASE_URL}/v1/accounts/list.json")

def list_accounts(session):
    """获取并打印账户列表"""
    response = fetch_account_list(session)

    if response.status_code == 200:
        data = response.json()
        if "AccountListResponse" in data and "Accounts" in data["AccountListResponse"]:
            accounts = data["AccountListResponse"]["Accounts"]["Account"]
            print(f"\n{'='*40}")
            print(f"{'账户ID':<20} | {'账户描述':<15} | {'类型'}")
            print(f"{'-'*40}")
            
            if isinstance(accounts, dict): accounts = [accounts]

            for acc in accounts:
                print(f"{acc.get('accountId'):<20} | {acc.get('accountDesc'):<15} | {acc.get('accountType')}")
            print(f"{'='*40}\n")
        else:
            print("未找到账户。")
    else:
        print(f"请求失败: {response.status_code} - {response.text}")

def get_portfolio_data(session, account_key):
    """获取单个账户的持仓数据"""
    url = f"{BASE_URL}/v1/accounts/{account_key}/portfolio.json"
    response = session.get(url)
    
    if response.status_code == 200:
        data = response.json()
        if "PortfolioResponse" in data and "AccountPortfolio" in data["PortfolioResponse"]:
            return data["PortfolioResponse"]["AccountPortfolio"]
    return None

def cmd_account_positions(session):
    """处理 'account positions' 命令"""
    
    # 1. 获取账户列表
    response = fetch_account_list(session)
    if response.status_code != 200:
        print(f"无法获取账户列表。Code: {response.status_code}")
        return

    data = response.json()
    if "AccountListResponse" not in data or "Accounts" not in data["AccountListResponse"]:
        print("名下没有账户。")
        return

    accounts = data["AccountListResponse"]["Accounts"]["Account"]
    if isinstance(accounts, dict): accounts = [accounts]

    # 2. 遍历每个账户获取持仓
    for acc in accounts:
        acc_desc = acc.get('accountDesc', 'Unknown Account')
        acc_id = acc.get('accountId')
        acc_key = acc.get('accountIdKey')

        print(f"\n{Colors.BOLD}账户: {acc_desc} ({acc_id}){Colors.RESET}")
        
        # 表头
        print(f"{'-'*135}")
        print(f"{'Symbol':<20} | {'Name':<25} | {'Qty':>8} | {'Paid ($)':>10} | {'Price ($)':>10} | {'Mkt Value ($)':>14} | {'P&L ($)':>12} | {'P&L %':>10}")
        print(f"{'-'*135}")

        portfolios = get_portfolio_data(session, acc_key)
        
        if not portfolios:
            print("  (无持仓或无法获取数据)")
            continue

        # AccountPortfolio 可能是列表（如果有多页或其他情况），通常只有一项
        for p_section in portfolios:
            positions = p_section.get("Position", [])
            if not positions:
                continue
                
            for pos in positions:
                # 提取数据
                product = pos.get("Product", {})
                symbol = product.get("symbol", "N/A")
                description = pos.get("symbolDescription", "N/A")[:25] # 截断太长的名字
                
                qty = pos.get("quantity", 0)
                price_paid = pos.get("pricePaid", 0) # 平均成本
                
                # 获取当前价格 (Quick 字段通常包含实时/延时数据)
                current_price = pos.get("Quick", {}).get("lastTrade", 0)
                market_value = pos.get("marketValue", 0)
                total_gain = pos.get("totalGain", 0)
                total_gain_pct = pos.get("totalGainPct", 0)

                # 设置颜色：盈利绿色，亏损红色
                pl_color = Colors.GREEN if total_gain >= 0 else Colors.RED
                
                # 格式化输出行
                print(f"{symbol:<20} | {description:<25} | {qty:>8.2f} | {price_paid:>10.2f} | {current_price:>10.2f} | {market_value:>14.2f} | {pl_color}{total_gain:>12.2f}{Colors.RESET} | {pl_color}{total_gain_pct:>9.2f}%{Colors.RESET}")

        print(f"{'-'*135}")

def cmd_account_balance(session):
    """处理 'account balance' 命令"""
    response = fetch_account_list(session)
    if response.status_code != 200:
        return

    data = response.json()
    accounts = data["AccountListResponse"]["Accounts"]["Account"]
    if isinstance(accounts, dict): accounts = [accounts]

    print(f"\n{'='*85}")
    print(f"{'账户描述':<20} | {'净资产 (Net Value)':<18} | {'现金购买力':<15} | {'保证金购买力'}")
    print(f"{'-'*85}")

    for acc in accounts:
        # 获取余额
        url = f"{BASE_URL}/v1/accounts/{acc['accountIdKey']}/balance.json"
        params = {"instType": acc.get("institutionType", "BROKERAGE"), "realTimeNAV": "true"}
        bal_res = session.get(url, params=params, headers={"consumerkey": CONSUMER_KEY})
        
        net_value = 0.0
        cash_power = 0.0
        margin_power = 0.0

        if bal_res.status_code == 200:
            b_data = bal_res.json().get("BalanceResponse", {})
            computed = b_data.get("Computed", {})
            real_time = computed.get("RealTimeValues", {})
            net_value = real_time.get("totalAccountValue", computed.get("totalAccountValue", 0))
            cash_power = computed.get("cashBuyingPower", 0)
            margin_power = computed.get("marginBuyingPower", 0)

        print(f"{acc.get('accountDesc'):<20} | ${net_value:<17,.2f} | ${cash_power:<14,.2f} | ${margin_power:,.2f}")
    print(f"{'='*85}\n")

def main():
    if len(sys.argv) < 3 or sys.argv[1] != "account":
        print("用法:")
        print("  python main.py account list       - 查看账户列表")
        print("  python main.py account balance    - 查看资金余额")
        print("  python main.py account positions  - 查看当前持仓 (P&L)")
        return

    session = get_session()
    command = sys.argv[2]

    if command == "list":
        list_accounts(session)
    elif command == "balance":
        cmd_account_balance(session)
    elif command == "positions":
        cmd_account_positions(session)
    else:
        print(f"未知命令: {command}")

if __name__ == "__main__":
    main()