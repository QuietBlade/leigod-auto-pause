from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
# from serverchan_sdk import sc_send # 不再需要直接导入 sc_send
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

# notify_enable = False # 不再需要这个变量
# serverchan = os.getenv('serverchan_sendkey', "") # 不再需要在这里获取
# if serverchan:
#     notify_enable = True

# 这里是提供的demo
# response = sc_send(serverchan, "雷神加速器 提示", "消息内容", { "tags": "雷神加速器"})


class AppState:
    def __init__(self):
        self.current_token: str = os.getenv('token', "")
        self.last_update_time: str = self.get_current_time() if self.current_token else "从未更新"
        self.nickname: str = ""
        self.status_message: str = "服务启动中..."
        self.history: List[Dict] = []
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

    usage_success, usage_message, duration_minutes = state.leigod_obj.get_usage_details()

    if usage_success:
        print(f"定时任务：使用明细检查结果: {usage_message}")
        if duration_minutes > 2:
            print(f"定时任务：已持续 {duration_minutes:.2f} 分钟，超过2分钟，尝试暂停加速...")
            # 直接调用 legod 对象的 notify 方法，它内部会判断是否发送通知
            state.leigod_obj.notify(f"账号已加速超过2分钟并尝试自动暂停: {usage_message}") 
            pause_success, pause_msg = state.leigod_obj.pause()
            print(f"定时任务：自动暂停{'成功' if pause_success else '失败'}: {pause_msg}")
        elif duration_minutes > 1:
            print(f"定时任务：已持续 {duration_minutes:.2f} 分钟，超过1分钟，发送通知...")
            # 直接调用 legod 对象的 notify 方法
            state.leigod_obj.notify(f"账号已加速超过1分钟: {usage_message}")
    else:
        print(f"定时任务：获取使用明细失败: {usage_message}")

def start_usage_timer():
    stop_usage_timer()
    
    if app.state.current_token:
        check_usage_details_task()
        app.state.usage_timer = threading.Timer(1800, start_usage_timer)
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
            else:
                app.state.status_message = f"Token 初始化成功，但获取账号信息失败: {account_info[1]}"
        else:
            app.state.status_message = f"Token 初始化失败: {message}"
    else:
        app.state.status_message = "当前token为空，请更新token。"

    if app.state.current_token and success:
        app.state.history.insert(0, {
            "time": app.state.last_update_time,
            "token": app.state.current_token
        })

    start_usage_timer()
    yield
    stop_usage_timer()

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    state = request.app.state
    usage_success, usage_message, _ = state.leigod_obj.get_usage_details()

    if usage_success and "Token 初始化失败" not in state.status_message and "Token 为空" not in state.status_message:
        state.status_message = usage_message

    return templates.TemplateResponse("index.html", {
        "request": request,
        "current_token": state.current_token,
        "nickname": state.nickname,
        "status_message": state.status_message,
        "last_update_time": state.last_update_time,
        "history": state.history[:5]
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
            else:
                state.status_message = f"Token 更新成功，但获取账号信息失败: {account_info[1]}"
                state.nickname = ""
                stop_usage_timer()
        else:
            state.status_message = f"Token 更新失败: {message}"
            state.nickname = ""
            stop_usage_timer()
    else:
        state.nickname = ""
        state.status_message = "Token 为空，未能更新。"
        state.leigod_obj.update_token("")
        stop_usage_timer()

    state.last_update_time = state.get_current_time()
    state.history.insert(0, {"time": state.last_update_time, "token": token})
    return RedirectResponse("/", status_code=303)

@app.post("/pause", response_class=RedirectResponse)
async def pause_acceleration(request: Request):
    state = request.app.state
    
    if not state.current_token:
        state.status_message = "当前没有有效的Token，请先更新Token。"
        stop_usage_timer()
    else:
        success_check_login, msg_check_login = state.leigod_obj.update_token(state.current_token)
        if not success_check_login:
            state.status_message = f"Token 已失效或登录失败，请重新登录: {msg_check_login}"
            state.nickname = ""
            stop_usage_timer()
        else:
            success_pause, msg_pause = state.leigod_obj.pause()
            state.status_message = f"{'暂停加速成功' if success_pause else '暂停加速失败'}! {msg_pause}"
            
            account_info = state.leigod_obj.get_account_info()
            if account_info[0]:
                state.nickname = account_info[1]['nickname']
                usage_success, usage_message, _ = state.leigod_obj.get_usage_details()
                if usage_success:
                    state.status_message = usage_message
                else:
                    state.status_message = f"暂停操作成功，但获取使用明细失败: {usage_message}"

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/reset", response_class=RedirectResponse)
async def reset_state(request: Request):
    state = request.app.state
    state.current_token = ""
    state.nickname = ""
    state.status_message = "状态已重置，请重新输入Token。"
    state.last_update_time = state.get_current_time()
    state.history = []
    state.leigod_obj.update_token("")
    stop_usage_timer()
    return RedirectResponse("/", status_code=303)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)