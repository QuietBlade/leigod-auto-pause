from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn
import time
import legod
import os
import json
import threading
from contextlib import asynccontextmanager
from typing import Optional, Dict, List

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- 新增：脱敏 Token 的函数 ---
def mask_token(token: str, visible_chars: int = 6) -> str:
    """
    对Token进行脱敏处理，只显示开头和结尾的指定字符数，中间用星号代替。
    """
    if not token or len(token) <= visible_chars * 2:
        return token  # Token 太短，不进行脱敏
    
    start = token[:visible_chars]
    end = token[-visible_chars:]
    return f"{start}***{end}"
# --- 结束新增 ---


class AppState:
    def __init__(self):
        self.current_token: str = os.getenv('token', "")
        self.last_update_time: str = self.get_current_time() if self.current_token else "从未更新"
        self.nickname: str = ""
        self.status_message: str = "服务启动中..."
        self.usage_records: List[Dict] = [] # 新增：用于存储使用明细记录
        self.usage_timer: Optional[threading.Timer] = None
        self.leigod_obj = legod.legod(token=self.current_token) # legod 实例现在会处理通知逻辑
    
    @staticmethod
    def get_current_time() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

def check_usage_details_task():
    state = app.state
    print(f"[{state.get_current_time()}] 定时任务：正在检查使用明细...")

    if not state.current_token:
        print("定时任务：Token 无效，停止定时检查。")
        stop_usage_timer()
        return

    # 获取完整的 usage_details 信息
    success, message, duration_minutes, full_data = state.leigod_obj.get_usage_details_and_full_data() # 调用新的方法

    if success:
        print(f"定时任务：使用明细检查结果: {message}")
        # 目前雷神加速器 API 访问在重庆正常。如果时间超过2分钟，尝试自动暂停。
        if duration_minutes > 2:
            print(f"定时任务：已持续 {duration_minutes:.2f} 分钟，超过2分钟，尝试暂停加速...")
            state.leigod_obj.notify(f"账号已加速超过2分钟并尝试自动暂停: {message}") 
            pause_success, pause_msg = state.leigod_obj.pause()
            print(f"定时任务：自动暂停{'成功' if pause_success else '失败'}: {pause_msg}")
        elif duration_minutes > 1:
            print(f"定时任务：已持续 {duration_minutes:.2f} 分钟，超过1分钟，发送通知...")
            state.leigod_obj.notify(f"账号已加速超过1分钟: {message}")
        
        # 更新 usage_records
        if full_data and 'list' in full_data:
            state.usage_records = full_data['list'] # 将使用明细列表保存到 state
        else:
            state.usage_records = [] # 如果没有数据，清空记录
    else:
        print(f"定时任务：获取使用明细失败: {message}")
        state.usage_records = [] # 获取失败也清空记录

def start_usage_timer():
    stop_usage_timer()
    
    if app.state.current_token:
        check_usage_details_task()
        app.state.usage_timer = threading.Timer(1800, start_usage_timer) # 30分钟定时
        app.state.usage_timer.daemon = True
        app.state.usage_timer.start()
        print("定时检查使用明细任务已启动。")
    else:
        print("Token 为空，未启动定时检查任务。")

def stop_usage_timer():
    if app.state.usage_timer and app.state.usage_timer.is_alive():
        app.state.usage_timer.cancel()
        app.state.usage_timer = None
        print("定时检查使用明细任务已停止。")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state = AppState()
    
    if app.state.current_token:
        success, message = app.state.leigod_obj.update_token(app.state.current_token)
        if success:
            account_info = app.state.leigod_obj.get_account_info()
            if account_info[0]:
                app.state.status_message = f"Token 初始化成功！账号状态: {account_info[1]['pause_status']}"
                app.state.nickname = account_info[1]['nickname']
                # 初始加载时也尝试获取使用记录
                success_usage, msg_usage, _, full_data_usage = app.state.leigod_obj.get_usage_details_and_full_data()
                if success_usage and full_data_usage and 'list' in full_data_usage:
                    app.state.usage_records = full_data_usage['list']
            else:
                app.state.status_message = f"Token 初始化成功，但获取账号信息失败: {account_info[1]}"
        else:
            app.state.status_message = f"Token 初始化失败: {message}"
    else:
        app.state.status_message = "当前token为空，请更新token。"

    start_usage_timer()
    yield
    stop_usage_timer()

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    state = request.app.state
    
    # 刷新页面时，也确保 usage_records 是最新的
    if state.current_token:
        success_usage, msg_usage, duration_minutes, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
        if success_usage and full_data_usage and 'list' in full_data_usage:
            state.usage_records = full_data_usage['list']
            # 如果当前状态消息不是错误，则更新为最新的使用状态
            if full_data_usage['list'] and full_data_usage['list'][0].get('pause_time') is None:
                state.status_message = f"当前账号处于未暂停状态，已持续 {duration_minutes:.2f} 分钟。"
            else:
                state.status_message = "当前账号处于已暂停状态。"
        else:
            state.status_message = msg_usage # 如果获取使用明细失败，更新状态消息
            state.usage_records = []
    else:
        state.usage_records = []
        state.status_message = "当前token为空，请更新token。" # 确保token为空时状态消息正确

    # --- 修改这里，传递脱敏后的 Token ---
    masked_token_display = mask_token(state.current_token) if state.current_token else '未设置'

    return templates.TemplateResponse("index.html", {
        "request": request,
        "current_token": masked_token_display, # 使用脱敏后的 Token
        "nickname": state.nickname,
        "status_message": state.status_message,
        "last_update_time": state.get_current_time(), 
        "usage_records": state.usage_records 
    })

