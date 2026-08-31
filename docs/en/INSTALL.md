# Install & Run

> [中文版](../INSTALL.md)

## Option 1: pip (recommended for beginners)

> PyPI publishing is not enabled yet; `pip install ofbot2` is not available.
> Use Option 2 (Git clone) for now.

```bash
pip install ofbot2
```

Create a run directory and prepare the config on first start:

```bash
mkdir ~/ofbot && cd ~/ofbot
cp <repo>/config.example.yaml ./config.yaml
ofbot2 run
```

- `ofbot2` is equivalent to `python -m ofbot2`.
- Runtime directory resolution: `OFBOT2_ROOT` env var → current working directory
  (with `config.yaml` or `plugins/`) → package directory.
- Web admin defaults to http://127.0.0.1:8000; first login `admin / admin`
  (change it immediately).

## Option 2: Git clone (development / customization)

```bash
git clone https://github.com/Laffey-82/OFbot2.git && cd OFbot2
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy config.example.yaml config.yaml
python main.py
```

On Windows you can also use `install.bat` and `start_bot.bat`.

## Option 3: Docker

```bash
docker compose up -d
```

Only `127.0.0.1:8000` is exposed by default; data, logs and plugins use named volumes.
See `docker-compose.yml` and `deploy/ofbot2.service` (systemd unit example).

## Verify the installation

```bash
ofbot2 version
ofbot2 doctor
```

`doctor` checks Python version, dependencies, database and config integrity.

## Next steps

- [QUICKSTART.md](QUICKSTART.md) — 3-minute start
- [TUTORIAL.md](../TUTORIAL.md) — write your first plugin
- [CONNECTIONS.md](CONNECTIONS.md) — connect QQ (NapCat OneBot v11 reverse WS recommended)
