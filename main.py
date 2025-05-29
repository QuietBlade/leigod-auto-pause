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
        self.usage_records: List[Dict] = [] 
        self.usage_timer: Optional[threading.Timer] = None
        self.leigod_obj = legod.legod(token=self.current_token)
        # 新增：用于跟踪上一次定时器检测时账号是否为暂停状态
        self.is_last_known_state_paused: Optional[bool] = None # True: paused, False: accelerating, None: undetermined
    
    @staticmethod
    def get_current_time() -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S")

def check_usage_details_task():
    state = app.state

    if not state.current_token:
        logger.warning("定时任务：Token 无效，停止定时检查。")
        stop_usage_timer() # Ensure timer stops if token becomes invalid
        return

    success, message, duration_minutes, full_data = state.leigod_obj.get_usage_details_and_full_data()

    current_is_determined_to_be_paused: Optional[bool] = None

    if success:
        # Determine current pause state primarily from the message
        if "已暂停状态" in message:
            current_is_determined_to_be_paused = True
        elif "未暂停状态" in message: # Covers "未暂停状态" and "最新记录为恢复状态，但未找到恢复时间"
            current_is_determined_to_be_paused = False
        elif full_data and 'list' in full_data and full_data['list']: # Fallback if message is not clear
            latest_record = full_data['list'][0]
            pause_time = latest_record.get('pause_time')
            recover_time = latest_record.get('recover_time')
            if pause_time and (not recover_time or pause_time >= recover_time):
                current_is_determined_to_be_paused = True
            elif recover_time and (not pause_time or recover_time > pause_time):
                current_is_determined_to_be_paused = False
            elif duration_minutes > 0 : # If time has elapsed and not clearly paused/recovered by times
                 current_is_determined_to_be_paused = False
        # If message was "未获取到使用明细数据。", full_data['list'] would be empty, current_is_determined_to_be_paused remains None.

        if current_is_determined_to_be_paused is not None:
            if state.is_last_known_state_paused is True and current_is_determined_to_be_paused is False:
                notification_message = f"检测到状态从暂停变为加速, 请确认是本人操作"
                state.leigod_obj.notify(notification_message)
            
            state.is_last_known_state_paused = current_is_determined_to_be_paused # Update state for next check

        # Original auto-pause logic
        pause_minutes_env = os.getenv("PAUSE_THRESHOLD_MINUTES")
        warning_minutes_env = os.getenv("WARNING_THRESHOLD_MINUTES")

        # Ensure values from env are valid integers, otherwise use defaults or skip
        try:
            pause_threshold_minutes = int(pause_minutes_env) if pause_minutes_env is not None else 1440 # Default 24h
        except ValueError:
            logger.warning(f"无效的 PAUSE_THRESHOLD_MINUTES值: {pause_minutes_env}，将使用默认值或不触发自动暂停。")
            pause_threshold_minutes = float('inf') # Effectively disable if invalid

        try:
            warning_threshold_minutes = int(warning_minutes_env) if warning_minutes_env is not None else 1440 # Default 24h
        except ValueError:
            logger.warning(f"无效的 WARNING_THRESHOLD_MINUTES值: {warning_minutes_env}，将使用默认值或不触发警告。")
            warning_threshold_minutes = float('inf') # Effectively disable if invalid

        if current_is_determined_to_be_paused is False: # Only consider auto-pause if currently accelerating
            if duration_minutes > pause_threshold_minutes:
                state.leigod_obj.notify(f"账号已加速超过 {pause_threshold_minutes} 分钟并尝试自动暂停: {message}")
                pause_success, pause_msg = state.leigod_obj.pause()
                logger.info(f"定时任务：自动暂停{'成功' if pause_success else '失败'}: {pause_msg}")
                if pause_success:
                    state.is_last_known_state_paused = True # Update state immediately after successful pause
            elif duration_minutes > warning_threshold_minutes:
                state.leigod_obj.notify(f"账号已加速超过 {warning_threshold_minutes} 分钟: {message}")
        
        if full_data and 'list' in full_data:
            state.usage_records = full_data['list']
        else:
            state.usage_records = []
            if success: # Only log if API call was successful but no list data
                 logger.info("定时任务：未获取到使用明细列表，记录已清空。")

    else: # get_usage_details_and_full_data failed
        logger.error(f"定时任务：获取使用明细失败: {message}")
        state.usage_records = []
        # Do not change state.is_last_known_state_paused if API call fails, keep last known state.
        logger.info(f"定时任务：获取使用明细失败，上次记录的暂停状态 ({state.is_last_known_state_paused}) 将保持不变。")


