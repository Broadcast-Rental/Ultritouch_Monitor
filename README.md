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

### Stack in Portainer

Use **Repository** (not Web editor alone). Portainer must clone the full repo so `docker build` can see the `Dockerfile`.

1. On the Portainer host, create e.g. `/opt/ultritouch/` with:
   - `config.yaml` (from `config.example.yaml`, after Arista discovery)
   - empty `data/` directory
2. **Stacks** → **Add stack** → **Repository**:
   - URL: `https://github.com/Broadcast-Rental/Ultritouch_Monitor`
   - Branch: `main`
   - Compose path: `docker-compose.yml`
3. In the stack **Environment variables**, set (paths on the Docker host):
   - `ULTRITOUCH_CONFIG=/opt/ultritouch/config.yaml`
   - `ULTRITOUCH_DATA=/opt/ultritouch/data`
4. Deploy (first deploy builds the image on the server; may take a few minutes).
5. Open `http://<server-ip>:8080/` on the kiosk PC.

**GHCR pull (`unauthorized`)** — the default compose no longer pulls from `ghcr.io`. To use the pre-built image instead, either make the package public (GitHub → **Packages** → `ultritouch-monitor` → **Package settings** → **Public**) and use [docker-compose.ghcr.yml](docker-compose.ghcr.yml), or add a Portainer registry for `ghcr.io` with a GitHub PAT (`read:packages`).

Do **not** deploy from a raw `raw.githubusercontent.com/.../docker-compose.yml` URL only — that omits the `Dockerfile`.

### Build on the server (SSH)

```bash
git clone https://github.com/Broadcast-Rental/Ultritouch_Monitor.git
cd Ultritouch_Monitor
cp config.example.yaml config.yaml   # edit + Arista discovery
docker compose up --build -d
```

`network_mode: host` is required so SNMP and Ember+ use the host routing table (not NAT). The UI listens on port **8080** on the host.

## Network notes

- [docker-compose.yml](docker-compose.yml) uses **`network_mode: host`** so SNMP/Ember+ use the same network as the Docker host (required for `172.21.x`).
- Kiosk URL: `http://<host>:8080/` (port is bound on the host, not mapped in compose).
- On Docker Desktop for Windows, containers often cannot ping `172.21.x` even with host mode; use Portainer on a server with VLAN access instead.
- Aruba v1: uplink **ifIndex 26** (`A1`) — link and error counters only (no DOM via SNMP).
- Arista: optical power via ENTITY-SENSOR-MIB; run discovery after hardware changes.
