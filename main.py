from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import logging
import uvicorn
import time
import legod # 确保 legod.py 已经修改为使用 logger
import os
import json
import threading
from contextlib import asynccontextmanager
from typing import Optional, Dict, List
from dotenv import load_dotenv

load_dotenv()

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # 默认设置为 INFO 级别

# 避免重复添加 handler，并统一格式
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

app = FastAPI() # FastAPI 实例现在在 lifespan 函数之后创建，以正确应用 lifespan

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
        # legod 实例现在会处理通知逻辑，其内部也使用了 logger
        self.leigod_obj = legod.legod(token=self.current_token) 
    
    @staticmethod
    def get_current_time() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

def check_usage_details_task():
    state = app.state

    if not state.current_token:
        logger.warning("定时任务：Token 无效，停止定时检查。")
        stop_usage_timer()
        return

    # 获取完整的 usage_details 信息
    success, message, duration_minutes, full_data = state.leigod_obj.get_usage_details_and_full_data() # 调用新的方法

    if success:
        logger.info(f"定时任务：使用明细检查结果: {message}")
        pause_minutes = int(os.getenv("PAUSE_THRESHOLD_MINUTES", "1440"))
        warning_minutes = int(os.getenv("WARNING_THRESHOLD_MINUTES", "1440"))
        if duration_minutes > pause_minutes:
            state.leigod_obj.notify(f"账号已加速{pause_minutes}分钟并尝试自动暂停: {message}") 
            pause_success, pause_msg = state.leigod_obj.pause()
            logger.info(f"定时任务：自动暂停{'成功' if pause_success else '失败'}: {pause_msg}")
        elif duration_minutes > warning_minutes:
            state.leigod_obj.notify(f"账号已加速超过{warning_minutes}分钟: {message}")
        
        # 更新 usage_records
        if full_data and 'list' in full_data:
            state.usage_records = full_data['list'] # 将使用明细列表保存到 state
        else:
            state.usage_records = [] # 如果没有数据，清空记录
            logger.info("定时任务：未获取到使用明细列表，记录已清空。")
    else:
        logger.error(f"定时任务：获取使用明细失败: {message}")
        state.usage_records = [] # 获取失败也清空记录

def start_usage_timer():
    stop_usage_timer() # 确保在启动前停止任何现有计时器
    
    if app.state.current_token:
        check_usage_details_task() # 立即执行一次
        interval = int(os.getenv("CHECK_INTERVAL_MINUTES", "60"))
        app.state.usage_timer = threading.Timer(interval * 60, start_usage_timer)
        app.state.usage_timer.daemon = True # 设置为守护线程，以便在主程序退出时自动终止
        app.state.usage_timer.start()
    else:
        logger.info("Token 为空，未启动定时检查任务。")

def stop_usage_timer():
    if app.state.usage_timer and app.state.usage_timer.is_alive():
        app.state.usage_timer.cancel()
        app.state.usage_timer = None
    elif app.state.usage_timer:
        logger.info("定时检查使用明细任务已停止（已完成或已取消）。")
    else:
        logger.info("没有正在运行的定时检查使用明细任务。")


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
                    logger.warning(f"初始使用明细获取失败: {msg_usage}")
            else:
                app.state.status_message = f"Token 初始化成功，但获取账号信息失败: {account_info[1]}"
        else:
            app.state.status_message = f"Token 初始化失败: {message}"
    else:
        app.state.status_message = "当前token为空，请更新token。"

    logger.info(app.state.status_message)
    start_usage_timer()
    yield
    stop_usage_timer()

