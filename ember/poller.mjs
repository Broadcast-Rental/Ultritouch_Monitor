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

/** Stageracer paths use Ember numbers: 997.{srIndex}.{param} e.g. 997.1.2100 */
function emberPath(root, srIndex, suffix) {
  return `${root}.${srIndex}.${suffix}`;
}

function pathVariants(root, srIndex, suffix) {
  const r = String(root);
  const i = String(srIndex);
  const s = String(suffix);
  return [
    `${r}.${i}.${s}`,
    `${r}/${i}/${s}`,
    `0.${r}.${i}.${s}`,
  ];
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

function labelFromNode(node) {
  if (!node) return null;
  const c = node.contents || node;
  const parts = [c.identifier, c.description, c.displayName, c.name, node.identifier, node.description]
    .filter((x) => x != null && String(x).trim() !== "")
    .map(String);
  return parts.length ? [...new Set(parts)].join(" ") : null;
}

async function readParameter(client, paramPath) {
  const paths = Array.isArray(paramPath) ? paramPath : [paramPath];
  for (const p of paths) {
    try {
      const node = await client.getElementByPathAsync(p);
      if (!node) continue;
      const v = node.contents?.value ?? node.value;
      if (v == null) continue;
      if (typeof v === "object" && "value" in v) return v.value;
      return v;
    } catch {
      /* try next path form */
    }
  }
  return null;
}

async function getNode(client, pathStr) {
  try {
    return await client.getElementByPathAsync(pathStr);
  } catch {
    return null;
  }
}

async function expandFiberRoot(client, root) {
  const tries = [String(root), `0.${root}`, root.replace(/\//g, ".")];
  for (const p of tries) {
    const node = await getNode(client, p);
    if (!node) continue;
    try {
      await client.getDirectoryAsync(node);
    } catch {
      /* may already be expanded */
    }
    log("INFO", `Ember fiber root resolved at path "${p}"`);
    return p;
  }
  return String(root);
}

async function nodeLabel(client, root, i) {
  const paths = [`${root}.${i}`, `${root}/${i}`, `0.${root}.${i}`];
  for (const p of paths) {
    const node = await getNode(client, p);
    const label = labelFromNode(node);
    if (label) return label;
    const param = await readParameter(client, p);
    if (param != null) return String(param);
  }
  return null;
}

/** Find SR index by reading trunk 1 sync param (997.n.2100). */
async function discoverByTrunkProbe(client, root) {
  for (let i = 1; i <= 20; i++) {
    for (const p of pathVariants(root, i, 2100)) {
      const v = await readParameter(client, p);
      if (v != null) {
        log("INFO", `Stageracer trunk probe hit at ${p}`);
        return i;
      }
    }
  }
  return null;
}

function walkTree(node, depth = 0, maxDepth = 6, results = []) {
  if (!node || depth > maxDepth) return results;
  const label = labelFromNode(node);
  const nodePath =
    typeof node.getPath === "function"
      ? node.getPath()
      : node.path ?? node.contents?.path ?? null;
  if (label || nodePath) {
    results.push({ path: nodePath, label: label || "(no label)" });
  }
  const kids = node.children ?? node.contents?.children ?? [];
  for (const ch of kids) {
    walkTree(ch, depth + 1, maxDepth, results);
  }
  return results;
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

  const probed = await discoverByTrunkProbe(client, root);
  if (probed != null) {
    log("INFO", `Using Stageracer index ${probed} (trunk 2100 readable, name match skipped)`);
    return probed;
  }

  if (candidates.length === 1) {
    log("INFO", `Only one child under ${root}, using index ${candidates[0].i} (${candidates[0].label})`);
    return candidates[0].i;
  }

  if (candidates.length) {
    log(
      "WARN",
      `No device matching "${nameMatch}" under ${root}. Children found: ` +
        candidates.map((c) => `${c.i}="${c.label}"`).join(", ")
    );
  } else {
    const treeRoot = client.root ?? client.tree;
    if (treeRoot) {
      try {
        await client.getDirectoryAsync(treeRoot);
      } catch {
        /* ignore */
      }
      const sample = walkTree(treeRoot, 0, 4).slice(0, 40);
      if (sample.length) {
        log(
          "WARN",
          `No children at ${root}. Sample Ember tree (use Ember+ Viewer or set ember.fiber_root): ` +
            sample.map((n) => `${n.path || "?"}="${n.label}"`).join("; ")
        );
      } else {
        log("WARN", `No children under Ember path ${root} (tried ${root}.1, ${root}/1, …)`);
      }
    } else {
      log("WARN", `No children under Ember path ${root} (tried ${root}.1, ${root}/1, …)`);
    }
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
    const fiberRoot = await expandFiberRoot(client, root);
    const srIndex = await discoverSrIndex(client, fiberRoot, nameMatch);
    if (!srIndex) {
      log("WARN", `No device matching "${nameMatch}" under Ember path ${root} on ${connectedHost}`);
      const state = {
        online: false,
        host: connectedHost,
        name: null,
        message: `No Stageracer matching "${nameMatch}" under ${fiberRoot}`,
        trunks: [],
        updatedAt: new Date().toISOString(),
      };
      fs.mkdirSync(path.dirname(outPath), { recursive: true });
      fs.writeFileSync(outPath, JSON.stringify(state, null, 2));
      return;
    }

    const srName = await nodeLabel(client, fiberRoot, srIndex);
    const trunks = [];

    for (const t of trunkSuffixes()) {
      const syncRaw = await readParameter(client, pathVariants(fiberRoot, srIndex, t.sync));
      const errRaw = await readParameter(client, pathVariants(fiberRoot, srIndex, t.lastError));
      const pwrRaw = await readParameter(client, pathVariants(fiberRoot, srIndex, t.power));

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
