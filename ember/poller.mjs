/**
 * Ember+ poller for Stageracer2 fiber status.
 * Writes JSON state for the Python API to read.
 */

import fs from "fs";
import net from "net";
import path from "path";
import { fileURLToPath } from "url";
import yaml from "yaml";
import emberplus from "node-emberplus";
const { EmberClient } = emberplus;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

function log(level, msg, ...args) {
  const ts = new Date().toISOString().replace("T", " ").slice(0, 19);
  console.log(`${ts} ${level} [ember] ${msg}`, ...args);
}

function loadConfig() {
  const configPath = process.env.CONFIG_PATH || path.join(ROOT, "config.yaml");
  if (!fs.existsSync(configPath)) {
    const example = path.join(ROOT, "config.example.yaml");
    return yaml.parse(fs.readFileSync(example, "utf8"));
  }
  return yaml.parse(fs.readFileSync(configPath, "utf8"));
}

function emberPath(root, srIndex, suffix) {
  return `${root}/${srIndex}/${suffix}`;
}

function tcpProbe(host, port, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const done = (ok) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
    socket.connect(port, host);
  });
}

function trunkSuffixes() {
  return [
    { id: 1, sync: 2100, lastError: 2101, power: 2103 },
    { id: 2, sync: 2200, lastError: 2201, power: 2203 },
    { id: 3, sync: 2300, lastError: 2301, power: 2303 },
    { id: 4, sync: 2400, lastError: 2401, power: 2403 },
  ];
}

function trunkStatus(sync, powerDbm, lastErrorSec, thresholds) {
  if (sync === 0 || sync === false) {
    return { status: "red", summary: "Trunk not locked" };
  }
  if (sync == null) {
    return { status: "gray", summary: "Unknown" };
  }
  if (lastErrorSec != null && lastErrorSec < thresholds.recent_error_seconds) {
    return { status: "orange", summary: "Recent glitch" };
  }
  if (powerDbm != null && powerDbm < thresholds.red_dbm) {
    return { status: "red", summary: "Low power" };
  }
  if (powerDbm != null && powerDbm < thresholds.orange_dbm) {
    return { status: "orange", summary: "Low power" };
  }
  return { status: "green", summary: "OK" };
}

async function readParameter(client, paramPath) {
  try {
    const node = await client.getElementByPathAsync(paramPath);
    if (!node) return null;
    const v = node.contents?.value ?? node.value;
    if (v == null) return null;
    if (typeof v === "object" && "value" in v) return v.value;
    return v;
  } catch {
    return null;
  }
}

async function nodeLabel(client, root, i) {
  try {
    const node = await client.getElementByPathAsync(`${root}/${i}`);
    if (!node) return null;
    const c = node.contents || node;
    const parts = [c.identifier, c.description, c.displayName, c.name, node.identifier, node.description]
      .filter((x) => x != null && String(x).trim() !== "")
      .map(String);
    if (parts.length) return [...new Set(parts)].join(" ");
    const param = await readParameter(client, `${root}/${i}`);
    return param != null ? String(param) : null;
  } catch {
    return null;
  }
}

async function discoverSrIndex(client, root, nameMatch) {
  const candidates = [];
  for (let i = 1; i <= 20; i++) {
    const label = await nodeLabel(client, root, i);
    if (!label) continue;
    candidates.push({ i, label });
    if (label.toUpperCase().includes(nameMatch.toUpperCase())) {
      return i;
    }
  }
  if (candidates.length) {
    log(
      "WARN",
      `No device matching "${nameMatch}" under ${root}. Children found: ` +
        candidates.map((c) => `${c.i}="${c.label}"`).join(", ")
    );
  } else {
    log("WARN", `No children under Ember path ${root} (expected e.g. ${root}/1, ${root}/2, …)`);
  }
  return null;
}