@app.post("/update-token", response_class=RedirectResponse)
async def update_token(request: Request, token: str = Form(...)):
    state = request.app.state
    state.current_token = token
    print(f"收到新 Token: {token}")

    if token:
        success, message = state.leigod_obj.update_token(token)
        if success:
            account_info = state.leigod_obj.get_account_info()
            if account_info[0]:
                state.status_message = f"Token 更新成功！账号状态: {account_info[1]['pause_status']}"
                state.nickname = account_info[1]['nickname']
                start_usage_timer()
                # 更新 token 后也立即获取使用记录
                success_usage, msg_usage, duration_minutes, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
                if success_usage and full_data_usage and 'list' in full_data_usage:
                    state.usage_records = full_data_usage['list']
                    if full_data_usage['list'] and full_data_usage['list'][0].get('pause_time') is None:
                        state.status_message = f"Token 更新成功！当前账号处于未暂停状态，已持续 {duration_minutes:.2f} 分钟。"
                    else:
                        state.status_message = "Token 更新成功！当前账号处于已暂停状态。"
                else:
                    state.usage_records = []
                    state.status_message = f"Token 更新成功，但获取使用明细失败: {msg_usage}"
            else:
                state.status_message = f"Token 更新成功，但获取账号信息失败: {account_info[1]}"
                state.nickname = ""
                stop_usage_timer()
                state.usage_records = [] # 清空记录
        else:
            state.status_message = f"Token 更新失败: {message}"
            state.nickname = ""
            stop_usage_timer()
            state.usage_records = [] # 清空记录
    else:
        state.nickname = ""
        state.status_message = "Token 为空，未能更新。"
        state.leigod_obj.update_token("")
        stop_usage_timer()
        state.usage_records = [] # 清空记录

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/pause", response_class=RedirectResponse)
async def pause_acceleration(request: Request):
    state = request.app.state
    
    if not state.current_token:
        state.status_message = "当前没有有效的Token，请先更新Token。"
        stop_usage_timer()
        state.usage_records = [] # 清空记录
    else:
        success_check_login, msg_check_login = state.leigod_obj.update_token(state.current_token)
        if not success_check_login:
            state.status_message = f"Token 已失效或登录失败，请重新登录: {msg_check_login}"
            state.nickname = ""
            stop_usage_timer()
            state.usage_records = [] # 清空记录
        else:
            success_pause, msg_pause = state.leigod_obj.pause()
            
            # 暂停操作后立即更新使用记录
            success_usage, usage_message, duration_minutes, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
            if success_usage:
                if full_data_usage and 'list' in full_data_usage:
                    state.usage_records = full_data_usage['list']
                    # 暂停成功后，更新状态消息以反映最新的使用状态
                    if full_data_usage['list'] and full_data_usage['list'][0].get('pause_time') is None:
                        state.status_message = f"{msg_pause}！当前账号处于未暂停状态，已持续 {duration_minutes:.2f} 分钟。"
                    else:
                        state.status_message = f"{msg_pause}！当前账号处于已暂停状态。"
                else:
                    state.usage_records = [] # 没有数据
                    state.status_message = f"{msg_pause}！但获取使用明细失败: {usage_message}" # 用使用明细接口返回的消息
            else:
                state.status_message = f"{msg_pause}！但获取使用明细失败: {usage_message}"
                state.usage_records = [] # 清空记录

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/reset", response_class=RedirectResponse)
async def reset_state(request: Request):
    state = request.app.state
    state.current_token = ""
    state.nickname = ""
    state.status_message = "状态已重置，请重新输入Token。"
    state.last_update_time = state.get_current_time()
    state.usage_records = [] # 清空使用记录
    state.leigod_obj.update_token("")
    stop_usage_timer()
    return RedirectResponse("/", status_code=303)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)