app = FastAPI(lifespan=lifespan) # 将 lifespan 传递给 FastAPI 实例

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
                state.status_message = msg_usage
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
    logger.info(f"收到新 Token {mask_token(token)}")

    if token:
        success, message = state.leigod_obj.update_token(token)
        if success:
            account_info = state.leigod_obj.get_account_info()
            if account_info[0]:
                state.status_message = f"Token 更新成功！账号状态: {account_info[1]['pause_status']}"
                state.nickname = account_info[1]['nickname']
                logger.info(f"Token 更新成功，账号昵称: {state.nickname}")
                start_usage_timer() # 成功更新 Token 后启动定时器
                # 更新 token 后也立即获取使用记录
                success_usage, msg_usage, duration_minutes, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
                if success_usage and full_data_usage and 'list' in full_data_usage:
                    state.usage_records = full_data_usage['list']
                    if full_data_usage['list'] and full_data_usage['list'][0].get('pause_time') is None:
                        state.status_message = f"Token 更新成功！ {msg_usage} 分钟。"
                        logger.info(f"Token 更新后，当前账号状态: {msg_usage}")
                    else:
                        state.status_message = "Token 更新成功！当前账号处于已暂停状态。"
                        logger.info("Token 更新后，当前账号处于已暂停状态。")
                else:
                    state.usage_records = []
                    state.status_message = f"Token 更新成功，但获取使用明细失败: {msg_usage}"
                    logger.warning(f"Token 更新成功，但获取使用明细失败: {msg_usage}")
            else:
                state.status_message = f"Token 更新成功，但获取账号信息失败: {account_info[1]}"
                state.nickname = ""
                stop_usage_timer() # 获取账号信息失败，停止定时器
                state.usage_records = [] # 清空记录
                logger.error(f"Token 更新成功，但获取账号信息失败: {account_info[1]}")
        else:
            state.status_message = f"Token 更新失败: {message}"
            state.nickname = ""
            stop_usage_timer() # Token 更新失败，停止定时器
            state.usage_records = [] # 清空记录
            logger.error(f"Token 更新失败: {message}")
    else:
        state.nickname = ""
        state.status_message = "Token 为空，未能更新。"
        state.leigod_obj.update_token("") # 清空 legod 实例中的 token
        stop_usage_timer() # Token 为空，停止定时器
        state.usage_records = [] # 清空记录
        logger.warning("Token 为空，未能更新。")

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/pause", response_class=RedirectResponse)
async def pause_acceleration(request: Request):
    state = request.app.state
    logger.info("收到暂停加速请求。")
    
    if not state.current_token:
        state.status_message = "当前没有有效的Token，请先更新Token。"
        stop_usage_timer()
        state.usage_records = [] # 清空记录
        logger.warning("暂停加速请求：Token 无效。")
    else:
        # 暂停前先检查Token是否有效，防止过期Token反复尝试
        success_check_login, msg_check_login = state.leigod_obj.update_token(state.current_token)
        if not success_check_login:
            state.status_message = f"Token 已失效或登录失败，请重新登录: {msg_check_login}"
            state.nickname = ""
            stop_usage_timer()
            state.usage_records = [] # 清空记录
            logger.error(f"暂停加速请求：Token 已失效或登录失败: {msg_check_login}")
        else:
            success_pause, msg_pause = state.leigod_obj.pause()
            logger.info(f"暂停操作结果: {'成功' if success_pause else '失败'}, 消息: {msg_pause}")
            
            # 暂停操作后立即更新使用记录
            success_usage, usage_message, duration_minutes, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
            if success_usage:
                if full_data_usage and 'list' in full_data_usage:
                    state.usage_records = full_data_usage['list']
                    # 暂停成功后，更新状态消息以反映最新的使用状态
                    if full_data_usage['list'] and full_data_usage['list'][0].get('pause_time') is None:
                        state.status_message = usage_message
                        logger.info(f"暂停后，账号仍处于加速状态: {usage_message}")
                    else:
                        state.status_message = f"{msg_pause}！当前账号处于已暂停状态。"
                        logger.info(f"暂停后，账号已成功暂停: {state.status_message}")
                else:
                    state.usage_records = [] # 没有数据
                    state.status_message = f"{msg_pause}！但获取使用明细失败: {usage_message}" # 用使用明细接口返回的消息
                    logger.warning(f"暂停后，获取使用明细失败: {usage_message}")
            else:
                state.status_message = f"{msg_pause}！但获取使用明细失败: {usage_message}"
                state.usage_records = [] # 清空记录
                logger.error(f"暂停后，获取使用明细失败: {usage_message}")

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
    state.leigod_obj.update_token("") # 清空 legod 实例中的 token
    stop_usage_timer() # 重置状态，停止定时器
    logger.info("应用程序状态已重置。")
    return RedirectResponse("/", status_code=303)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")