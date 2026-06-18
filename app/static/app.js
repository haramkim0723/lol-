const POSITIONS = ["TOP", "JUG", "MID", "ADC", "SUP"];
const POSITION_NAMES = {
  TOP: "탑", JUG: "정글", MID: "미드", ADC: "원딜", SUP: "서폿",
};
const TIER_STYLES = {
  IRON: ["#82909e", "#b1bbc4", "#303944", "rgba(130,144,158,.22)"],
  BRONZE: ["#ad7049", "#d69a6d", "#4d2d20", "rgba(173,112,73,.24)"],
  SILVER: ["#a8bac8", "#e4edf2", "#4d6473", "rgba(168,186,200,.24)"],
  GOLD: ["#e2b84f", "#ffe49a", "#7b4e18", "rgba(226,184,79,.28)"],
  PLATINUM: ["#55d6c2", "#b7fff1", "#185e63", "rgba(85,214,194,.25)"],
  EMERALD: ["#3ddd82", "#b3ffd0", "#17643c", "rgba(61,221,130,.25)"],
  DIAMOND: ["#7aa9ff", "#d4e2ff", "#43458d", "rgba(122,169,255,.27)"],
  MASTER: ["#c879ef", "#f4c7ff", "#632d88", "rgba(200,121,239,.27)"],
  GRANDMASTER: ["#ff6677", "#ffc1c7", "#7e1c32", "rgba(255,102,119,.27)"],
  CHALLENGER: ["#68e6ff", "#e5fbff", "#7b651d", "rgba(104,230,255,.29)"],
  UNRANKED: ["#778493", "#aab5c2", "#303a46", "rgba(119,132,147,.18)"],
};

let state = null;
let currentView = "intro";
let loginRole = "spectator";
let toastTimer = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.className = "toast", 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "요청을 처리하지 못했습니다.");
  return data;
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function playerById(id) {
  return state.players.find((player) => player.id === id);
}

function captainById(id) {
  return state.captains.find((captain) => captain.id === id);
}

function tierKey(tier = "") {
  const upper = tier.toUpperCase();
  return Object.keys(TIER_STYLES).find((key) => upper.startsWith(key)) || "UNRANKED";
}

function positionOptions(optional = false) {
  return `${optional ? '<option value="">선택 안 함</option>' : ""}${POSITIONS.map(
    (position) => `<option value="${position}">${POSITION_NAMES[position]}</option>`
  ).join("")}`;
}

