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

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]