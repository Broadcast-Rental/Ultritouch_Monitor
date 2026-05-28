const REFRESH_MS = 5000;

const STATUS_LABELS = {
  green: "All OK",
  orange: "Attention needed",
  red: "Problem",
  gray: "Unknown",
};

function formatTime(iso) {
  if (!iso) return "Never updated";
  try {
    const d = new Date(iso);
    return `Updated ${d.toLocaleTimeString()}`;
  } catch {
    return iso;
  }
}

function humanizeError(seconds) {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  return `${Math.round(seconds / 3600)} h ago`;
}

function renderHeader(data) {
  const header = document.getElementById("header");
  const overall = data.overallStatus || "gray";
  header.className = `header status-${overall}`;
  document.getElementById("overall-label").textContent = STATUS_LABELS[overall] || overall;
  document.getElementById("updated-at").textContent = formatTime(data.updatedAt);
}

function renderStageracer(sr) {
  const container = document.getElementById("sr-container");
  container.innerHTML = "";

  if (!sr || !sr.online) {
    const el = document.createElement("div");
    el.className = "offline-banner status-red";
    el.textContent = sr?.message || "Stageracer offline";
    container.appendChild(el);
    return;
  }

  const title = document.createElement("p");
  title.className = "trunk-details";
  title.textContent = sr.name ? `${sr.name} (${sr.host || ""})` : "Stageracer";
  container.appendChild(title);

  const trunks = sr.trunks || [];
  if (!trunks.length) {
    const el = document.createElement("div");
    el.className = "offline-banner";
    el.textContent = "No trunk data";
    container.appendChild(el);
    return;
  }

  trunks.forEach((t) => {
    const card = document.createElement("article");
    card.className = `trunk-card status-${t.status || "gray"}`;
    card.innerHTML = `
      <h3>Trunk ${t.id}</h3>
      <p class="trunk-summary">${t.summary || "—"}</p>
      <p class="trunk-details">
        Sync: ${t.sync ? "Yes" : "No"}
        &nbsp;|&nbsp; Power: ${t.powerDbm != null ? `${t.powerDbm.toFixed(1)} dBm` : "—"}
        &nbsp;|&nbsp; Last error: ${humanizeError(t.lastErrorSeconds)}
      </p>
    `;
    container.appendChild(card);
  });
}

function renderSwitches(switches) {
  const grid = document.getElementById("switch-grid");
  grid.innerHTML = "";

  if (!switches || !switches.length) {
    const el = document.createElement("div");
    el.className = "offline-banner";
    el.textContent = "No switches detected";
    grid.appendChild(el);
    return;
  }

  switches.forEach((sw) => {
    const tile = document.createElement("article");
    tile.className = `switch-tile status-${sw.status || "gray"}`;
    const rx = sw.arista?.rxDbm;
    const rxText = rx != null ? `${rx.toFixed(1)} dBm` : "—";
    const trend = sw.arista?.errorsIncreasing || sw.aruba?.errorsIncreasing ? " ↑ errors" : "";
    tile.innerHTML = `
      <p class="name">${sw.label || sw.ip}</p>
      <p class="summary">${sw.summary || sw.status}</p>
      <p class="meta">${sw.ip} · Rx ${rxText}${trend}</p>
    `;
    grid.appendChild(tile);
  });
}

async function refresh() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    renderHeader(data);
    renderStageracer(data.stageracer);
    renderSwitches(data.switches);
  } catch (err) {
    document.getElementById("overall-label").textContent = "Cannot reach monitor";
    console.error(err);
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
