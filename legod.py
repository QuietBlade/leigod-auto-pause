import requests
import json
from datetime import datetime, timedelta
from serverchan_sdk import sc_send
import os

class legod(object):
    def __init__(self, token = ""):
        self.version = "v2.2.5"
        self.pause_url = "https://webapi.leigod.com/api/user/pause"
        self.info_url = "https://webapi.leigod.com/api/user/info"
        self.usage_detail_url = "https://webapi.leigod.com/api/user/time/log"
        self.key = "5C5A639C20665313622F51E93E3F2783"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.96 Safari/537.36 Edg/88.0.705.53",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Connection": "keep-alive",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
            "DNT": "1",
            "Referer": "https://www.leigod.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
        }
        self.stopp = None
        self.token = token
        self.account_info = None
        self.serverchan_sendkey = os.getenv('serverchan_sendkey', "") 
        if self.serverchan_sendkey:
            print("Server酱通知已启用。")
        else:
            print("环境变量 'serverchan_sendkey' 未设置，Server酱通知已禁用。")

        print(
            """雷神加速器自动暂停工具 当前版本：%s"""
            % self.version
        )

    def update_token(self, token: str) -> tuple:
        """
        重置token信息, 初始化也需要用此方法
        """
        self.stopp = None
        self.token = token
        self.account_info = None
        if token:
            return self.get_account_info()
        return False, "Token 为空，无法更新。"


    def get_account_info(self) -> tuple:
        """
        获取账号信息
        Returns
        --------
        :class:`tuple`
            (True,账号信息) or (False,错误信息)
        """
        if self.token == "":
            return False, "token信息无效, 请检查后再试"

        payload = {
            "account_token": self.token,
            "lang": "zh_CN",
            "os_type": 4,
        }
        
        try:
            r = requests.post(self.info_url, data=payload, headers=self.header)
            r.raise_for_status()
            msg = json.loads(r.text)
            if msg["code"] == 0:
                self.account_info = msg["data"]
                self.stopp = self.account_info["pause_status_id"] == 1
                return True, self.account_info
            else:
                self.update_token("")
                return False, msg["msg"]
        except requests.exceptions.RequestException as e:
            self.update_token("")
            return False, f"请求账号信息失败: {e}"
        except json.JSONDecodeError:
            self.update_token("")
            return False, "解析账号信息响应失败。"


    def pause(self) -> tuple:
        """
        暂停加速,调用官网api
        """
        if self.token == "":
            return False, "token信息无效, 请使用update_token方法更新后再试"
        if self.stopp:
            return False, "当前用户已经暂停加速"
            
        payload = {
            "account_token": self.token,
            "lang": "zh_CN",
            "os_type": 4,
        }
        try:
            response = requests.post(self.pause_url, data=payload, headers=self.header)
            response.raise_for_status()
            if response.status_code == 403:
                msg = "未知错误，可能是请求频繁或者是网址更新"
                return False, msg
            res = json.loads(response.text)
            if res["code"] == 0:
                self.stopp = True 
                self.notify("账号已成功暂停")
                return True, res["msg"]
            elif res["code"] == 400006:
                self.update_token("")
                return False, res["msg"]
            else:
                return False, res["msg"]
        except requests.exceptions.RequestException as e:
            return False, f"请求暂停失败: {e}"
        except json.JSONDecodeError:
            return False, "解析暂停响应失败。"

    def notify(self, message: str):
        """
        通知方法 (占位符，可扩展为邮件、微信等通知)
        """
        if self.serverchan_sendkey:
            sc_send(self.serverchan_sendkey, "雷神加速器 提示", message, { "tags": "雷神加速器"})

    def get_usage_details_and_full_data(self) -> tuple:
        """
        获取雷神加速器使用明细，并返回完整的数据列表，以及当前加速时长。
        返回 (bool, message, duration_minutes, full_data_dict)
        full_data_dict 包含 'list' 键，是使用记录列表。
        """
        if not self.token:
            return False, "Token 信息无效，无法获取使用明细。", 0, None

        payload = {
            "account_token": self.token,
            "page": 1,
            "size": 5, # 可以根据需要调整获取的记录数量
            "lang": "zh_CN",
            "region_code": 1,
            "src_channel": "guanwang",
            "os_type": 4
        }
        
        try:
            response = requests.post(self.usage_detail_url, data=payload, headers=self.header)
            response.raise_for_status()
            res = json.loads(response.text)

            if res["code"] != 0:
                if res["code"] == 400006:
                    self.update_token("")
                    return False, "Token 已失效，请重新登录获取。", 0, None
                return False, f"获取使用明细失败: {res['msg']}", 0, None

            full_data = res["data"] if "data" in res else {"list": []}

            # Inject 'duration' into each record from 'reduce_pause_time'
            if full_data and 'list' in full_data:
                for record in full_data['list']:
                    # Ensure 'duration' key exists for consistency with frontend expectation
                    # Use 'reduce_pause_time' if available, otherwise default to 0 or None
                    record['duration'] = record.get('reduce_pause_time', 0) 
            
            if not full_data or not full_data["list"]:
                return False, "未获取到使用明细数据。", 0, full_data

            latest_record = full_data["list"][0]
            
            is_paused_last_action = latest_record.get('pause_time') is not None and \
                                    latest_record.get('pause_time') != latest_record.get('recover_time')

            duration_minutes = 0
            message = "当前账号处于已暂停状态，无需操作。"

            if not is_paused_last_action:
                recover_time_str = latest_record.get('recover_time')
                if recover_time_str:
                    try:
                        recover_dt = datetime.strptime(recover_time_str, "%Y-%m-%d %H:%M:%S")
                        current_dt = datetime.now()
                        time_elapsed = current_dt - recover_dt
                        duration_minutes = time_elapsed.total_seconds() / 60 
                        message = f"当前账号处于未暂停状态，已持续 {duration_minutes:.2f} 分钟。"
                    except ValueError:
                        message = "解析恢复时间失败，格式不正确。"
                else:
                    message = "最新记录为恢复状态，但未找到恢复时间。"
            
            return True, message, duration_minutes, full_data
        
        except requests.exceptions.RequestException as e:
            return False, f"请求使用明细失败: {e}", 0, None
        except json.JSONDecodeError:
            return False, "解析使用明细响应失败。", 0, None
        except Exception as e:
            return False, f"处理使用明细时发生未知错误: {e}", 0, None

    def get_usage_details(self) -> tuple:
        """
        获取雷神加速器使用明细，并计算当前加速时长。
        返回 (bool, message, duration_minutes)
        此方法现在直接调用 get_usage_details_and_full_data 并返回前三个值。
        """
        success, message, duration_minutes, _ = self.get_usage_details_and_full_data()
        return success, message, duration_minutes


if __name__ == "__main__":
    debug = legod()
    test_token = "YOUR_LEIGOD_TOKEN_HERE" # 请替换为你的实际Token
    debug.update_token(test_token)
    print("--- 账户信息 ---")
    print(debug.get_account_info())
    print("--- 暂停操作 ---")
    print(debug.pause())
    print("--- 使用明细（简化后的接口）---")
    success, msg, duration = debug.get_usage_details()
    print(f"Success: {success}, Message: {msg}, Duration: {duration:.2f} min")
    print("--- 使用明细（新接口及完整数据）---")
    success, msg, duration, full_data = debug.get_usage_details_and_full_data()
    print(f"Success: {success}, Message: {msg}, Duration: {duration:.2f} min")
    if full_data:
        print("Full Data List:")
        for record in full_data.get('list', []):
            print(record)