function setView(view) {
  if (view === "setup" && state.viewer.role !== "host") view = "intro";
  if (view === "auction" && state.auction.status === "setup") {
    toast("호스트가 아직 경매를 시작하지 않았습니다.");
    view = "intro";
  }
  currentView = view;
  $("#intro-panel").classList.toggle("hidden", view !== "intro");
  $("#setup-panel").classList.toggle("hidden", view !== "setup");
  $("#auction-panel").classList.toggle("hidden", view !== "auction");
  $$("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
}

function renderRole() {
  const viewer = state.viewer;
  $("#login-overlay").classList.toggle("hidden", viewer.authenticated);
  $("#main-nav").classList.toggle("hidden", !viewer.authenticated);
  $("#logout-button").classList.toggle("hidden", !viewer.authenticated);
  $("#setup-nav").classList.toggle("hidden", viewer.role !== "host");

  let label = "관전자";
  if (viewer.role === "host") label = "호스트";
  if (viewer.role === "captain") {
    label = `${captainById(viewer.captain_id)?.name || "팀장"} 팀`;
  }
  $("#role-badge").textContent = label;

  $("#login-captain").innerHTML = state.captains.length
    ? state.captains.map((captain) =>
      `<option value="${captain.id}">${escapeHtml(captain.name)}</option>`
    ).join("")
    : '<option value="">등록된 팀장이 없습니다</option>';
}

function renderIntro() {
  $("#intro-count").textContent = `${state.players.length} PLAYERS`;
  $("#intro-players").innerHTML = state.players.length
    ? state.players.map((player) => {
      const key = tierKey(player.tier);
      const [color, light, dark, glow] = TIER_STYLES[key];
      return `
        <article class="intro-player" style="--tier-color:${color};--tier-light:${light};--tier-dark:${dark};--tier-glow:${glow}">
          <div class="tier-emblem" data-tier="${key}"></div>
          <div class="intro-player-content">
            <h3>${escapeHtml(player.name)}</h3>
            <span class="riot-name">${escapeHtml(player.riot_id || "Riot ID 미등록")}</span>
            <div class="intro-tier">${escapeHtml(player.tier)}</div>
            <div class="intro-positions">
              <span class="pos">${player.primary_position} · ${POSITION_NAMES[player.primary_position]}</span>
              ${player.secondary_position ? `<span class="pos">${player.secondary_position} · ${POSITION_NAMES[player.secondary_position]}</span>` : ""}
            </div>
          </div>
        </article>`;
    }).join("")
    : '<div class="intro-empty">호스트가 참가자를 등록하면 이곳에 소개 카드가 나타납니다.</div>';
}

function renderSetup() {
  if (state.viewer.role !== "host") return;
  const settings = state.settings;
  const form = $("#settings-form");
  Object.entries(settings).forEach(([key, value]) => {
    if (form.elements[key]) form.elements[key].value = value;
  });

  $("#captain-setup-list").className = state.captains.length
    ? "captain-list" : "captain-list empty-message";
  $("#captain-setup-list").innerHTML = state.captains.length
    ? state.captains.map((captain) => `
      <div class="captain-row">
        <div class="captain-row-avatar">${escapeHtml(captain.name.slice(0, 1))}</div>
        <div class="captain-row-copy">
          <strong>${escapeHtml(captain.name)} 팀</strong>
          <small>${escapeHtml(playerById(captain.player_id)?.primary_position || "POSITION")} 자동 배치 · PIN 입장</small>
        </div>
        <div class="captain-budget">
          <strong>${captain.initial_budget.toLocaleString()} P</strong>
          <small>START BUDGET</small>
        </div>
        <button class="remove" data-delete-captain="${captain.id}">삭제</button>
      </div>`).join("")
    : `<div class="captain-empty-icon">♜</div>
       <strong>아직 등록된 팀장이 없습니다</strong>
       <span>참가자를 등록한 뒤 팀장과 시작 예산을 지정해 주세요.</span>`;

  const captainCandidates = state.players.filter(
    (player) => player.status === "waiting"
  );
  $("#captain-player").innerHTML = captainCandidates.length
    ? captainCandidates.map((player) =>
      `<option value="${player.id}">${escapeHtml(player.name)} · ${player.primary_position}</option>`
    ).join("")
    : '<option value="">먼저 참가자를 등록하세요</option>';
  updateCaptainPreview();

  $("#player-setup-list").className = state.players.length
    ? "player-cards" : "player-cards empty-message";
  $("#player-setup-list").innerHTML = state.players.length
    ? state.players.map((player) => `
      <div class="player-mini">
        ${player.profile_icon_url ? `<img src="${escapeHtml(player.profile_icon_url)}" alt="" />` : '<div class="avatar"></div>'}
        <div class="player-copy">
          <strong>${escapeHtml(player.name)}</strong>
          <small>${escapeHtml(player.tier)} · ${escapeHtml(player.riot_id || "Riot ID 없음")}</small>
        </div>
        <span class="pos">${player.status === "captain" ? "CAPTAIN · " : ""}${player.primary_position}</span>
        <button class="remove" data-delete-player="${player.id}">×</button>
      </div>`).join("")
    : "등록된 참가자가 없습니다.";
}

function updateCaptainPreview() {
  if (!state) return;
  const player = playerById($("#captain-player").value);
  $("#captain-preview-avatar").textContent = player ? player.name.slice(0, 1) : "?";
  $("#captain-preview-meta").textContent = player
    ? `${player.tier} · ${POSITION_NAMES[player.primary_position]} 자동 배치`
    : "참가자를 먼저 등록해 주세요.";
}

function renderAuction() {
  const auction = state.auction;
  $("#round-number").textContent = auction.round;
  const current = playerById(auction.current_player_id);
  $("#current-player").innerHTML = current ? `
    <div class="current-player-name">${escapeHtml(current.name)}</div>
    <div class="current-player-meta">
      <span>${escapeHtml(current.tier)}</span>
      <span class="pos">${current.primary_position}</span>
      ${current.secondary_position ? `<span class="pos">${current.secondary_position}</span>` : ""}
    </div>` : `<div class="current-player-name">${auction.status === "finished" ? "경매 종료" : "라운드 대기"}</div>`;

  $("#highest-bid").innerHTML = auction.highest_bid
    ? `<strong>${escapeHtml(auction.highest_bid.captain_name)}</strong> · ${auction.highest_bid.amount.toLocaleString()} P`
    : "아직 입찰이 없습니다";

  const viewerCaptain = captainById(state.viewer.captain_id);
  $("#bid-identity").textContent = viewerCaptain
    ? `${viewerCaptain.name} 팀 · 잔여 ${viewerCaptain.remaining_budget.toLocaleString()} P`
    : state.viewer.role === "host"
      ? "호스트는 진행만 관리하며 입찰하지 않습니다."
      : "팀장으로 입장하면 자기 팀으로 직접 입찰할 수 있습니다.";

  const required = auction.highest_bid
    ? auction.highest_bid.amount + state.settings.bid_increment
    : state.settings.minimum_bid;
  $("#bid-amount").min = required;
  if (!$("#bid-amount").value || Number($("#bid-amount").value) < required) {
    $("#bid-amount").value = required;
  }
  $("#bid-guide").textContent =
    `현재 최소 입찰: ${required.toLocaleString()} P · 마지막 ${state.settings.extension_trigger_seconds}초 입찰 시 ${state.settings.extension_seconds}초 연장`;

  const canBid = state.viewer.role === "captain" && auction.status === "running";
  $("#bid-form").querySelectorAll("input, button").forEach((element) => {
    element.disabled = !canBid;
  });
  $("#pause-button").classList.toggle(
    "hidden", state.viewer.role !== "host" || auction.status !== "running"
  );
  $("#resume-button").classList.toggle(
    "hidden", state.viewer.role !== "host" || auction.status !== "paused"
  );
  $("#reauction-button").classList.toggle(
    "hidden", state.viewer.role !== "host" || auction.status !== "waiting_reauction"
  );

  renderTeams();
  renderQueue();
  updateTimer();
}

function renderTeams() {
  $("#teams").innerHTML = state.captains.map((captain) => `
    <div class="team-card">
      <div class="team-head"><strong>${escapeHtml(captain.name)} 팀</strong><span class="budget">${captain.remaining_budget.toLocaleString()} P</span></div>
      ${POSITIONS.map((position) => {
        const player = playerById(captain.team[position]);
        return `<div class="roster-row"><span>${position}</span><span class="${player ? "" : "vacant"}">${player ? escapeHtml(player.name) : "비어 있음"}</span></div>`;
      }).join("")}
      ${captain.bench.map((id) => `<div class="roster-row"><span>ETC</span><span>${escapeHtml(playerById(id)?.name || "-")}</span></div>`).join("")}
    </div>`).join("");
}

function renderQueue() {
  $("#queue").innerHTML = state.auction.queue.length
    ? state.auction.queue.map((id, index) => {
      const player = playerById(id);
      return `<div class="queue-item"><span>${index + 1}. ${escapeHtml(player.name)}</span><span class="pos">${player.primary_position}</span></div>`;
    }).join("")
    : '<div class="empty-message">대기 중인 참가자가 없습니다.</div>';

  $("#unsold").innerHTML = state.auction.unsold.length
    ? state.auction.unsold.map((id) => {
      const player = playerById(id);
      return `<div class="queue-item"><span>${escapeHtml(player.name)} · ${player.unsold_count}회</span><span class="pos">${player.primary_position}</span></div>`;
    }).join("")
    : '<div class="empty-message">유찰자가 없습니다.</div>';
}

function updateTimer() {
  if (!state || state.auction.status === "setup") return;
  let remaining = state.auction.remaining_seconds;
  if (state.auction.status === "paused") remaining = state.auction.paused_remaining;
  const timer = $("#timer");
  if (remaining == null) {
    timer.textContent = state.auction.status === "waiting_reauction" ? "RE" : "--";
    timer.classList.remove("danger");
    return;
  }
  const elapsed = (Date.now() / 1000) - state.server_time;
  const seconds = Math.max(0, Math.ceil(
    remaining - (state.auction.status === "running" ? elapsed : 0)
  ));
  timer.textContent = String(seconds).padStart(2, "0");
  timer.classList.toggle("danger", seconds <= 5);
}

function render() {
  $("#room-title").textContent = state.settings.room_name;
  document.title = `${state.settings.room_name} · LoL Auction`;
  renderRole();
  renderIntro();
  renderSetup();
  renderAuction();
  if (state.viewer.role !== "host" && state.auction.status === "setup") {
    currentView = "intro";
  }
  setView(currentView);
}

function connectSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  socket.onopen = () => {
    $("#socket-dot").classList.add("online");
    $("#socket-text").textContent = "실시간 연결됨";
  };
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "state") {
      const previousStatus = state?.auction?.status;
      state = message.data;
      if (previousStatus === "setup" && state.auction.status === "running") {
        currentView = "auction";
      }
      render();
    }
  };
  socket.onclose = () => {
    $("#socket-dot").classList.remove("online");
    $("#socket-text").textContent = "재연결 중";
    setTimeout(connectSocket, 1500);
  };
}

