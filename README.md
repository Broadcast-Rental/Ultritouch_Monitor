# Ultritouch Fiber Kiosk Monitor

Portrait kiosk dashboard (1080×1920) for flypack fiber health: **Stageracer2** (Ember+), **Arista** core (SNMP DOM + errors), and **Aruba** switches (SNMP link + errors).

## Quick start (Docker)

1. Copy configuration:

   ```bash
   cp config.example.yaml config.yaml
   ```

2. Set SNMP community and paths in `config.yaml` (or `SNMP_COMMUNITY` env var).

3. Run discovery against the Arista (once, on a machine that can reach `172.21.100.2`):

   ```bash
   pip install -r requirements.txt
   python -m src.discover_arista --output arista_ports.yaml
   ```

   Merge the `arista.ports` section from `arista_ports.yaml` into `config.yaml`.

4. Start the stack:

   ```bash
   docker compose up --build
   ```

5. Open `http://localhost:8080/` on the touchscreen PC (or map host port 8080).

## Kiosk browser (Windows)

Launch Chromium/Edge in kiosk mode pointing at the monitor URL:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  --kiosk --app=http://localhost:8080/ `
  --window-size=1080,1920 `
  --disable-pinch
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Kiosk UI |
| `GET /api/status` | JSON status (switches + Stageracer) |
| `GET /health` | Liveness (SNMP poll freshness) |

## Configuration

See [config.example.yaml](config.example.yaml). Key fields:

- **arista.ports** — from discovery (`if_index`, `rx_sensor_index`)
- **ember.hosts** — `172.21.50.21` with fallback `.22`
- **thresholds.orange_dbm** — weak signal warning (default -18 dBm)

## Development (without Docker)

```bash
pip install -r requirements.txt
cd ember && npm install && cd ..
cp config.example.yaml config.yaml
mkdir -p data

# Terminal 1
node ember/poller.mjs

# Terminal 2
python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8080
```

## Logs

Watch live output (explains why the UI shows OK / Problem):

```bash
docker compose logs -f
```

More detail:

```bash
LOG_LEVEL=DEBUG docker compose up -d
docker compose logs -f
```

After each SNMP poll you should see a `=== Status summary ===` block with Arista reachability, each switch, and Stageracer trunk state.

## Tests

```bash
pytest tests/
```

## Portainer (recommended)

Deploy on a Linux host that can reach `172.21.x` (management VLAN). Docker Desktop on Windows often cannot reach those subnets even with `network_mode: host`; Portainer on the rack network works.

### Stack in Portainer (avoids “Dockerfile: no such file”)

The default [docker-compose.yml](docker-compose.yml) **pulls a pre-built image** — it does not run `docker build` on the server. That fixes Portainer’s common error when only the compose file is deployed (Web editor or raw GitHub URL).

1. On the Portainer host, create a folder (e.g. `/opt/ultritouch`) with:
   - `config.yaml` (from `config.example.yaml`, after Arista discovery)
   - empty `data/` directory
2. **Stacks** → **Add stack** → **Web editor** or **Repository**:
   - Paste or use repo `https://github.com/Broadcast-Rental/Ultritouch_Monitor`
   - Compose path: `docker-compose.yml`
3. If using **Repository**, set **Stack path** / working directory to the folder that contains `config.yaml` and `data/` (bind mounts use `./config.yaml` and `./data`).
4. Deploy. Image: `ghcr.io/broadcast-rental/ultritouch-monitor:latest` (built on each push to `main` via GitHub Actions).
5. If pull is denied, open the package on GitHub → **Package settings** → **Change visibility** → Public, or add a Portainer registry credential for `ghcr.io`.
6. Open `http://<server-ip>:8080/` on the kiosk PC.

Do **not** use a raw `raw.githubusercontent.com/.../docker-compose.yml` URL as the only source if the file still contains `build: .` — Portainer never receives the Dockerfile.

### Build on the server instead

Clone the repo on the host, add `config.yaml`, then:

```bash
docker compose -f docker-compose.build.yml up --build -d
```

`network_mode: host` is required so SNMP and Ember+ use the host routing table (not NAT). The UI listens on port **8080** on the host.

## Network notes

- [docker-compose.yml](docker-compose.yml) uses **`network_mode: host`** so SNMP/Ember+ use the same network as the Docker host (required for `172.21.x`).
- Kiosk URL: `http://<host>:8080/` (port is bound on the host, not mapped in compose).
- On Docker Desktop for Windows, containers often cannot ping `172.21.x` even with host mode; use Portainer on a server with VLAN access instead.
- Aruba v1: uplink **ifIndex 26** (`A1`) — link and error counters only (no DOM via SNMP).
- Arista: optical power via ENTITY-SENSOR-MIB; run discovery after hardware changes.