def start_usage_timer():
    stop_usage_timer() 
    
    if app.state.current_token:
        check_usage_details_task() 
        interval_env = os.getenv("CHECK_INTERVAL_MINUTES", "60")
        try:
            interval = int(interval_env)
            if interval <= 0:
                interval = 60 # Default to 60 if non-positive
                logger.warning(f"CHECK_INTERVAL_MINUTES 值 ({interval_env}) 无效，已重置为60分钟。")
        except ValueError:
            interval = 60 # Default to 60 if not a valid integer
            logger.warning(f"CHECK_INTERVAL_MINUTES 值 ({interval_env}) 无效，已重置为60分钟。")

        app.state.usage_timer = threading.Timer(interval * 60, start_usage_timer)
        app.state.usage_timer.daemon = True
        app.state.usage_timer.start()
        logger.info(f"定时检查任务已启动，间隔: {interval} 分钟。")
    else:
        logger.info("Token 为空，未启动定时检查任务。")

def stop_usage_timer():
    if app.state.usage_timer and app.state.usage_timer.is_alive():
        app.state.usage_timer.cancel()
        app.state.usage_timer = None
    elif app.state.usage_timer: # Timer exists but not alive (already finished/cancelled)
        app.state.usage_timer = None # Clear it
    # else: No timer was running or set

@asynccontextmanager
async def lifespan(app_instance: FastAPI): # Renamed app to app_instance to avoid conflict
    app_instance.state = AppState()
    state = app_instance.state # Use local variable for convenience

    if state.current_token:
        success, message = state.leigod_obj.update_token(state.current_token)
        if success:
            account_info_tuple = state.leigod_obj.get_account_info()
            if account_info_tuple[0]:
                account_data = account_info_tuple[1]
                state.status_message = f"Token 初始化成功！账号状态: {account_data.get('pause_status', '未知')}"
                state.nickname = account_data.get('nickname', '')
                
                # Initialize is_last_known_state_paused
                if 'pause_status_id' in account_data:
                    state.is_last_known_state_paused = (account_data['pause_status_id'] == 1)
                    logger.info(f"Lifespan: 初始暂停状态根据 account_info 设置为: {state.is_last_known_state_paused} (ID: {account_data['pause_status_id']})")
                else:
                    # Fallback: Try to infer from initial usage details
                    s_usage, m_usage, _, fd_usage = state.leigod_obj.get_usage_details_and_full_data()
                    if s_usage:
                        if "已暂停状态" in m_usage: state.is_last_known_state_paused = True
                        elif "未暂停状态" in m_usage: state.is_last_known_state_paused = False
                        else: state.is_last_known_state_paused = None
                        logger.info(f"Lifespan: 初始暂停状态根据 usage_details 设置为: {state.is_last_known_state_paused} (消息: '{m_usage}')")
                    else:
                        state.is_last_known_state_paused = None
                        logger.warning(f"Lifespan: 获取初始使用明细失败 ({m_usage})，无法确定初始暂停状态。")
                
                success_usage, msg_usage, _, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
                if success_usage and full_data_usage and 'list' in full_data_usage:
                    state.usage_records = full_data_usage['list']
                else:
                    logger.warning(f"初始使用明细获取失败: {msg_usage}")
            else:
                state.status_message = f"Token 初始化成功，但获取账号信息失败: {account_info_tuple[1]}"
                state.is_last_known_state_paused = None
                logger.error(f"Lifespan: 获取账号信息失败, 初始暂停状态未确定: {account_info_tuple[1]}")
        else:
            state.status_message = f"Token 初始化失败: {message}"
            state.is_last_known_state_paused = None
            logger.error(f"Lifespan: Token 初始化失败, 初始暂停状态未确定: {message}")
    else:
        state.status_message = "当前token为空，请更新token。"
        state.is_last_known_state_paused = None
        logger.info("Lifespan: Token 为空, 初始暂停状态未确定。")

    logger.info(f"Lifespan: 服务状态: {state.status_message}, 初始暂停检测状态: {state.is_last_known_state_paused}")
    start_usage_timer()
    yield
    stop_usage_timer()

