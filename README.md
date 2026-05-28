# Ultritouch Fiber Kiosk Monitor

Portrait kiosk (1080×1920) for flypack fiber health: **Stageracer2** (Ember+), **Arista** core (SNMP), **Aruba** switches (SNMP).

Everything lives in this repo — including [`config.yaml`](config.yaml). Edit config, push to GitHub, redeploy the stack.

## Portainer

1. **Stacks** → **Add stack**
2. Either:
   - **Repository:** `https://github.com/Broadcast-Rental/Ultritouch_Monitor`, branch `main`, compose `docker-compose.yml`, or
   - **Web editor:** paste [docker-compose.yml](docker-compose.yml) from the repo
3. **Deploy** — Docker clones GitHub and builds (no Dockerfile needed on the Portainer host folder)
4. After you change `config.yaml` on GitHub: **Pull and redeploy** (rebuild picks up new config)
5. Kiosk: `http://<server-ip>:8080/`

If the repo is **private**, add Git credentials in Portainer or make the repo public (the compose build pulls from GitHub).

## SSH (same idea)

```bash
git clone https://github.com/Broadcast-Rental/Ultritouch_Monitor.git
cd Ultritouch_Monitor
docker compose up --build -d
```

## Config

Edit [`config.yaml`](config.yaml) in GitHub (or locally and push).

- **arista.ports** — run once on a machine that can reach the Arista:

  ```bash
  pip install -r requirements.txt
  python -m src.discover_arista --output arista_ports.yaml
  ```

  Merge `arista.ports` into `config.yaml`, commit, redeploy.

[`config.example.yaml`](config.example.yaml) is only a reference copy.

## Logs

```bash
docker compose logs -f
```

You should see `=== Network connectivity ===` and `=== Status summary ===` each poll.

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Kiosk UI |
| `GET /api/status` | JSON status |
| `GET /health` | Liveness |

## Kiosk browser (Windows)

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --kiosk --app=http://<server-ip>:8080/ `
  --window-size=1080,1920 `
  --disable-pinch
```

## Development (no Docker)

```bash
pip install -r requirements.txt
cd ember && npm install && cd ..
mkdir -p data
node ember/poller.mjs          # terminal 1
python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080   # terminal 2
```

## Tests

```bash
pytest tests/
```

## Troubleshooting

**`address already in use` on port 8080** — With `network_mode: host`, only one process on the server can use that port. Stop duplicate stacks in Portainer, or run `docker stop ultritouch-monitor` and remove old containers. Or change `api.port` in `config.yaml` (e.g. `8088`) and open `http://<server>:8088/`.

**Ember `No device matching … under 997`** — Check logs for `Children found:` and set `ember.sr2_name_match` in `config.yaml` to a substring of the real device name.

## Notes

- `network_mode: host` — container uses the host network (needed for `172.21.x`). UI on port **8080** (see `api.port` in config).
- Docker Desktop on Windows often cannot reach `172.21.x`; run on the Portainer host on the rack network.
- Aruba: uplink ifIndex **26** (link/errors only). Arista: DOM via discovery.
