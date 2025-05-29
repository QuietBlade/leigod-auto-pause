# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Define environment variable for Server酱 send key (if used)
# You should set this in your deployment environment, not hardcode it here
ENV serverchan_sendkey=""
ENV token=""
# 警告时间 12小时 = 720分钟
ENV WARNING_THRESHOLD_MINUTES=720
# 暂停时间 24小时 = 1440分钟
ENV PAUSE_THRESHOLD_MINUTES=1440
 # 定时器间隔 30分钟
ENV CHECK_INTERVAL_MINUTES=30
ENV TZ=Asia/Shanghai

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]

# docker build -t yuanzhangzcc/leigod-auto-pause:v2.2.5 -t yuanzhangzcc/leigod-auto-pause:latest .
# docker push yuanzhangzcc/leigod-auto-pause:v2.2.5
# docker push yuanzhangzcc/leigod-auto-pause:latest