app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    state = request.app.state
    
    if state.current_token:
        success_usage, msg_usage, _, full_data_usage = state.leigod_obj.get_usage_details_and_full_data()
        if success_usage:
            if full_data_usage and 'list' in full_data_usage:
                state.usage_records = full_data_usage['list']
            else:
                state.usage_records = [] # No list data even if call was success

            # Update status message based on latest usage details if not an error message already
            if not ("失败" in state.status_message or "错误" in state.status_message): # Avoid overwriting error messages
                if "已暂停状态" in msg_usage:
                    state.status_message = "当前账号处于已暂停状态。"
                elif "未暂停状态" in msg_usage:
                     state.status_message = msg_usage # e.g., "当前账号处于未暂停状态，已持续 X 分钟。"
                # else, keep existing status_message if usage message is ambiguous for main page display
        else:
            state.status_message = msg_usage # Reflect error from get_usage_details
            state.usage_records = []
    else:
        state.usage_records = []
        state.status_message = "当前token为空，请更新token。"

    masked_token_display = mask_token(state.current_token) if state.current_token else '未设置'

    return templates.TemplateResponse("index.html", {
        "request": request,
        "current_token": masked_token_display,
        "nickname": state.nickname,
        "status_message": state.status_message,
        "last_update_time": state.get_current_time(), 
        "usage_records": state.usage_records 
    })

