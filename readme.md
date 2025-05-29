# 前言

前段时间玩游戏没注意暂停，怒失200游戏时长，一怒之下写了这个工具, 推荐有服务器的人使用（因为需要24h运行

由于前段时间leigod更改了登录接口，现在需要滑动验证码进行登录， 正在尝试滑动登录方案

当前方案是输入token，然后监听


# 雷神加速器暂停管理服务

一个基于 FastAPI 的小型服务，用于管理雷神加速器的账号暂停状态，并支持自动暂停功能。

```

## 功能特性

* **Token 管理**: 方便地更新和重置雷神加速器账号 Token。
* **账号信息展示**: 显示当前 Token 对应的昵称和账号状态。
* **一键暂停**: 手动触发暂停加速操作。
* **使用记录**: 展示最近的加速和暂停明细，包括每次加速的时长。
* **自动暂停**: 当检测到账号处于加速状态超过设定阈值时（默认为2分钟），尝试自动暂停加速。
* **Server酱通知**: 集成 Server酱，可在自动暂停或加速时长超过阈值时发送通知。
* **Docker 支持**: 提供 Dockerfile 方便部署。

```

## 快速开始 (使用 Docker)

这是推荐的部署方式，简单方便。

### 1. 克隆仓库

```bash
git clone https://github.com/QuietBlade/leigod-auto-pause.git
cd leigod-auto-pause
```

### 2. 配置环境变量

这两个环境变量（`token` 和 `serverchan_sendkey`）都不是必须的，设置 `token` 初始化用户信息，设置 `serverchan_sendkey` 启用微信通知。

```ini
# .env 文件示例 (推荐使用此文件来管理环境变量)
# token="你的雷神加速器账号Token"
# serverchan_sendkey="你的Server酱SendKey (可选，用于微信通知)"
```

**如何获取 Token**:

1.  访问 [雷神加速器官网](https://www.leigod.com/) 并登录。
2.  登录成功后，按下 **F12** 打开浏览器开发者工具，切换到 **控制台 (Console)** 标签页。
3.  在控制台中输入以下代码并回车，即可获取你的 `account_token`：

    ```javascript
    JSON.parse(localStorage.getItem('account_token')).account_token
    ```

**如何获取 Server酱 SendKey**:
访问 [Server酱官网](https://sct.ftqq.com/) 注册并获取 SendKey。

### 3. 构建 Docker 镜像

根据你的需求，这里提供两种构建方式：

#### 方式一：直接构建为 `yuanzhangzcc/leigod-auto-pause` 镜像

如果你希望直接构建并推送到指定名称的镜像仓库，可以使用：

```bash
docker build -t yuanzhangzcc/leigod-auto-pause .
```

#### 方式二：构建为本地镜像（不指定仓库名称）

如果你只在本地运行，不需要推送到远程仓库，可以使用：

```bash
docker build -t leigod-auto-pause .
```

### 4. 运行 Docker 容器

#### 使用 Docker 命令直接运行 (推荐)

这种方式可以直接在命令中设置环境变量，不需要 `.env` 文件。

```cmd
docker run -d \
  --name leigod-auto-pause-service \
  -p 8000:8000 \
  -e token="YOUR_LEIGOD_TOKEN_HERE" \
  -e serverchan_sendkey="YOUR_SERVERCHAN_SENDKEY_HERE" \
  --restart always \
  yuanzhangzcc/leigod-auto-pause
```

**请注意**:
* 将 `YOUR_LEIGOD_TOKEN_HERE` 替换为你的实际 Token。如果不需要，可以将这行删除。
* 将 `YOUR_SERVERCHAN_SENDKEY_HERE` 替换为你的 Server酱 SendKey。如果不需要，可以将这行删除。

#### 使用 Docker Compose 运行

首先，确保你的项目根目录下有 `docker-compose.yml` 文件：

```yaml
version: '3.8'

services:
  leigod-auto-pause:
    image: yuanzhangzcc/leigod-auto-pause
    container_name: leigod-auto-pause-service
    ports:
      - "8000:8000"
    environment:
      # 将 YOUR_LEIGOD_TOKEN_HERE 替换为你的实际 Token
      - token="YOUR_LEIGOD_TOKEN_HERE" 
      # 将 YOUR_SERVERCHAN_SENDKEY_HERE 替换为你的 Server酱 SendKey (可选)
      - serverchan_sendkey="YOUR_SERVERCHAN_SENDKEY_HERE" 
    restart: always
```

然后运行：

```cmd
docker-compose up -d
```

### 5. 访问服务

在浏览器中访问 `http://localhost:8000` (如果部署在其他服务器，请替换为服务器IP)。

```

## 手动运行

```cmd
git clone [https://github.com/QuietBlade/leigod-auto-pause.git](https://github.com/QuietBlade/leigod-auto-pause.git)
cd leigod-auto-pause
# 设置本地环境变量, 都不是非必须
# 你可以通过以下命令设置环境变量，或者直接在 shell 中 export
echo token="" > .env
echo serverchan_sendkey="" >> .env
# 确保你的 .env 文件与你的 shell 环境兼容，某些 shell 可能需要 source .env
# 或者直接在运行命令时传入环境变量
# export token="YOUR_LEIGOD_TOKEN_HERE"
# export serverchan_sendkey="YOUR_SERVERCHAN_SENDKEY_HERE"
python main.py
```

```

## 项目结构

```
.
├── main.py             # FastAPI 主应用
├── legod.py            # 雷神加速器 API 交互逻辑
├── templates/
│   └── index.html      # 网页前端模板
├── pyproject.toml      # Poetry 项目配置及依赖
├── poetry.lock         # Poetry 锁定依赖版本
├── Dockerfile          # Docker 构建文件
└── README.md           # 项目说明文档
```

```

## 贡献

欢迎提交 Pull Request 或 Issues 来改进项目！

```

## 许可证

本项目基于 MIT 许可证开源。