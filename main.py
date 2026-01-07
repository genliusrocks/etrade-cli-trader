import sys
import configparser
import webbrowser
import json
from rauth import OAuth1Service, OAuth1Session

# 读取配置文件
config = configparser.ConfigParser()
config.read('config.ini')

# 检查配置是否存在
if config["DEFAULT"]["CONSUMER_KEY"].startswith("PLEASE_ENTER"):
    print("错误: 请先在 config.ini 中填入您的 Sandbox Key 和 Secret。")
    sys.exit(1)

# 配置 Sandbox 环境参数
CONSUMER_KEY = config["DEFAULT"]["CONSUMER_KEY"]
CONSUMER_SECRET = config["DEFAULT"]["CONSUMER_SECRET"]
#BASE_URL = config["DEFAULT"]["SANDBOX_BASE_URL"]
BASE_URL = config["DEFAULT"]["PROD_BASE_URL"]

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
    
    # 1. 尝试从 config.ini 读取现有的 Access Token
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

    # 2. 如果本地没有令牌，则执行完整的登录流程
    return oauth_login()

def oauth_login():
    """执行 OAuth 1.0a 认证流程"""
    print("\n正在连接 E*TRADE Sandbox 进行认证...")
    
    etrade = OAuth1Service(
        name="etrade",
        consumer_key=CONSUMER_KEY,
        consumer_secret=CONSUMER_SECRET,
        request_token_url=f"{BASE_URL}/oauth/request_token",
        access_token_url=f"{BASE_URL}/oauth/access_token",
        authorize_url="https://us.etrade.com/e/t/etws/authorize?key={}&token={}",
        base_url=BASE_URL
    )

    # 第一步：获取 Request Token
    request_token, request_token_secret = etrade.get_request_token(
        params={"oauth_callback": "oob", "format": "json"}
    )

    # 第二步：生成授权链接并打开浏览器
    authorize_url = etrade.authorize_url.format(etrade.consumer_key, request_token)
    print(f"\n请在浏览器中打开以下链接进行授权 (Sandbox):\n{authorize_url}")
    webbrowser.open(authorize_url)

    # 第三步：用户输入验证码
    verifier = input("\n请输入浏览器页面显示的验证码 (Verifier Code): ")

    # 第四步：获取 Access Token (正式会话)
    session = etrade.get_auth_session(
        request_token,
        request_token_secret,
        params={"oauth_verifier": verifier}
    )
    
    print("认证成功！")
    
    # 保存 Token 供下次使用
    save_tokens(session.access_token, session.access_token_secret)
    
    return session

def list_accounts(session):
    """获取并打印账户列表"""
    url = f"{BASE_URL}/v1/accounts/list.json"
    
    response = session.get(url)

    # === 修改点：自动处理过期 Token ===
    if response.status_code == 401:
        print("\n[提示] 令牌已过期，正在重新登录...")
        clear_tokens()
        session = oauth_login() # 重新登录获取新 Session
        response = session.get(url) # 重试请求

    if response.status_code == 200:
        data = response.json()
        if "AccountListResponse" in data and "Accounts" in data["AccountListResponse"]:
            accounts = data["AccountListResponse"]["Accounts"]["Account"]
            print(f"\n{'='*40}")
            print(f"{'账户ID':<20} | {'账户描述':<15} | {'类型'}")
            print(f"{'-'*40}")
            
            if isinstance(accounts, dict):
                accounts = [accounts]

            for acc in accounts:
                acc_id = acc.get('accountId', 'N/A')
                acc_desc = acc.get('accountDesc', 'N/A')
                acc_type = acc.get('accountType', 'N/A')
                print(f"{acc_id:<20} | {acc_desc:<15} | {acc_type}")
            print(f"{'='*40}\n")
        else:
            print("未找到账户信息或响应格式意外。")
            print(json.dumps(data, indent=4))
    elif response.status_code == 204:
        print("查询成功，但名下没有账户。")
    else:
        print(f"请求失败 (状态码 {response.status_code}):")
        print(response.text)

def get_account_balance(session, account):
    """获取单个账户的余额详情"""
    account_id_key = account.get("accountIdKey")
    inst_type = account.get("institutionType", "BROKERAGE")
    
    # 构造余额查询 API URL
    url = f"{BASE_URL}/v1/accounts/{account_id_key}/balance.json"
    
    # E*TRADE API 要求 Header 包含 consumerkey
    params = {
        "instType": inst_type, 
        "realTimeNAV": "true"
    }
    headers = {"consumerkey": CONSUMER_KEY}

    response = session.get(url, params=params, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        if "BalanceResponse" in data:
            return data["BalanceResponse"]
    return None

def cmd_account_balance(session):
    """处理 'account balance' 命令：获取所有账户列表并查询每个账户的余额"""
    
    # 1. 获取账户列表 (我们需要其中的 accountIdKey)
    url = f"{BASE_URL}/v1/accounts/list.json"
    response = session.get(url)

    # === 修改点：自动处理过期 Token ===
    if response.status_code == 401:
        print("\n[提示] 令牌已过期，正在重新登录...")
        clear_tokens()
        session = oauth_login() # 重新登录
        response = session.get(url) # 重试请求

    if response.status_code != 200:
        print(f"无法获取账户列表。状态码: {response.status_code}")
        if response.status_code != 401:
            print(response.text)
        return

    data = response.json()
    if "AccountListResponse" not in data or "Accounts" not in data["AccountListResponse"]:
        print("名下没有账户。")
        return

    accounts = data["AccountListResponse"]["Accounts"]["Account"]
    if isinstance(accounts, dict):
        accounts = [accounts]

    # 2. 打印表头
    print(f"\n{'='*85}")
    print(f"{'账户描述':<20} | {'净资产 (Net Value)':<18} | {'现金购买力':<15} | {'保证金购买力'}")
    print(f"{'-'*85}")

    # 3. 遍历账户查询余额
    for acc in accounts:
        desc = acc.get('accountDesc', 'N/A')
        
        # 使用可能已经更新的 session
        balance_data = get_account_balance(session, acc)
        
        net_value = 0.0
        cash_power = 0.0
        margin_power = 0.0

        if balance_data:
            computed = balance_data.get("Computed", {})
            real_time = computed.get("RealTimeValues", {})
            
            # 获取净值 (优先取实时值)
            if "totalAccountValue" in real_time:
                net_value = real_time["totalAccountValue"]
            elif "totalAccountValue" in computed:
                net_value = computed["totalAccountValue"]
            
            # 获取购买力
            cash_power = computed.get("cashBuyingPower", 0.0)
            margin_power = computed.get("marginBuyingPower", 0.0)

        print(f"{desc:<20} | ${net_value:<17,.2f} | ${cash_power:<14,.2f} | ${margin_power:,.2f}")

    print(f"{'='*85}\n")

def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "account":
        session = get_session()
        command = sys.argv[2]
        
        if command == "list":
            list_accounts(session)
        elif command == "balance":
            cmd_account_balance(session)
        else:
             print(f"未知子命令: {command}")
             print("用法: python main.py account [list|balance]")
    else:
        print("用法: python main.py account [list|balance]")

if __name__ == "__main__":
    main()