@app.post("/update-token", response_class=RedirectResponse)
async def update_token(request: Request, token: str = Form(...)):
    state = request.app.state
    state.current_token = token # Store full token in state
    logger.info(f"收到新 Token {mask_token(token)}") # Log masked token

    if token:
        success, message = state.leigod_obj.update_token(token)
        if success:
            account_info_tuple = state.leigod_obj.get_account_info()
            if account_info_tuple[0]:
                account_data = account_info_tuple[1]
                state.nickname = account_data.get('nickname', '')
                
                # Update is_last_known_state_paused
                if 'pause_status_id' in account_data:
                    state.is_last_known_state_paused = (account_data['pause_status_id'] == 1)
                    logger.info(f"Token Update: 暂停状态根据 account_info 设置为: {state.is_last_known_state_paused} (ID: {account_data['pause_status_id']})")
                else:
                    # Fallback if pause_status_id is missing
                    s_usage, m_usage, _, _ = state.leigod_obj.get_usage_details_and_full_data()
                    if s_usage:
                        if "已暂停状态" in m_usage: state.is_last_known_state_paused = True
                        elif "未暂停状态" in m_usage: state.is_last_known_state_paused = False
                        else: state.is_last_known_state_paused = None
                        logger.info(f"Token Update: 暂停状态根据 usage_details 设置为: {state.is_last_known_state_paused} (消息: '{m_usage}')")
                    else:
                        state.is_last_known_state_paused = None
                        logger.warning(f"Token Update: 获取使用明细失败 ({m_usage})，无法确定暂停状态。")

                # Update status message and usage records
                s_usage, m_usage, dur_min, fd_usage = state.leigod_obj.get_usage_details_and_full_data()
                if s_usage:
                    state.usage_records = fd_usage.get('list', [])
                    if "已暂停状态" in m_usage:
                        state.status_message = f"Token 更新成功！当前账号处于已暂停状态。"
                    elif "未暂停状态" in m_usage:
                        state.status_message = f"Token 更新成功！{m_usage}"
                    else: # Ambiguous or other message
                        state.status_message = f"Token 更新成功！账号状态: {account_data.get('pause_status', '未知')}. 使用明细: {m_usage}"
                    logger.info(f"Token 更新后，状态: {state.status_message}")
                else:
                    state.usage_records = []
                    state.status_message = f"Token 更新成功！但获取使用明细失败: {m_usage}"
                    logger.warning(f"Token 更新成功，但获取使用明细失败: {m_usage}")
                
                start_usage_timer()
            else:
                state.status_message = f"Token 更新成功，但获取账号信息失败: {account_info_tuple[1]}"
                state.nickname = ""
                state.is_last_known_state_paused = None
                stop_usage_timer()
                state.usage_records = []
                logger.error(f"Token 更新成功，但获取账号信息失败: {account_info_tuple[1]}")
        else:
            state.status_message = f"Token 更新失败: {message}"
            state.nickname = ""
            state.is_last_known_state_paused = None
            stop_usage_timer()
            state.usage_records = []
            logger.error(f"Token 更新失败: {message}")
    else: # Token is empty
        state.nickname = ""
        state.status_message = "Token 为空，未能更新。"
        state.leigod_obj.update_token("")
        state.is_last_known_state_paused = None
        stop_usage_timer()
        state.usage_records = []
        logger.warning("Token 为空，未能更新，定时任务已停止。")

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/pause", response_class=RedirectResponse)
async def pause_acceleration(request: Request):
    state = request.app.state
    logger.info("收到暂停加速请求。")
    
    if not state.current_token:
        state.status_message = "当前没有有效的Token，请先更新Token。"
        # state.is_last_known_state_paused remains unchanged or could be set to None
        state.usage_records = []
        logger.warning("暂停加速请求：Token 无效。")
    else:
        success_check_login, msg_check_login = state.leigod_obj.update_token(state.current_token) # Re-validate token
        if not success_check_login:
            state.status_message = f"Token 已失效或登录失败，请重新登录: {msg_check_login}"
            state.nickname = ""
            state.is_last_known_state_paused = None # Token invalid, state unknown
            stop_usage_timer()
            state.usage_records = []
            logger.error(f"暂停加速请求：Token 已失效或登录失败: {msg_check_login}")
        else:
            # Refresh account info to correctly set nickname and initial pause state before manual pause
            account_info_tuple = state.leigod_obj.get_account_info()
            if account_info_tuple[0]:
                state.nickname = account_info_tuple[1].get('nickname', '')
                if 'pause_status_id' in account_info_tuple[1]:
                     state.is_last_known_state_paused = (account_info_tuple[1]['pause_status_id'] == 1)
            
            success_pause, msg_pause = state.leigod_obj.pause()
            logger.info(f"手动暂停操作结果: {'成功' if success_pause else '失败'}, 消息: {msg_pause}")
            
            if success_pause:
                state.is_last_known_state_paused = True # Successfully paused
            
            s_usage, m_usage, _, fd_usage = state.leigod_obj.get_usage_details_and_full_data()
            if s_usage:
                state.usage_records = fd_usage.get('list', [])
                if "已暂停状态" in m_usage: # Expected after successful pause
                    state.status_message = f"{msg_pause} 当前账号处于已暂停状态。"
                elif "未暂停状态" in m_usage: # Pause might have failed or not reflected yet
                     state.status_message = f"{msg_pause} 但状态仍为: {m_usage}"
                else:
                    state.status_message = f"{msg_pause} 使用明细: {m_usage}"
            else:
                state.usage_records = []
                state.status_message = f"{msg_pause} 但获取使用明细失败: {m_usage}"
                logger.error(f"手动暂停后，获取使用明细失败: {m_usage}")

    state.last_update_time = state.get_current_time()
    return RedirectResponse("/", status_code=303)

@app.post("/reset", response_class=RedirectResponse)
async def reset_state(request: Request):
    state = request.app.state
    state.current_token = ""
    state.nickname = ""
    state.status_message = "状态已重置，请重新输入Token。"
    state.last_update_time = state.get_current_time()
    state.usage_records = []
    state.leigod_obj.update_token("")
    state.is_last_known_state_paused = None # Reset pause state
    stop_usage_timer()
    logger.info("应用程序状态已重置。")
    return RedirectResponse("/", status_code=303)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning") # Changed log_level for uvicorn for more details if needed