async function pollOnce(cfg) {
  const ember = cfg.ember || {};
  const hosts = ember.hosts || ["172.21.50.21", "172.21.50.22"];
  const port = ember.port || 9000;
  const root = ember.fiber_root || "997";
  const nameMatch = ember.sr2_name_match || "SR2";
  const stateFile = ember.state_file || "data/ember_state.json";
  const thresholds = cfg.thresholds || {
    orange_dbm: -18,
    red_dbm: -25,
    recent_error_seconds: 300,
  };

  const outPath = path.isAbsolute(stateFile)
    ? stateFile
    : path.join(ROOT, stateFile);

  let client = null;
  let connectedHost = null;

  for (const host of hosts) {
    const pingOk = await tcpProbe(host, port, 3000);
    log("INFO", `TCP probe ${host}:${port} => ${pingOk ? "open" : "closed/filtered"}`);
    if (!pingOk) {
      continue;
    }
    log("INFO", `Connecting Ember+ ${host}:${port}...`);
    const c = new EmberClient({ host, port });
    c.on?.("error", (err) => log("WARN", `Ember client error (${host}):`, err?.message || err));
    try {
      await c.connectAsync();
      client = c;
      connectedHost = host;
      log("INFO", `Connected to Stageracer at ${host}:${port}`);
      break;
    } catch (err) {
      log("WARN", `Failed ${host}:${port} —`, err?.message || err);
      try {
        await c.disconnectAsync?.();
      } catch {
        /* ignore */
      }
    }
  }

  if (!client) {
    log("WARN", `Cannot connect to any Ember+ host (${hosts.join(", ")})`);
    const offline = {
      online: false,
      host: null,
      name: null,
      message: "Cannot connect to Stageracer",
      trunks: [],
      updatedAt: new Date().toISOString(),
    };
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, JSON.stringify(offline, null, 2));
    return;
  }

  try {
    await client.getDirectoryAsync();
    const srIndex = await discoverSrIndex(client, root, nameMatch);
    if (!srIndex) {
      log("WARN", `No device matching "${nameMatch}" under Ember path ${root} on ${connectedHost}`);
      const state = {
        online: false,
        host: connectedHost,
        name: null,
        message: `No Stageracer matching "${nameMatch}" under ${root}`,
        trunks: [],
        updatedAt: new Date().toISOString(),
      };
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      fs.writeFileSync(outPath, JSON.stringify(state, null, 2));
      return;
    }

    const srName = await readParameter(client, `${root}/${srIndex}`);
    const trunks = [];

    for (const t of trunkSuffixes()) {
      const syncPath = emberPath(root, srIndex, t.sync);
      const errPath = emberPath(root, srIndex, t.lastError);
      const pwrPath = emberPath(root, srIndex, t.power);

      const syncRaw = await readParameter(client, syncPath);
      const errRaw = await readParameter(client, errPath);
      const pwrRaw = await readParameter(client, pwrPath);

      if (syncRaw == null && errRaw == null && pwrRaw == null) {
        continue;
      }

      const sync = syncRaw != null ? Number(syncRaw) : null;
      const lastErrorSec = errRaw != null ? Number(errRaw) : null;
      const powerDbm = pwrRaw != null ? Number(pwrRaw) : null;
      const { status, summary } = trunkStatus(sync, powerDbm, lastErrorSec, thresholds);

      trunks.push({
        id: t.id,
        sync: sync === 1,
        lastErrorSeconds: lastErrorSec,
        powerDbm,
        status,
        summary,
      });
    }

    const state = {
      online: true,
      host: connectedHost,
      index: srIndex,
      name: srName != null ? String(srName) : nameMatch,
      message: "OK",
      trunks,
      updatedAt: new Date().toISOString(),
    };
    fs.mkdirSync(path.dirname(outPath), { recursive: true });
    fs.writeFileSync(outPath, JSON.stringify(state, null, 2));
    log(
      "INFO",
      `Stageracer OK: ${state.name} index=${srIndex} trunks=${trunks.length} ` +
        trunks.map((t) => `T${t.id}=${t.status}`).join(" ")
    );
  } finally {
    try {
      await client.disconnectAsync();
    } catch {
      /* ignore */
    }
  }
}

process.on("uncaughtException", (err) => {
  log("ERROR", "uncaught:", err.message);
});
process.on("unhandledRejection", (err) => {
  log("ERROR", "unhandled:", err);
});

async function main() {
  const cfg = loadConfig();
  const intervalSec = (cfg.polling && cfg.polling.interval_seconds) || 15;

  log("INFO", `Ember+ poller started (interval ${intervalSec}s, hosts=${(cfg.ember?.hosts || []).join(",")})`);

  while (true) {
    try {
      await pollOnce(cfg);
    } catch (err) {
      log("ERROR", "Poll error:", err?.message || err);
      const stateFile = cfg.ember?.state_file || "data/ember_state.json";
      const outPath = path.isAbsolute(stateFile)
        ? stateFile
        : path.join(ROOT, stateFile);
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      fs.writeFileSync(
        outPath,
        JSON.stringify({
          online: false,
          message: String(err),
          trunks: [],
          updatedAt: new Date().toISOString(),
        }),
        "utf8"
      );
    }
    await new Promise((r) => setTimeout(r, intervalSec * 1000));
  }
}

main();