$$(".position-select").forEach((select) => {
  select.innerHTML = positionOptions(select.classList.contains("optional"));
});

$$(".tab").forEach((button) => button.addEventListener("click", () => {
  $$(".tab").forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  $("#manual-player-form").classList.toggle("hidden", button.dataset.tab !== "manual");
  $("#riot-player-form").classList.toggle("hidden", button.dataset.tab !== "riot");
}));

$("#captain-player").addEventListener("change", updateCaptainPreview);

$$("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

$$(".login-tab").forEach((button) => button.addEventListener("click", () => {
  loginRole = button.dataset.loginRole;
  $$(".login-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
  $("#captain-login-fields").classList.toggle("hidden", loginRole !== "captain");
  $("#pin-login-field").classList.toggle("hidden", loginRole === "spectator");
  $("#login-submit").textContent =
    loginRole === "host" ? "호스트로 입장"
      : loginRole === "captain" ? "팀장으로 입장" : "관전자로 입장";
}));

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = {
    role: loginRole,
    pin: form.get("pin") || "",
    captain_id: loginRole === "captain" ? form.get("captain_id") : null,
  };
  try {
    await api("/api/login", { method: "POST", body: JSON.stringify(payload) });
    location.reload();
  } catch (error) {
    toast(error.message, true);
  }
});

