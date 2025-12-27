import sys
import configparser
import webbrowser
import json
from rauth import OAuth1Service

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
BASE_URL = config["DEFAULT"]["SANDBOX_BASE_URL"]

def oauth_login():
    """执行 OAuth 1.0a 认证流程"""
    print("正在连接 E*TRADE Sandbox 进行认证...")
    
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
    # 注意：Sandbox 有时需要特定的回调设置，这里设置为 'oob' (Out of Band)
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
    return session

def list_accounts(session):
    """获取并打印账户列表"""
    url = f"{BASE_URL}/v1/accounts/list.json"
    
    print(f"\n正在获取账户列表: {url}")
    response = session.get(url)

    if response.status_code == 200:
        data = response.json()
        if "AccountListResponse" in data and "Accounts" in data["AccountListResponse"]:
            accounts = data["AccountListResponse"]["Accounts"]["Account"]
            print(f"\n{'='*40}")
            print(f"{'账户ID':<20} | {'账户描述':<15} | {'类型'}")
            print(f"{'-'*40}")
            
            # 如果只有一个账户，API 有时返回字典而不是列表，做个兼容处理
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

def main():
    # 解析命令行参数
    if len(sys.argv) >= 3 and sys.argv[1] == "account" and sys.argv[2] == "list":
        # 1. 登录
        session = oauth_login()
        # 2. 获取列表
        list_accounts(session)
    else:
        print("用法: python main.py account list")

if __name__ == "__main__":
    main()