# 安装与运行（三种方式）

## 方式一：pip 安装（推荐小白）

> 当前 PyPI 发布暂未启用，`pip install ofbot2` 尚不可用；请使用方式二（Git 克隆）安装。

```bash
pip install ofbot2
```

创建运行目录并首次准备配置：

```bash
mkdir ~/ofbot && cd ~/ofbot
cp <仓库>/config.example.yaml ./config.yaml   # 或手动新建
ofbot2 run
```

- `ofbot2` 与 `python -m ofbot2` 等价。
- 运行时目录解析顺序：环境变量 `OFBOT2_ROOT` → 当前工作目录（含 `config.yaml` 或 `plugins/`）→ 包目录；建议在专用目录运行并把配置放当前目录。
- Web 后台默认 `http://127.0.0.1:8000`，首次登录 `admin / admin`（请立即修改）。

## 方式二：Git 克隆（开发/自定义）

```bash
git clone https://github.com/Laffey-82/OFbot2.git && cd OFbot2
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy config.example.yaml config.yaml
python main.py
```

Windows 也可以直接用 `install.bat` 安装、`start_bot.bat` 启动。

## 方式三：Docker

```bash
docker compose up -d
```

默认仅暴露本机 `127.0.0.1:8000`；数据、日志与插件使用命名卷持久化。参考 `docker-compose.yml` 与 `deploy/ofbot2.service`（systemd 单元示例）。

## 验证安装

```bash
ofbot2 version
ofbot2 doctor
```

`doctor` 会检查 Python 版本、依赖、数据库与配置完整性。

## 下一步

- 3 分钟上手：[QUICKSTART.md](QUICKSTART.md)
- 从零写第一个插件：[TUTORIAL.md](TUTORIAL.md)
- 接入 QQ：见 [CONNECTIONS.md](CONNECTIONS.md)（默认推荐 NapCat OneBot v11 反向 WS）