$("#logout-button").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  Object.keys(data).filter((key) => key !== "room_name")
    .forEach((key) => data[key] = Number(data[key]));
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(data) });
    toast("경매 설정을 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#captain-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.budget = Number(data.budget);
  try {
    await api("/api/captains", { method: "POST", body: JSON.stringify(data) });
    event.target.reset();
  } catch (error) { toast(error.message, true); }
});

$("#manual-player-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.secondary_position ||= null;
  try {
    await api("/api/players", { method: "POST", body: JSON.stringify(data) });
    event.target.reset();
  } catch (error) { toast(error.message, true); }
});

$("#riot-player-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.secondary_position ||= null;
  const button = event.target.querySelector("button");
  button.disabled = true;
  button.textContent = "조회 중...";
  try {
    await api("/api/players/riot", { method: "POST", body: JSON.stringify(data) });
    event.target.reset();
    toast("Riot 정보를 확인해 추가했습니다.");
  } catch (error) { toast(error.message, true); }
  finally {
    button.disabled = false;
    button.textContent = "티어 조회 후 추가";
  }
});

document.addEventListener("click", async (event) => {
  const captainId = event.target.dataset.deleteCaptain;
  const playerId = event.target.dataset.deletePlayer;
  try {
    if (captainId) await api(`/api/captains/${captainId}`, { method: "DELETE" });
    if (playerId) await api(`/api/players/${playerId}`, { method: "DELETE" });
  } catch (error) { toast(error.message, true); }
});

$("#start-button").addEventListener("click", async () => {
  try {
    await api("/api/auction/start", { method: "POST" });
    currentView = "auction";
    toast("무작위 순서로 경매를 시작했습니다.");
  } catch (error) { toast(error.message, true); }
});
$("#pause-button").addEventListener("click", () =>
  api("/api/auction/pause", { method: "POST" }).catch((e) => toast(e.message, true)));
$("#resume-button").addEventListener("click", () =>
  api("/api/auction/resume", { method: "POST" }).catch((e) => toast(e.message, true)));
$("#reauction-button").addEventListener("click", () =>
  api("/api/auction/reauction", { method: "POST" }).catch((e) => toast(e.message, true)));

$("#bid-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = { amount: Number($("#bid-amount").value) };
  try {
    await api("/api/auction/bid", { method: "POST", body: JSON.stringify(data) });
  } catch (error) { toast(error.message, true); }
});

setInterval(updateTimer, 100);
api("/api/state").then((data) => {
  state = data;
  render();
});
connectSocket();
