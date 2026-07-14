const POSITIONS = ["TOP", "JUG", "MID", "ADC", "SUP"];
const POSITION_NAMES = {
  TOP: "탑", JUG: "정글", MID: "미드", ADC: "원딜", SUP: "서폿",
};
const TIER_DIVISIONS = { 1: "I", 2: "II", 3: "III", 4: "IV" };
const DIVISION_TIERS = new Set([
  "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
]);
const DEFAULT_POSTER_IMAGE = "/static/season-26-2-poster.png";
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
let currentView = location.pathname === "/players"
  ? "intro"
  : location.pathname === "/score-players"
  ? "score-intro"
  : location.pathname === "/team-simulator"
  ? "team-simulator"
  : location.pathname === "/team-register"
    ? "team-register"
  : location.pathname === "/tournament"
    ? "tournament"
  : location.pathname === "/participation"
    ? "participation"
  : location.pathname === "/members"
    ? "members"
  : location.pathname === "/notices"
    ? "notices"
  : location.pathname === "/mypage"
    ? "mypage"
  : ["/competition-room", "/scrim"].includes(location.pathname)
    ? "scrim"
    : "poster";
let authPromptOpen = false;
let authMode = "login";
let introIndex = 0;
let introPlayerId = null;
let scoreIntroIndex = 0;
let scoreIntroPlayerId = null;
let toastTimer = null;
let stateSignature = "";
let scrimRoomTab = "progress";
let lastGroupDrawAnimationSignature = "";
let groupDrawReady = false;
let groupDrawRevealActive = false;
let groupDrawRevealCount = 0;
let riotPreviewData = null;
let rosterPage = 1;
let selectedScrimTeamId = null;
let pendingApiCount = 0;
let pollStateInFlight = false;
const STATE_POLL_INTERVAL_MS = 15000;
const STATE_POLL_VIEWS = new Set(["poster", "setup", "auction", "tournament", "scrim"]);
let simulatorExcludedSignature = "";
let participationHostView = "settings";
let participationApprovalView = "requests";
let participationApprovalStatus = "pending";
let participationApplicationsPromise = null;
let participationApplicationsSignature = "";
let bracketDraft = null;
let memberRosterCache = null;
let rosterCreateOpen = false;
const dirtyRosterIds = new Set();
const ROSTER_EDIT_FIELDS = [
  "name", "riot_id", "secondary_riot_id", "preferred_lines", "tier",
  "payment_status", "participation_status_text", "absence_reason",
  "top_adjustment", "game_count_adjustment", "notes", "score_top",
  "score_jungle", "score_mid", "score_adc", "score_support",
];

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message, error = false) {
  const node = $("#toast");
  node.textContent = message;
  node.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.className = "toast", 2600);
}

function setGlobalLoading(active, message = "처리 중...") {
  let node = $("#global-loading");
  if (!node) {
    node = document.createElement("div");
    node.id = "global-loading";
    node.className = "global-loading hidden";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    document.body.appendChild(node);
  }
  node.textContent = message;
  node.classList.toggle("hidden", !active);
}

function requestFailureMessage(error, fallback = "요청에 실패했습니다.") {
  const message = String(error?.message || "").trim();
  if (!message) return fallback;
  if (message === "Failed to fetch") return "서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.";
  if (message.includes("NetworkError")) return "네트워크 오류로 요청에 실패했습니다.";
  return message;
}

async function withButtonLoading(button, label, task) {
  if (!button) return task();
  const originalText = button.textContent;
  button.disabled = true;
  button.classList.add("loading");
  button.textContent = label;
  try {
    return await task();
  } catch (error) {
    button.textContent = "실패";
    throw error;
  } finally {
    setTimeout(() => {
      button.disabled = false;
      button.classList.remove("loading");
      button.textContent = originalText;
    }, 350);
  }
}

async function api(path, options = {}) {
  const { silent = false, ...fetchOptions } = options;
  if (!silent) {
    pendingApiCount += 1;
    setGlobalLoading(true);
  }
  try {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
      ...fetchOptions,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail || data.message || "";
      const statusMessage = response.status === 401
        ? "로그인이 필요하거나 아이디/비밀번호가 올바르지 않습니다."
        : response.status === 403
          ? "권한이 없어 요청에 실패했습니다."
          : response.status >= 500
            ? "서버 오류로 요청에 실패했습니다."
            : "요청 처리에 실패했습니다.";
      throw new Error(detail || statusMessage);
    }
    return data;
  } catch (error) {
    throw new Error(requestFailureMessage(error));
  } finally {
    if (!silent) {
      pendingApiCount = Math.max(0, pendingApiCount - 1);
      if (pendingApiCount === 0) setGlobalLoading(false);
    }
  }
}

async function refreshState({ renderView = true, silent = false } = {}) {
  const data = await api("/api/state", { silent });
  state = data;
  stateSignature = meaningfulStateSignature(state);
  if (renderView) render();
  return state;
}

function shouldPollState() {
  return STATE_POLL_VIEWS.has(currentView);
}

function readPosterImageInput(input) {
  const file = input?.files?.[0];
  if (!file) return Promise.resolve("");
  if (!file.type.startsWith("image/")) {
    return Promise.reject(new Error("포스터는 이미지 파일만 업로드할 수 있습니다."));
  }
  if (file.size > 3 * 1024 * 1024) {
    return Promise.reject(new Error("포스터 이미지는 3MB 이하로 업로드해 주세요."));
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("포스터 이미지를 읽지 못했습니다."));
    reader.readAsDataURL(file);
  });
}

window.addEventListener("unhandledrejection", (event) => {
  toast(`실패: ${requestFailureMessage(event.reason)}`, true);
});

window.addEventListener("error", (event) => {
  toast(`실패: ${requestFailureMessage(event.error || event.message, "화면 처리 중 오류가 발생했습니다.")}`, true);
});


function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function playerById(id) {
  return state.players.find((player) => player.id === id);
}

function registeredTournamentPlayerIds() {
  const ids = new Set();
  (state?.tournament?.teams || []).forEach((team) => {
    if (team.status === "rejected") return;
    POSITIONS.forEach((position) => {
      const playerId = team.members?.[position];
      if (playerId) ids.add(playerId);
    });
  });
  return ids;
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

function updateManualTierDivision() {
  const tier = $("#manual-tier").value;
  const slider = $("#manual-tier-division");
  const output = $("#manual-tier-division-output");
  const usesDivision = DIVISION_TIERS.has(tier);
  slider.disabled = !usesDivision;
  output.textContent = usesDivision ? `${slider.value} · ${TIER_DIVISIONS[slider.value]}` : "선택 안 함";
  $(".tier-division-field").classList.toggle("disabled", !usesDivision);
}

function updateSecondaryScoreField(form) {
  const secondaryPosition = form.elements.secondary_position?.value;
  const input = form.elements.secondary_score;
  const field = form.querySelector(".secondary-score-field");
  if (!field || !input) return;
  input.disabled = !secondaryPosition;
  field.classList.toggle("selected", Boolean(secondaryPosition));
  field.title = secondaryPosition
    ? `${POSITION_NAMES[secondaryPosition]} 배치 시 이 점수를 사용합니다.`
    : "부 포지션을 선택하면 이 점수를 사용합니다.";
}

function playerPositions(player) {
  return [
    player?.primary_position,
    player?.secondary_position,
    ...(player?.extra_positions || []),
  ].filter(Boolean);
}

function playerCanPosition(player, position) {
  return playerPositions(player).includes(position);
}

function scoreForPosition(player, position) {
  if (player?.position_scores?.[position] !== undefined && player.position_scores[position] !== "") {
    return Number(player.position_scores[position] || 0);
  }
  if (player?.primary_position !== position && playerCanPosition(player, position)) {
    return Number(player.secondary_score ?? player.score ?? 0);
  }
  return Number(player?.score || 0);
}


function setupPositionSlots(form) {
  if (!form || form.dataset.positionSlotsReady === "1") return;
  form.dataset.positionSlotsReady = "1";
  const primary = form.elements.primary_position;
  const secondary = form.elements.secondary_position;
  if (!primary || !secondary) return;
  const slots = [
    { select: primary, label: "포지션 1" },
    { select: secondary, label: "포지션 2" },
  ];
  for (let index = 3; index <= 4; index += 1) {
    const label = document.createElement("label");
    label.className = "position-slot hidden";
    label.textContent = `포지션 ${index}`;
    const select = document.createElement("select");
    select.name = "extra_position";
    select.className = "position-select optional";
    select.innerHTML = positionOptions(true);
    label.appendChild(select);
    secondary.closest("label").after(label);
    slots.push({ select, label: `포지션 ${index}` });
  }
  slots.forEach((slot, index) => {
    const label = slot.select.closest("label");
    label.classList.add("position-slot");
    label.dataset.positionSlot = String(index + 1);
    const textNode = [...label.childNodes].find((node) => node.nodeType === Node.TEXT_NODE);
    if (textNode) textNode.textContent = slot.label;
    if (index > 0) label.classList.add("hidden");
  });
  const actions = document.createElement("div");
  actions.className = "position-slot-actions";
  actions.innerHTML = '<button class="ghost add-position-button" type="button">+ 포지션 추가</button><small>최대 4개까지 선택</small>';
  slots.at(-1).select.closest("label").after(actions);
  const addButton = actions.querySelector("button");
  const refresh = () => {
    const hidden = slots
      .map((slot) => slot.select.closest("label"))
      .filter((label) => label.classList.contains("hidden"));
    addButton.disabled = hidden.length === 0;
  };
  addButton.addEventListener("click", () => {
    const next = slots
      .map((slot) => slot.select.closest("label"))
      .find((label) => label.classList.contains("hidden"));
    if (next) next.classList.remove("hidden");
    refresh();
  });
  refresh();
}

function collectPlayerFormData(form) {
  const data = Object.fromEntries(new FormData(form));
  const positions = [...form.querySelectorAll(".position-slot:not(.hidden) select")]
    .map((select) => select.value)
    .filter(Boolean)
    .filter((position, index, items) => items.indexOf(position) === index)
    .slice(0, 4);
  data.primary_position = positions[0] || data.primary_position;
  data.secondary_position = positions[1] || null;
  data.extra_positions = positions.slice(2);
  data.preferred_lines = positions.join(",");
  return data;
}

function resetPositionSlots(form) {
  form.querySelectorAll(".position-slot").forEach((label, index) => {
    label.classList.toggle("hidden", index > 0);
    const select = label.querySelector("select");
    if (select) select.value = index === 0 ? select.value || "TOP" : "";
  });
  const button = form.querySelector(".add-position-button");
  if (button) button.disabled = false;
}


function setView(view) {
  if (view === "setup" && state.viewer.role !== "host") {
    view = "poster";
  }
  if (view === "auction" && state.auction.status === "setup") {
    toast("강사님이 아직 이 대회의 경매를 열지 않았습니다.");
    view = "poster";
  }
  currentView = view;
  $("#poster-panel").classList.toggle("hidden", view !== "poster");
  $("#intro-panel").classList.toggle("hidden", view !== "intro");
  $("#setup-panel").classList.toggle("hidden", view !== "setup");
  $("#score-intro-panel").classList.toggle("hidden", view !== "score-intro");
  $("#team-simulator-panel").classList.toggle("hidden", view !== "team-simulator");
  $("#team-register-panel").classList.toggle("hidden", view !== "team-register");
  $("#tournament-panel").classList.toggle("hidden", view !== "tournament");
  $("#participation-panel").classList.toggle("hidden", view !== "participation");
  $("#notices-panel").classList.toggle("hidden", view !== "notices");
  $("#members-panel").classList.toggle("hidden", view !== "members");
  $("#mypage-panel").classList.toggle("hidden", view !== "mypage");
  $("#auction-panel").classList.toggle("hidden", view !== "auction");
  $("#scrim-panel").classList.toggle("hidden", view !== "scrim");
  $$("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  const path = view === "team-simulator" ? "/team-simulator"
    : view === "score-intro" ? "/score-players"
    : view === "team-register" ? "/team-register"
    : view === "tournament" ? "/tournament"
    : view === "participation" ? "/participation"
    : view === "notices" ? "/notices"
    : view === "members" ? "/members"
    : view === "mypage" ? "/mypage"
    : view === "scrim" ? "/competition-room"
    : view === "intro" ? "/players"
    : "/";
  if (location.pathname !== path) {
    history.pushState({ view }, "", path);
  }
  if (view === "scrim") loadScrimData();
  if (view === "members") {
    movePlayerRegistrationToMembers();
    loadMembers();
    if (state.viewer.role === "host") searchScrimUsers("");
  }
}

function navigateView(view) {
  setView(view);
  renderCurrentView();
}

function renderScrimRoomTabs() {
  if (scrimRoomTab === "results") scrimRoomTab = "stats";
  $$("[data-scrim-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.scrimTab === scrimRoomTab);
  });
  $$("[data-scrim-tab-panel]").forEach((panel) => {
    const tabs = String(panel.dataset.scrimTabPanel || "").split(/\s+/);
    panel.classList.toggle("scrim-tab-collapsed", !tabs.includes(scrimRoomTab));
  });
}

function movePlayerRegistrationToMembers() {
  const slot = $("#member-player-registration-slot");
  const panel = $(".players-panel");
  if (slot && panel && !slot.contains(panel)) {
    const wrapper = document.createElement("details");
    wrapper.className = "member-toolbox";
    wrapper.innerHTML = '<summary><span>03</span><strong>회원 관리 도구</strong><small>Riot API 조회와 점수 검색</small></summary>';
    wrapper.appendChild(panel);
    slot.appendChild(wrapper);
  }
  if (!panel) return;
  const title = panel.querySelector(".panel-title h2");
  if (title) title.textContent = "회원 관리";
  const manualTab = panel.querySelector('[data-tab="manual"]');
  if (manualTab) manualTab.textContent = "검색";
  const riotTab = panel.querySelector('[data-tab="riot"]');
  if (riotTab) riotTab.textContent = "Riot API 조회";
  const manualButton = panel.querySelector("#manual-player-form button[type='submit']");
  if (manualButton) manualButton.textContent = "검색";
  const riotButton = panel.querySelector("#riot-player-form button[type='submit']");
  if (riotButton) riotButton.textContent = "Riot API 조회";
}


function renderScoreTableEditor() {
  const container = $("#score-table-rows");
  if (!container) return;
  const rows = state.roster_score_table || [];
  container.innerHTML = rows.map((row, index) => `
    <div class="score-table-row" data-score-row="${index}">
      <input name="tier_key" value="${escapeHtml(row.tier_key || "")}" aria-label="tier key" />
      <input name="top" type="number" step="0.1" min="0" max="200" value="${Number(row.top ?? 0)}" aria-label="top score" />
      <input name="jungle" type="number" step="0.1" min="0" max="200" value="${Number(row.jungle ?? 0)}" aria-label="jungle score" />
      <input name="mid" type="number" step="0.1" min="0" max="200" value="${Number(row.mid ?? 0)}" aria-label="mid score" />
      <input name="adc" type="number" step="0.1" min="0" max="200" value="${Number(row.adc ?? 0)}" aria-label="adc score" />
      <input name="support" type="number" step="0.1" min="0" max="200" value="${Number(row.support ?? 0)}" aria-label="support score" />
    </div>
  `).join("");
}

async function enterAuctionView() {
  if (state.auction.status === "setup") {
    if (state.viewer.role !== "host") {
      toast("강사님이 아직 이 대회의 경매를 열지 않았습니다.");
      return;
    }
    try {
      await api("/api/auction/start", { method: "POST" });
      await refreshState();
      toast("현재 대회의 경매장을 열었습니다. 첫 후보의 타이머를 시작해 주세요.");
    } catch (error) {
      toast(error.message, true);
      return;
    }
  }
  currentView = "auction";
  setView("auction");
}

function renderRole() {
  const viewer = state.viewer;
  const participationEnabled = Boolean(state.participation?.enabled);
  const browsable = viewer.authenticated;
  const showLoginOverlay = !viewer.authenticated || authPromptOpen;
  $("#login-overlay").classList.toggle("hidden", !showLoginOverlay);
  $("#main-nav").classList.toggle("hidden", !browsable);
  $("#login-button").classList.toggle("hidden", viewer.authenticated || showLoginOverlay);
  $("#logout-button").classList.toggle("hidden", !viewer.authenticated);
  $("#setup-nav").classList.toggle("hidden", viewer.role !== "host");
  $("#admin-panel").classList.toggle("hidden", viewer.role !== "host");
  $$('[data-view="members"]').forEach((button) =>
    button.classList.toggle("hidden", viewer.role !== "host")
  );
  $$('[data-view="participation"]').forEach((button) =>
    button.classList.toggle("hidden", !viewer.authenticated)
  );
  $$('[data-view="mypage"]').forEach((button) =>
    button.classList.toggle("hidden", !viewer.authenticated)
  );
  $$('[data-view="notices"]').forEach((button) =>
    button.classList.toggle("hidden", !viewer.authenticated)
  );
  $("#competition-switcher").classList.toggle("hidden", !browsable);

  let label = "관리자";
  if (viewer.role === "host") label = "강사님";
  if (viewer.role === "participant") label = "참가자";
  if (viewer.role === "captain") {
    label = `${captainById(viewer.captain_id)?.name || "팀"} 팀`;
  }
  $("#role-badge").textContent = label;
}


function renderCompetitions() {
  const registry = state.competition_registry;
  if (!registry) return;
  const activeId = registry.active_competition_id;
  $("#active-competition-select").innerHTML = registry.competitions.map(
    (competition) =>
      `<option value="${competition.id}" ${competition.id === activeId ? "selected" : ""}>${escapeHtml(competition.name)}</option>`
  ).join("");
  $("#active-competition-select").disabled = state.viewer.role !== "host";
  if (state.viewer.role !== "host") return;
  $("#competition-list").innerHTML = registry.competitions.map(
    (competition) => `
      <article class="competition-item${competition.id === activeId ? " active" : ""}">
        <div>
          <strong>${escapeHtml(competition.name)}</strong>
          <label class="competition-name-edit">
            <span>이름 수정</span>
            <input value="${escapeHtml(competition.name)}" maxlength="50" data-competition-name-input="${competition.id}" />
          </label>
          <small>${competition.mode === "auction" ? "경매 대회" : "점수제 대회"} · 참가자 ${competition.player_count}명 · 팀 ${competition.team_count}개</small>
        </div>
        <div class="competition-actions">
          <button class="ghost" type="button" data-competition-rename="${competition.id}">저장</button>
          ${competition.id !== activeId ? `<button class="ghost" type="button" data-competition-select="${competition.id}">선택</button>` : ""}
          <button class="remove" type="button" data-competition-delete="${competition.id}" data-competition-name="${escapeHtml(competition.name)}">삭제</button>
        </div>
      </article>`
  ).join("");
}

function activeCompetition() {
  const registry = state.competition_registry;
  return registry?.competitions.find(
    (competition) => competition.id === registry.active_competition_id
  );
}

function mainViewForCompetition() {
  return "poster";
}

function renderMainPoster() {
  const source = activeCompetition()?.poster_image || DEFAULT_POSTER_IMAGE;
  $$(".main-poster-image").forEach((image) => {
    if (image.getAttribute("src") !== source) {
      image.src = source;
    }
    image.onerror = () => {
      if (image.getAttribute("src") !== DEFAULT_POSTER_IMAGE) {
        image.src = DEFAULT_POSTER_IMAGE;
      }
    };
  });
}

function applyCompetitionMode() {
  const isAuction = (activeCompetition()?.mode || "auction") === "auction";
  const scoreVisible = Boolean(state.participation?.score_visible) || state.viewer.role === "host";
  $$('[data-view="poster"]').forEach((button) => {
    button.classList.remove("hidden");
  });
  $$('[data-view="intro"], [data-view="auction"]').forEach((button) => {
    button.classList.toggle("hidden", !isAuction);
  });
  $$('[data-view="score-intro"], [data-view="team-simulator"], [data-view="team-register"], [data-view="tournament"]').forEach((button) => {
    button.classList.toggle("hidden", isAuction || !scoreVisible);
  });
  $$('[data-view="members"]').forEach((button) => {
    button.classList.toggle("hidden", state.viewer.role !== "host");
  });
  $$('[data-view="participation"]').forEach((button) => {
    button.classList.toggle(
      "hidden",
      isAuction || !state.viewer.authenticated
    );
  });
  $$('[data-view="mypage"]').forEach((button) => {
    button.classList.toggle("hidden", !state.viewer.authenticated);
  });
  $(".tournament-score-settings").classList.toggle("hidden", isAuction);
  $(".settings-panel").classList.toggle("hidden", !isAuction);
  $(".captain-panel").classList.toggle("hidden", !isAuction);

  const allowedViews = isAuction
    ? [
      "intro",
      "poster",
      "setup",
      "auction",
      "notices",
      "scrim",
      ...(state.viewer.role === "host" ? ["members"] : []),
      "mypage",
    ]
    : [
      "setup",
      "poster",
      ...(scoreVisible ? ["score-intro", "team-simulator", "team-register", "tournament"] : []),
      ...(state.viewer.authenticated ? ["participation"] : []),
      "notices",
      "scrim",
      ...(state.viewer.role === "host" ? ["members"] : []),
      "mypage",
    ];
  if (!allowedViews.includes(currentView)) {
    currentView = mainViewForCompetition();
  }
}

function renderScoreIntro() {
  const players = sortedIntroPlayers();
  $("#score-intro-count").textContent = `${players.length} PLAYERS`;
  if (!players.length) {
    $("#score-intro-player").innerHTML =
      '<div class="intro-empty">점수제 참가자가 아직 없습니다.</div>';
    $("#score-intro-position-nav").innerHTML = "";
    $("#score-intro-progress").innerHTML = "";
    $("#score-intro-prev").disabled = true;
    $("#score-intro-next").disabled = true;
    return;
  }
  const preserved = players.findIndex(
    (player) => player.id === scoreIntroPlayerId
  );
  if (preserved >= 0) scoreIntroIndex = preserved;
  scoreIntroIndex = Math.min(
    Math.max(scoreIntroIndex, 0), players.length - 1
  );
  const player = players[scoreIntroIndex];
  scoreIntroPlayerId = player.id;
  const key = tierKey(player.tier);
  const [color, light, dark, glow] = TIER_STYLES[key];
  $("#score-intro-player").innerHTML = `
    <article class="intro-player" data-position="${player.primary_position}" style="--tier-color:${color};--tier-light:${light};--tier-dark:${dark};--tier-glow:${glow}">
      <div class="intro-visual"><div class="tier-emblem" data-tier="${key}"></div></div>
      <div class="intro-player-content">
        <div class="intro-index">${String(scoreIntroIndex + 1).padStart(2, "0")} / ${String(players.length).padStart(2, "0")} · ${POSITION_NAMES[player.primary_position]}</div>
        <h3>${escapeHtml(player.name)}</h3>
        <span class="riot-name">${escapeHtml(player.riot_id || "Riot ID 미등록")}</span>
        <div class="intro-tier">${escapeHtml(player.tier)}</div>
        <div class="showcase-score"><strong>${Number(player.score || 0)}</strong><span>SCORE POINT</span></div>
        <div class="intro-positions">
          <span class="pos">${player.primary_position} · ${POSITION_NAMES[player.primary_position]}</span>
          ${player.secondary_position ? `<span class="pos">${player.secondary_position} · ${POSITION_NAMES[player.secondary_position]}</span>` : ""}
        </div>
      </div>
    </article>`;
  $("#score-intro-position-nav").innerHTML = POSITIONS.map((position) => {
    const count = players.filter((item) => item.primary_position === position).length;
    return `<button class="intro-position-button${player.primary_position === position ? " active" : ""}" type="button" data-score-intro-position="${position}" ${count ? "" : "disabled"}>${POSITION_NAMES[position]} <span>${count}</span></button>`;
  }).join("");
  $("#score-intro-progress").innerHTML = introProgressMarkup(scoreIntroIndex, players.length);
  $("#score-intro-prev").disabled = scoreIntroIndex === 0;
  $("#score-intro-next").disabled = scoreIntroIndex === players.length - 1;
}

function moveScoreIntro(direction) {
  const players = sortedIntroPlayers();
  scoreIntroIndex = Math.min(
    Math.max(scoreIntroIndex + direction, 0), players.length - 1
  );
  scoreIntroPlayerId = players[scoreIntroIndex]?.id || null;
  renderScoreIntro();
}

function renderIntro() {
  const players = sortedIntroPlayers();
  $("#intro-count").textContent = `${players.length} PLAYERS`;
  if (!players.length) {
    introIndex = 0;
    introPlayerId = null;
    $("#intro-players").innerHTML =
      '<div class="intro-empty">강사님이 참가자를 등록하면 이곳에 소개 카드가 나타납니다.</div>';
    $("#intro-position-nav").innerHTML = "";
    $("#intro-progress").innerHTML = "";
    $("#intro-prev").disabled = true;
    $("#intro-next").disabled = true;
    return;
  }

  const preservedIndex = players.findIndex((player) => player.id === introPlayerId);
  if (preservedIndex >= 0) introIndex = preservedIndex;
  introIndex = Math.min(Math.max(introIndex, 0), players.length - 1);
  const player = players[introIndex];
  introPlayerId = player.id;
  const key = tierKey(player.tier);
  const [color, light, dark, glow] = TIER_STYLES[key];

  $("#intro-players").innerHTML = `
    <article class="intro-player" data-position="${player.primary_position}" style="--tier-color:${color};--tier-light:${light};--tier-dark:${dark};--tier-glow:${glow}">
      <div class="intro-visual">
        <div class="tier-emblem" data-tier="${key}"></div>
      </div>
      <div class="intro-player-content">
        <div class="intro-index">${String(introIndex + 1).padStart(2, "0")} / ${String(players.length).padStart(2, "0")} · ${POSITION_NAMES[player.primary_position]}</div>
        <h3>${escapeHtml(player.name)}</h3>
        <span class="riot-name">${escapeHtml(player.riot_id || "Riot ID 미등록")}</span>
        <div class="intro-tier">${escapeHtml(player.tier)}</div>
        <div class="intro-positions">
          <span class="pos">${player.primary_position} · ${POSITION_NAMES[player.primary_position]}</span>
          ${player.secondary_position ? `<span class="pos">${player.secondary_position} · ${POSITION_NAMES[player.secondary_position]}</span>` : ""}
          ${player.status === "captain" ? '<span class="pos">CAPTAIN</span>' : ""}
        </div>
      </div>
    </article>`;

  $("#intro-position-nav").innerHTML = POSITIONS.map((position) => {
    const count = players.filter((item) => item.primary_position === position).length;
    return `<button class="intro-position-button${player.primary_position === position ? " active" : ""}" type="button" data-intro-position="${position}" ${count ? "" : "disabled"}>
      ${POSITION_NAMES[position]} <span>${count}</span>
    </button>`;
  }).join("");
  $("#intro-progress").innerHTML = introProgressMarkup(introIndex, players.length);
  $("#intro-prev").disabled = introIndex === 0;
  $("#intro-next").disabled = introIndex === players.length - 1;
}

function introProgressMarkup(index, total) {
  const progress = total > 1 ? index / (total - 1) * 100 : 100;
  return `
    <div class="intro-progress-track" aria-hidden="true">
      <span style="width:${Math.max(0, Math.min(100, progress))}%"></span>
    </div>
    <strong>${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}</strong>
  `;
}

function sortedIntroPlayers() {
  return [...state.players].sort((left, right) => {
    const positionDifference =
      POSITIONS.indexOf(left.primary_position) - POSITIONS.indexOf(right.primary_position);
    if (positionDifference !== 0) return positionDifference;
    return left.name.localeCompare(right.name, "ko-KR", {
      sensitivity: "base",
      numeric: true,
    });
  });
}

function normalizedSearch(value = "") {
  return value.trim().toLocaleLowerCase("ko-KR").replace(/\s+/g, "");
}

function matchingIntroPlayers(query) {
  const needle = normalizedSearch(query);
  if (!needle) return [];
  return sortedIntroPlayers().filter((player) =>
    [player.name, player.riot_id].some((value) =>
      normalizedSearch(value).includes(needle)
    )
  ).slice(0, 8);
}

function renderPlayerSearch(inputSelector, resultsSelector, view) {
  const input = $(inputSelector);
  const results = $(resultsSelector);
  const matches = matchingIntroPlayers(input.value);
  results.classList.toggle("hidden", !input.value.trim());
  results.innerHTML = matches.length
    ? matches.map((player) => `
      <button type="button" data-player-search-id="${player.id}" data-player-search-view="${view}">
        <strong>${escapeHtml(player.name)}</strong>
        <span>${escapeHtml(player.riot_id || "Riot ID 미등록")} · ${POSITION_NAMES[player.primary_position]}</span>
      </button>`).join("")
    : '<div class="player-search-empty">일치하는 참가자가 없습니다.</div>';
}

function selectSearchedPlayer(playerId, view) {
  const players = sortedIntroPlayers();
  const index = players.findIndex((player) => player.id === playerId);
  if (index < 0) return;
  if (view === "score-intro") {
    scoreIntroIndex = index;
    scoreIntroPlayerId = playerId;
    $("#score-intro-search-results").classList.add("hidden");
    renderScoreIntro();
  } else {
    introIndex = index;
    introPlayerId = playerId;
    $("#intro-search-results").classList.add("hidden");
    renderIntro();
  }
}

function moveIntro(direction) {
  const players = sortedIntroPlayers();
  introIndex = Math.min(Math.max(introIndex + direction, 0), players.length - 1);
  introPlayerId = players[introIndex]?.id || null;
  renderIntro();
  renderScoreIntro();
}

function updateScoreVisibleControl() {
  const input = $("#tournament-score-visible-input");
  const label = $("#tournament-score-visible-label");
  if (!input || !label) return;
  const visible = Boolean(state.participation?.score_visible);
  input.checked = visible;
  label.textContent = visible ? "공개 중" : "비공개";
}

function renderSetup() {
  if (state.viewer.role !== "host") return;
  $("#teacher-score-limit-input").value = state.tournament.score_limit;
  updateScoreVisibleControl();
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
          <small>${escapeHtml(playerById(captain.player_id)?.primary_position || "POSITION")} 자동 배치 · 계정 로그인</small>
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
          <small>${escapeHtml(player.riot_id || "Riot ID 없음")}</small>
          <div class="player-meta-badges">
            <span class="tier-badge">${escapeHtml(player.tier)}</span>
            <span class="pos primary-score-badge">${player.status === "captain" ? "CAPTAIN · " : ""}주 ${player.primary_position} · ${Number(player.score || 0)}점</span>
            ${player.secondary_position ? `<span class="pos secondary-score-badge">부 ${player.secondary_position} · ${Number(player.secondary_score ?? player.score ?? 0)}점</span>` : ""}
          </div>
        </div>
        <div class="player-score-control">
          <span class="score-player-label">${escapeHtml(player.name)} · 포지션별 점수</span>
          <div class="score-input-row">
            <label class="player-score-editor">
              <input data-player-score="${player.id}" type="number" min="0" max="1000" value="${Number(player.score || 0)}" aria-label="${escapeHtml(player.name)} 주 포지션 점수" />
              <span>주 ${player.primary_position}</span>
            </label>
            ${player.secondary_position ? `<label class="player-score-editor">
              <input data-player-secondary-score="${player.id}" type="number" min="0" max="1000" value="${Number(player.secondary_score ?? player.score ?? 0)}" aria-label="${escapeHtml(player.name)} 부 포지션 점수" />
              <span>부 ${player.secondary_position}</span>
            </label>` : ""}
            <button class="score-save" type="button" data-save-player-score="${player.id}">점수 저장</button>
          </div>
        </div>
        <button class="remove" data-delete-player="${player.id}">×</button>
      </div>`).join("")
    : "등록된 참가자가 없습니다.";
}

function renderTournament() {
  const tournament = state.tournament;
  const isHost = state.viewer.role === "host";
  const isTournamentCompetition = activeCompetition()?.mode === "tournament";
  const registrationOpen = tournament.status === "registration";
  $("#competition-progress-panel").classList.toggle("hidden", !isTournamentCompetition);
  $("#tournament-status").textContent =
    tournament.status === "registration" ? "TEAM REGISTRATION"
      : tournament.status === "group" ? "GROUP STAGE"
      : tournament.status === "running" ? "TOURNAMENT LIVE" : "TOURNAMENT FINISHED";
  $("#tournament-team-form").classList.toggle("hidden", !registrationOpen);
  $("#team-registration-closed").classList.toggle("hidden", registrationOpen);
  $("#tournament-registration-area").classList.toggle("hidden", !registrationOpen);
  $("#team-registration-closed-tournament").classList.toggle("hidden", registrationOpen);
  $("#tournament-bracket-section").classList.toggle(
    "hidden", !isTournamentCompetition || !["running", "finished"].includes(tournament.status)
  );
  $("#tournament-group-section").classList.toggle(
    "hidden", !isTournamentCompetition || (tournament.status !== "group" && !groupDrawReady)
  );
  $("#teacher-score-limit-input").value = tournament.score_limit;
  updateScoreVisibleControl();
  $("#tournament-format-input").value = tournament.format || "single_elimination";
  $("#tournament-group-count-input").value = tournament.group_count || 2;
  $("#tournament-qualifiers-input").value = tournament.qualifiers_per_group || 2;
  const settingsLocked = ["running", "finished"].includes(tournament.status);
  ["#teacher-score-limit-input", "#tournament-score-visible-input", "#tournament-format-input", "#tournament-group-count-input", "#tournament-qualifiers-input", "#save-tournament-settings"]
    .forEach((selector) => { $(selector).disabled = settingsLocked; });
  $("#start-tournament-button").classList.toggle(
    "hidden", !registrationOpen || !isHost || tournament.format !== "group_then_knockout"
  );
  $("#open-bracket-editor-button").classList.toggle(
    "hidden",
    !isTournamentCompetition
      || !isHost
      || tournament.teams.filter((team) => team.status === "approved").length < 2
  );
  $("#start-tournament-button").textContent = "조 자동 추첨";
  $("#competition-room-format").textContent =
    tournament.format === "group_then_knockout"
      ? `조 편성 사용 · ${tournament.group_count}개 조 · 조당 ${tournament.qualifiers_per_group}팀 진출 · 본선 자유 편집`
      : "조 편성 없음 · 본선 대진 자유 편집";
  $("#team-score-limit").textContent = tournament.score_limit;
  $("#simulator-score-limit").textContent = tournament.score_limit;
  $("#open-team-register").classList.toggle("hidden", !registrationOpen);
  const showBulkBuild = isHost
    && registrationOpen
    && activeCompetition()?.id === "test2-score-open"
    && tournament.teams.length === 0;
  $("#build-test-teams-button")?.classList.toggle("hidden", !showBulkBuild);
  renderTournamentGroups();

  renderTeamSelectors(
    "#tournament-team-form",
    "#tournament-member-selects",
    loadSimulationDraft()
  );
  renderTeamSelectors("#team-simulator-form", "#simulator-member-selects");

  $("#tournament-team-list").innerHTML = tournament.teams.length
    ? tournament.teams.map((team) => `
      <article class="registered-team${team.over_score_limit ? " over-limit" : ""}">
        <div class="registered-team-head">
          <strong>${escapeHtml(team.name)}</strong>
          <span class="team-status ${team.status}">${team.status === "approved" ? "승인" : team.status === "rejected" ? "반려" : "승인 대기"}</span>
        </div>
        <div class="registered-team-members">
          ${POSITIONS.map((position) => {
            const player = playerById(team.members[position]);
            return `<div class="registered-team-member"><small>${position}</small><strong>${escapeHtml(player?.name || "-")}</strong></div>`;
          }).join("")}
        </div>
        <div class="registered-team-footer">
          <span>총 ${team.total_score} / ${tournament.score_limit}점${team.over_score_limit ? " · 제한 초과" : ""}</span>
          ${isHost ? `<div class="team-admin-actions">
            <button class="ghost" type="button" data-team-approve="${team.id}">승인</button>
            <button class="ghost" type="button" data-team-reject="${team.id}">반려</button>
            <button class="remove" type="button" data-team-delete="${team.id}">삭제</button>
          </div>` : ""}
        </div>
      </article>`).join("")
    : '<div class="empty-message">아직 등록된 팀이 없습니다.</div>';
  updateTeamScore();
  updateSimulatorScore();
  renderTournamentBracket();
}

function renderTournamentGroups() {
  const tournament = state.tournament;
  const isHost = state.viewer.role === "host";
  const teamById = (id) => tournament.teams.find((team) => team.id === id);
  const groupColors = ["blue", "cyan", "green", "slate", "lime", "red", "purple", "indigo"];
  $("#start-group-knockout-button").classList.toggle(
    "hidden", tournament.status !== "group" || !isHost
  );
  const groups = tournament.groups || [];
  const waitingForDraw = groupDrawReady;
  const revealSequence = groupDrawSequence();
  const revealDone = groupDrawRevealActive && groupDrawRevealCount >= revealSequence.length;
  const showDrawControls = groupDrawRevealActive && !waitingForDraw;
  const showManualReveal = showDrawControls && !revealDone;
  const replayButton = $("#play-group-draw-button");
  replayButton?.classList.toggle("hidden", tournament.status !== "group" || groups.length === 0 || waitingForDraw || showDrawControls);
  if (replayButton) replayButton.textContent = "다시 보기";
  const totalTeams = groups.reduce((sum, group) => sum + group.team_ids.length, 0);
  $("#tournament-groups").innerHTML = `
    <div id="group-draw-waiting" class="group-draw-waiting${waitingForDraw ? "" : " hidden"}">
      <div class="draw-orbit"><span></span></div>
      <small>GROUP DRAW READY</small>
      <strong>조 추첨 대기</strong>
      <p>추첨 시작을 누르면 서버에서 랜덤 조 편성을 확정합니다. 이후 다음 추첨을 누를 때마다 한 칸씩 공개됩니다.</p>
      <button id="start-group-draw-animation" class="accent" type="button">추첨 시작</button>
    </div>
    <div class="group-draw-controls${showDrawControls ? "" : " hidden"}">
      <div>
        <small>NEXT DRAW</small>
        <strong>${revealDone ? "조 추첨 완료" : `${Math.min(groupDrawRevealCount + 1, revealSequence.length)} / ${revealSequence.length}`}</strong>
        <p>${revealDone ? "모든 팀이 공개되었습니다." : "다음 추첨을 누르면 한 팀이 조에 배정됩니다."}</p>
      </div>
      <button id="next-group-draw-team" class="accent" type="button" ${revealDone ? "disabled" : ""}>다음 추첨</button>
    </div>
    <div class="group-draft-layout${waitingForDraw ? " draw-hidden" : ""}">
      <aside class="group-draft-summary">
        <span>GROUP CONFIGURATION</span>
        <dl>
          <div><dt>전체 팀</dt><dd>${totalTeams}</dd></div>
          <div><dt>조 수</dt><dd>${groups.length}</dd></div>
          <div><dt>조당 진출</dt><dd>${tournament.qualifiers_per_group}</dd></div>
        </dl>
        <p>체크한 팀이 본선 진출팀이 됩니다.</p>
      </aside>
      <div class="group-draft-board">
        ${groups.map((group, groupIndex) => `
          <article class="group-draft-card ${groupColors[groupIndex % groupColors.length]}">
            <header>
              <strong>${escapeHtml(group.name)}</strong>
              <span>${(group.qualified_team_ids || []).length}/${tournament.qualifiers_per_group}</span>
            </header>
            <div>
              <div class="group-standings-head">
                <span>순위</span>
                <span>팀</span>
                <span>승점</span>
                <span>득실</span>
                <span>전적</span>
              </div>
              ${(showManualReveal
                ? group.team_ids.map((teamId, teamIndex) => ({
                    teamId,
                    points: 0,
                    diff: 0,
                    wins: 0,
                    draws: 0,
                    losses: 0,
                    drawVisible: revealSequence.findIndex((item) => item.teamId === teamId) < groupDrawRevealCount,
                    drawCurrent: revealSequence[groupDrawRevealCount - 1]?.teamId === teamId,
                  }))
                : groupStandings(group)
              ).map((standing, teamIndex) => {
                const teamId = standing.teamId;
                const checked = (group.qualified_team_ids || []).includes(teamId);
                const drawHidden = showManualReveal && !standing.drawVisible;
                return `<label class="group-team-row${checked ? " qualified" : ""}${standing.drawCurrent ? " draw-current" : ""}${drawHidden ? " draw-slot-empty" : " draw-reveal"}" data-group-index="${groupIndex}" data-team-id="${teamId}">
                  <span class="group-team-seed">${teamIndex + 1}</span>
                  <strong>${drawHidden ? "대기 중" : escapeHtml(teamById(teamId)?.name || "-")}</strong>
                  <b>${standing.points}</b>
                  <em>${signedNumber(standing.diff)}</em>
                  <small>${standing.wins}승 ${standing.draws}무 ${standing.losses}패</small>
                  <input type="checkbox" data-group-qualifier="${groupIndex}" value="${teamId}"
                    aria-label="${escapeHtml(teamById(teamId)?.name || "-")} 본선 진출"
                    ${checked ? "checked" : ""} ${isHost ? "" : "disabled"} />
                </label>`;
              }).join("")}
            </div>
          </article>
        `).join("")}
      </div>
    </div>`;
  renderGroupResultForm();
}

function renderGroupResultForm() {
  const form = $("#group-result-form");
  if (!form) return;
  const groupTeamIds = new Set((state.tournament.groups || []).flatMap((group) => group.team_ids || []));
  const teams = state.tournament.teams.filter((team) => groupTeamIds.has(team.id));
  $("#group-result-entry")?.classList.toggle("hidden", state.tournament.status !== "group" || teams.length < 2);
  if (teams.length < 2) return;
  ["team_a_id", "team_b_id"].forEach((name, index) => {
    const select = form.elements[name];
    const selected = select.value;
    select.innerHTML = teams.map((team) => `<option value="${team.id}">${escapeHtml(team.name)}</option>`).join("");
    if (teams.some((team) => team.id === selected)) select.value = selected;
    else select.selectedIndex = Math.min(index, teams.length - 1);
  });
  if (!form.elements.match_date.value) {
    form.elements.match_date.value = new Date().toISOString().slice(0, 10);
  }
}

function groupDrawSequence() {
  const tournament = state.tournament;
  const teamById = (id) => tournament.teams.find((team) => team.id === id);
  const groups = tournament.groups || [];
  const maxRows = Math.max(0, ...groups.map((group) => group.team_ids.length));
  const sequence = [];
  for (let rowIndex = 0; rowIndex < maxRows; rowIndex += 1) {
    groups.forEach((group, groupIndex) => {
      const teamId = group.team_ids[rowIndex];
      if (!teamId) return;
      sequence.push({
        groupIndex,
        groupName: group.name,
        teamId,
        teamName: teamById(teamId)?.name || "-",
      });
    });
  }
  return sequence;
}

function groupDrawSignature() {
  return JSON.stringify((state.tournament.groups || []).map((group) => group.team_ids));
}

function groupStandings(group) {
  const teamIds = new Set(group.team_ids || []);
  const rows = new Map((group.team_ids || []).map((teamId) => [teamId, {
    teamId,
    played: 0,
    wins: 0,
    draws: 0,
    losses: 0,
    scored: 0,
    conceded: 0,
    points: 0,
    diff: 0,
  }]));
  (state.scrim_results || []).forEach((result) => {
    if (!teamIds.has(result.team_a_id) || !teamIds.has(result.team_b_id)) return;
    const a = rows.get(result.team_a_id);
    const b = rows.get(result.team_b_id);
    const aScore = Number(result.team_a_score || 0);
    const bScore = Number(result.team_b_score || 0);
    a.played += 1;
    b.played += 1;
    a.scored += aScore;
    a.conceded += bScore;
    b.scored += bScore;
    b.conceded += aScore;
    if (aScore > bScore) {
      a.wins += 1;
      b.losses += 1;
      a.points += 3;
    } else if (bScore > aScore) {
      b.wins += 1;
      a.losses += 1;
      b.points += 3;
    } else {
      a.draws += 1;
      b.draws += 1;
      a.points += 1;
      b.points += 1;
    }
  });
  rows.forEach((row) => { row.diff = row.scored - row.conceded; });
  return [...rows.values()].sort((left, right) =>
    right.points - left.points
    || right.diff - left.diff
    || right.scored - left.scored
    || left.teamId.localeCompare(right.teamId)
  );
}

function signedNumber(value) {
  return value > 0 ? `+${value}` : String(value);
}

function maybePlayGroupDrawAnimation(force = false) {
  if (scrimRoomTab !== "groups" || state.tournament.status !== "group") return;
  const signature = groupDrawSignature();
  if (!signature || signature === "[]" || (!force && signature === lastGroupDrawAnimationSignature)) return;
  lastGroupDrawAnimationSignature = signature;
  window.setTimeout(startManualGroupDraw, 80);
}

function startManualGroupDraw() {
  const sequence = groupDrawSequence();
  if (!sequence.length) return;
  groupDrawRevealActive = true;
  groupDrawRevealCount = 0;
  lastGroupDrawAnimationSignature = "";
  renderTournamentGroups();
}

function revealNextGroupDrawTeam() {
  const sequence = groupDrawSequence();
  if (!sequence.length) return;
  groupDrawRevealActive = true;
  groupDrawRevealCount = Math.min(groupDrawRevealCount + 1, sequence.length);
  if (groupDrawRevealCount >= sequence.length) {
    lastGroupDrawAnimationSignature = groupDrawSignature();
  }
  renderTournamentGroups();
}

function renderParticipation() {
  const participation = state.participation || {
    enabled: false,
    score_visible: false,
    terms: "",
    application_count: 0,
    viewer_has_applied: false,
  };
  const isHost = state.viewer.role === "host";
  $("#participation-status").textContent = participation.enabled
    ? `신청 접수 중 · ${participation.application_count || 0}명`
    : "신청 닫힘";
  $("#participation-host-panel").classList.toggle("hidden", !isHost);
  $("#participation-apply-panel").classList.toggle("hidden", isHost);
  $("#participation-terms").textContent = participation.terms || "등록된 약관이 없습니다.";

  const agree = $("#participation-terms-agree");
  const applyButton = $("#participation-apply-button");
  agree.checked = false;
  agree.disabled = !participation.enabled || participation.viewer_has_applied;
  applyButton.disabled =
    !participation.enabled || participation.viewer_has_applied || !agree.checked;
  applyButton.textContent = participation.viewer_has_applied
    ? "이미 참가 신청했습니다"
    : participation.enabled ? "대회 참가 신청" : "아직 참가 신청이 열리지 않았습니다";

  if (isHost) {
    const form = $("#participation-settings-form");
    form.elements.enabled.checked = Boolean(participation.enabled);
    form.elements.score_visible.checked = Boolean(participation.score_visible);
    form.elements.terms.value = participation.terms || "";
    setParticipationHostView(participationHostView);
    const signature = `${participation.enabled ? 1 : 0}:${participation.application_count || 0}`;
    if (participationHostView === "approvals" && signature !== participationApplicationsSignature) {
      loadParticipationApplications({ force: true, signature });
    }
  }
}

function setParticipationHostView(view) {
  participationHostView = view;
  $("#participation-settings-view").classList.toggle("hidden", view !== "settings");
  $("#participation-approvals-view").classList.toggle("hidden", view !== "approvals");
  $$("[data-participation-host-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.participationHostView === view);
  });
}

function setParticipationApprovalView(view) {
  participationApprovalView = view;
  $("#participation-requests-view").classList.toggle("hidden", view !== "requests");
  $("#participation-not-applied-view").classList.toggle("hidden", view !== "not-applied");
  $$("[data-participation-approval-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.participationApprovalView === view);
  });
}

function setParticipationApprovalStatus(status) {
  participationApprovalStatus = status;
  $("#pending-users").classList.toggle("hidden", status !== "pending");
  $("#approved-users").classList.toggle("hidden", status !== "approved");
  $$("[data-participation-approval-status]").forEach((button) => {
    button.classList.toggle("active", button.dataset.participationApprovalStatus === status);
  });
}

function renderParticipationUsers(target, users) {
  const node = $(target);
  node.innerHTML = users.length
    ? users.map((user) => `
      <article class="participation-user">
        <div>
          <strong>${escapeHtml(user.name)}</strong>
          <span>${escapeHtml(user.riot_id)}</span>
        </div>
        <small>${participationStatusLabel(user.participation_status)}${user.applied_at ? ` · ${formatDateTime(user.applied_at)}` : ""}</small>
        ${user.applied_at ? `<div class="participation-actions">
          <button class="ghost" type="button" data-participation-status="${user.id}" data-status="APPROVED">승인</button>
          <button class="remove" type="button" data-participation-status="${user.id}" data-status="CANCELLED">거절</button>
        </div>` : ""}
      </article>
    `).join("")
    : '<div class="empty-state">해당 인원이 없습니다.</div>';
}

async function loadParticipationApplications({ force = false, signature = "" } = {}) {
  if (state.viewer.role !== "host" || currentView !== "participation") return;
  if (participationApplicationsPromise && !force) {
    return participationApplicationsPromise;
  }
  if (force) participationApplicationsPromise = null;
  participationApplicationsSignature = signature || participationApplicationsSignature;
  participationApplicationsPromise = (async () => {
  try {
    const data = await api("/api/participation/applications");
    const pendingUsers = data.applied.filter((user) => user.participation_status !== "APPROVED");
    const approvedUsers = data.applied.filter((user) => user.participation_status === "APPROVED");
    if (state?.participation) {
      state.participation.application_count = data.applied.length;
      state.participation.enabled = Boolean(data.enabled);
      state.participation.score_visible = Boolean(data.score_visible);
    }
    $("#participation-status").textContent = data.enabled
      ? `신청 접수 중 · ${data.applied.length}명`
      : "신청 대기";
    $("#pending-count").textContent = pendingUsers.length;
    $("#approved-count").textContent = approvedUsers.length;
    $("#not-applied-count").textContent = data.not_applied.length;
    renderParticipationUsers("#pending-users", pendingUsers);
    renderParticipationUsers(
      "#approved-users",
      approvedUsers.map((user) => ({ ...user, applied_at: null }))
    );
    renderParticipationUsers(
      "#not-applied-users",
      data.not_applied.map((user) => ({ ...user, applied_at: null }))
    );
    setParticipationApprovalView(participationApprovalView);
    setParticipationApprovalStatus(participationApprovalStatus);
  } catch (error) {
    toast(error.message, true);
  } finally {
    participationApplicationsPromise = null;
  }
  })();
  return participationApplicationsPromise;
}

function participationClass(status) {
  if (status === "applied") return "approved";
  if (status === "not_applied") return "pending";
  return "excluded";
}

let rosterFilter = "with_id";

function rosterStatusClass(status) {
  if (status === "ISSUED" || status === "applied") return "approved";
  if (status === "not_applied") return "pending";
  return "excluded";
}

function rosterCell(entry, name, placeholder = "") {
  const value = entry[name] || "";
  return `<div class="roster-sheet-cell roster-field-${name}"><input name="${name}" value="${escapeHtml(value)}" title="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" aria-label="${name}" /></div>`;
}

function rosterTierCell(entry) {
  return `<div class="roster-sheet-cell roster-tier-cell">
    <input name="tier" value="${escapeHtml(entry.tier || "")}" aria-label="tier" />
    <button class="roster-riot-fill" type="button" data-roster-riot-fill title="Riot ID로 티어와 점수 조회">조회</button>
  </div>`;
}

function rosterPaymentCell(entry) {
  const paid = String(entry.payment_status || "").trim().toUpperCase() === "O";
  return `<div class="roster-sheet-cell roster-payment-cell">
    <input name="payment_status" type="hidden" value="${paid ? "O" : "X"}" />
    <button class="roster-payment-toggle ${paid ? "paid" : "unpaid"}" type="button" data-payment-toggle aria-label="입금 상태">
      ${paid ? "O" : "X"}
    </button>
  </div>`;
}

function rosterParticipationCell(entry) {
  const applied = entry.tournament_status === "applied";
  return `<div class="roster-sheet-status roster-participation-field">
    <input name="participation_status_text" type="hidden" value="${applied ? "대회 참가" : "대회 미참가"}" />
    <span class="user-approval ${participationClass(entry.tournament_status)}">${applied ? "참가" : "불참"}</span>
  </div>`;
}

function renderRosterCreateRow() {
  if (!rosterCreateOpen) return "";
  const draft = {};
  return `
    <form class="roster-admin-row roster-create-row" data-roster-create>
      <div class="roster-sheet-index"><button class="roster-create-cancel" type="button" data-roster-create-cancel>×</button></div>
      ${rosterCell(draft, "name", "이름")}
      ${rosterCell(draft, "riot_id", "Riot ID#KR1")}
      ${rosterCell(draft, "secondary_riot_id", "선택 입력")}
      ${rosterCell(draft, "preferred_lines", "정글,미드,원딜")}
      ${rosterTierCell(draft)}
      ${rosterPaymentCell(draft)}
      ${rosterParticipationCell({ tournament_status: "not_applied" })}
      ${rosterCell(draft, "absence_reason")}
      ${rosterCell(draft, "top_adjustment")}
      ${rosterCell(draft, "game_count_adjustment")}
      ${rosterCell(draft, "notes")}
      ${rosterCell(draft, "score_top")}
      ${rosterCell(draft, "score_jungle")}
      ${rosterCell(draft, "score_mid")}
      ${rosterCell(draft, "score_adc")}
      ${rosterCell(draft, "score_support")}
      <div class="roster-sheet-status"><span class="user-approval pending">미발급</span></div>
      <div class="roster-sheet-status"><span class="user-approval pending">대회 미참가</span></div>
      <div class="roster-sheet-save"><button class="primary" type="submit">추가</button></div>
    </form>
  `;
}

function participationStatusLabel(status) {
  if (status === "APPROVED") return "승인";
  if (status === "CANCELLED") return "취소";
  return "신청";
}

function renderParticipationPopover(entry) {
  const events = entry.participation_events || [];
  const rows = events.length
    ? events.map((event) => `
      <div class="participation-popover-row">
        <strong>${escapeHtml(event.competition_name || "-")}</strong>
        <span>${participationStatusLabel(event.status)}${event.applied_at ? ` · ${formatDateTime(event.applied_at)}` : ""}</span>
      </div>
    `).join("")
    : '<div class="participation-popover-empty">참가 기록이 없습니다.</div>';
  return `
    <div class="participation-popover hidden" data-participation-popover="${entry.id}">
      ${rows}
    </div>
  `;
}

function renderMemberRows(entries) {
  const list = $("#member-list");
  if (!entries.length && !rosterCreateOpen) {
    list.innerHTML = '<div class="empty-state">조건에 맞는 명단이 없습니다.</div>';
    return;
  }
  const headers = ["행", "이름", "본 아이디", "부 아이디", "참가라인", "티어", "입금", "참가여부", "불참사유", "탑레조정", "판수조정", "기타", "탑", "정글", "미드", "원딜", "서폿", "계정", "대회", "저장"];
  list.innerHTML = `
    <div class="roster-sheet">
      <div class="roster-sheet-header">${headers.map((header) => `<div>${header}</div>`).join("")}</div>
      ${renderRosterCreateRow()}
      ${entries.map((entry) => `
        <form class="roster-admin-row${dirtyRosterIds.has(entry.id) ? " dirty" : ""}" data-roster-entry="${entry.id}">
          <div class="roster-sheet-index">${entry.source_row}</div>
          ${rosterCell(entry, "name")}
          ${rosterCell(entry, "riot_id", "Riot ID#KR1")}
          ${rosterCell(entry, "secondary_riot_id", "선택 입력")}
          ${rosterCell(entry, "preferred_lines", "순서대로 주, 부 라인")}
          ${rosterTierCell(entry)}
          ${rosterPaymentCell(entry)}
          ${rosterParticipationCell(entry)}
          ${rosterCell(entry, "absence_reason")}
          ${rosterCell(entry, "top_adjustment")}
          ${rosterCell(entry, "game_count_adjustment")}
          ${rosterCell(entry, "notes")}
          ${rosterCell(entry, "score_top")}
          ${rosterCell(entry, "score_jungle")}
          ${rosterCell(entry, "score_mid")}
          ${rosterCell(entry, "score_adc")}
          ${rosterCell(entry, "score_support")}
          <div class="roster-sheet-status"><span class="user-approval ${rosterStatusClass(entry.account_status)}">${entry.account_status === "ISSUED" ? "발급" : "미발급"}</span></div>
          <div class="roster-sheet-status participation-cell">
            <span class="user-approval ${participationClass(entry.tournament_status)}">${escapeHtml(entry.tournament_label)}</span>
            <button class="participation-count" type="button" data-participation-count="${entry.id}">${Number(entry.participation_count || 0)}회</button>
            ${renderParticipationPopover(entry)}
          </div>
          <div class="roster-sheet-save">
            <button class="primary" type="submit">저장</button>
            <button class="remove" type="button" data-roster-delete="${entry.id}" data-roster-name="${escapeHtml(entry.name || "")}">삭제</button>
          </div>
        </form>
      `).join("")}
    </div>`;
}

function renderRiotPreview(data) {
  let preview = $("#riot-player-preview");
  if (!preview) {
    preview = document.createElement("div");
    preview.id = "riot-player-preview";
    preview.className = "riot-player-preview";
    $("#riot-player-form").after(preview);
  }
  const champions = data.champions?.length
    ? data.champions.slice(0, 5).map((champion) => `
      <span>${escapeHtml(champion.name)} ${champion.games}판 · ${champion.wins}승 · ${champion.kills}/${champion.deaths}/${champion.assists}</span>
    `).join("")
    : "<span>최근 챔피언 기록 없음</span>";
  preview.innerHTML = `
    <div class="riot-preview-head">
      ${data.profile_icon_url ? `<img src="${escapeHtml(data.profile_icon_url)}" alt="" />` : '<div class="avatar"></div>'}
      <div>
        <strong>${escapeHtml(data.name)}</strong>
        <small>${escapeHtml(data.riot_id)} · ${escapeHtml(data.tier)}</small>
      </div>
      <button class="accent" type="button" id="add-riot-preview-player">이 정보로 추가</button>
    </div>
    <div class="riot-preview-champions">${champions}</div>
  `;
}

async function loadMembers() {
  if (state.viewer.role !== "host") return;
  try {
    if (!memberRosterCache) {
      ["#member-stat-total", "#member-stat-with-id", "#member-stat-without-id", "#member-stat-issued", "#member-stat-applied", "#member-stat-applied-unpaid", "#member-stat-not-applied"]
        .forEach((selector) => { $(selector).textContent = "…"; });
      $("#member-list").innerHTML = '<div class="empty-state member-loading">회원 명단을 한 번 불러오는 중입니다...</div>';
      const query = ($("#member-search-form")?.elements.query.value || "").trim();
      const params = new URLSearchParams({
        filter: rosterFilter,
        page: String(rosterPage),
        page_size: "50",
      });
      if (query) params.set("query", query);
      memberRosterCache = await api(`/api/roster?${params.toString()}`);
    }
    const data = memberRosterCache;
    $("#member-stat-total").textContent = data.stats.total;
    $("#member-stat-with-id").textContent = data.stats.with_riot_id;
    $("#member-stat-without-id").textContent = data.stats.without_riot_id;
    $("#member-stat-issued").textContent = data.stats.account_issued;
    $("#member-stat-applied").textContent = data.stats.applied;
    $("#member-stat-applied-unpaid").textContent = data.stats.applied_unpaid || 0;
    $("#member-stat-not-applied").textContent = data.stats.not_applied;
    const query = ($("#member-search-form")?.elements.query.value || "").trim().toLocaleLowerCase();
    const entries = data.entries.filter((entry) => {
      const hasRiotId = Boolean(entry.riot_id);
      const applied = entry.tournament_status === "applied";
      if (rosterFilter === "with_id" && !hasRiotId) return false;
      if (rosterFilter === "without_id" && hasRiotId) return false;
      if (rosterFilter === "applied" && !applied) return false;
      if (rosterFilter === "applied_unpaid" && (!applied || String(entry.payment_status || "").trim().toUpperCase() === "O")) return false;
      if (rosterFilter === "not_applied" && applied) return false;
      if (!query) return true;
      return [entry.name, entry.riot_id, entry.secondary_riot_id, entry.preferred_lines]
        .some((value) => String(value || "").toLocaleLowerCase().includes(query));
    });
    renderMemberRows(entries);
    renderRosterPagination(data.pagination);
  } catch (error) {
    memberRosterCache = null;
    $("#member-list").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    toast(error.message, true);
  }
}

async function reloadMembers() {
  memberRosterCache = null;
  dirtyRosterIds.clear();
  await loadMembers();
}

function updateRosterFormCache(form, values) {
  const id = Number(form.dataset.rosterEntry);
  const cached = Number.isFinite(id)
    ? memberRosterCache?.entries.find((entry) => entry.id === id)
    : null;
  Object.entries(values).forEach(([field, value]) => {
    if (form.elements[field]) form.elements[field].value = value ?? "";
    if (cached) cached[field] = value ?? "";
  });
  form.classList.add("dirty");
  if (Number.isFinite(id)) dirtyRosterIds.add(id);
}

async function autofillRosterFromRiot(form, button) {
  const riotId = form.elements.riot_id?.value?.trim();
  if (!riotId) {
    toast("Riot ID를 먼저 입력해 주세요.", true);
    return;
  }
  if (!riotId.includes("#")) {
    toast("Riot ID는 이름#태그 형식으로 입력해 주세요.", true);
    return;
  }
  const payload = {
    riot_id: riotId,
    preferred_lines: form.elements.preferred_lines?.value || null,
    top_adjustment: form.elements.top_adjustment?.value || null,
    game_count_adjustment: form.elements.game_count_adjustment?.value || null,
  };
  await withButtonLoading(button, "조회중", async () => {
    const preview = await api("/api/roster/riot/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    const scores = preview.scores || {};
    updateRosterFormCache(form, {
      riot_id: preview.riot_id || riotId,
      tier: preview.tier || "",
      score_top: scores.score_top,
      score_jungle: scores.score_jungle,
      score_mid: scores.score_mid,
      score_adc: scores.score_adc,
      score_support: scores.score_support,
    });
    toast(preview.tier ? `${preview.riot_id} 티어와 점수를 채웠습니다.` : `${preview.riot_id}의 점수표 티어를 찾지 못했습니다.`, !preview.tier);
  });
}

function renderRosterPagination(pagination) {
  let node = $("#member-pagination");
  if (!node) {
    node = document.createElement("div");
    node.id = "member-pagination";
    node.className = "member-pagination";
    $("#member-list").after(node);
  }
  const totalPages = pagination?.total_pages || 1;
  const current = pagination?.page || 1;
  const pages = [];
  for (let page = 1; page <= totalPages; page += 1) {
    if (
      page === 1 ||
      page === totalPages ||
      Math.abs(page - current) <= 2
    ) {
      pages.push(page);
    }
  }
  node.innerHTML = pages.map((page, index) => {
    const gap = index > 0 && page - pages[index - 1] > 1 ? '<span>...</span>' : "";
    return `${gap}<button type="button" class="${page === current ? "active" : ""}" data-roster-page="${page}">${page}</button>`;
  }).join("");
}

function renderMyPage() {
  const viewer = state.viewer || {};
  const form = $("#mypage-form");
  if (!form || !viewer.authenticated) return;
  $("#mypage-score-tier").textContent = viewer.roster_tier || "티어 미등록";
  const scoreLines = viewer.score_lines || [];
  $("#mypage-score-list").innerHTML = !viewer.score_visible
    ? '<div class="empty-state">점수는 아직 공개되지 않았습니다.</div>'
    : scoreLines.length
    ? scoreLines.map((line) => `
      <article class="mypage-score-item">
        <div><span>${escapeHtml(line.role)}</span><strong>${escapeHtml(line.label)}</strong></div>
        <b>${escapeHtml(line.score)}<small>점</small></b>
      </article>
    `).join("")
    : '<div class="empty-state">티어와 참가라인이 등록되면 내 점수가 표시됩니다.</div>';
  form.elements.riot_id.value = viewer.riot_id || "";
  form.elements.secondary_riot_id.value = viewer.secondary_riot_id || "";
  form.elements.nickname.value = viewer.nickname || "";
}

function renderNotices() {
  const isHost = state.viewer.role === "host";
  $("#notice-form").classList.toggle("hidden", !isHost);
  const notices = state.notices || [];
  $("#notice-list").innerHTML = notices.length
    ? notices.map((notice) => `
      <article class="notice-card">
        <div class="notice-card-head">
          <div>
            <strong>${escapeHtml(notice.title)}</strong>
            <span>${notice.created_at ? formatDateTime(notice.created_at) : ""}</span>
          </div>
          ${isHost ? `<button class="remove" type="button" data-notice-delete="${notice.id}">삭제</button>` : ""}
        </div>
        <p>${escapeHtml(notice.body).replace(/\n/g, "<br>")}</p>
      </article>
    `).join("")
    : '<div class="empty-state">등록된 공지사항이 없습니다.</div>';
}

function formatDateTime(timestamp) {
  return new Date(Number(timestamp) * 1000).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderTeamSelectorSlot(position, primaryCandidates, secondaryCandidates, isSimulator) {
  const primaryOptions = primaryCandidates.map((player) =>
    `<option value="${player.id}">${escapeHtml(player.name)} | ${scoreForPosition(player, position)}점 [주]</option>`
  ).join("");
  const secondaryOptions = secondaryCandidates.map((player) =>
    `<option value="${player.id}">${escapeHtml(player.name)} | ${scoreForPosition(player, position)}점 [부]</option>`
  ).join("");
  return `<label class="tournament-member-slot">
    <strong><span>${position}</span>${POSITION_NAMES[position]} 배치</strong>
    <select name="${position}" ${isSimulator ? "" : "required"}>
      <option value="">${POSITION_NAMES[position]} 선수 선택</option>
      ${primaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 주 포지션">${primaryOptions}</optgroup>` : ""}
      ${secondaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 부 포지션 가능">${secondaryOptions}</optgroup>` : ""}
    </select>
    <small>주 ${primaryCandidates.length}명 · 부 ${secondaryCandidates.length}명</small>
  </label>`;
}

function renderTeamSelectors(formSelector, containerSelector, initial = null) {
  const form = $(formSelector);
  const isSimulator = formSelector === "#team-simulator-form";
  const excludedPlayerIds = isSimulator ? registeredTournamentPlayerIds() : new Set();
  if (isSimulator) {
    const excludedSignature = [...excludedPlayerIds].sort().join("|");
    if (simulatorExcludedSignature !== excludedSignature) {
      simulatorExcludedSignature = excludedSignature;
      window.latestRecommendations = [];
      const recommendationPanel = $("#simulator-recommendations");
      if (recommendationPanel) recommendationPanel.innerHTML = "";
    }
  }
  const currentSelections = Object.fromEntries(
    POSITIONS.map((position) => [
      position,
      excludedPlayerIds.has(form.elements[position]?.value || initial?.[position])
        ? ""
        : form.elements[position]?.value || initial?.[position] || "",
    ])
  );
  $(containerSelector).innerHTML = POSITIONS.map((position) => {
    const primaryCandidates = state.players
      .filter((player) =>
        !excludedPlayerIds.has(player.id) &&
        player.primary_position === position
      )
      .sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));
    const secondaryCandidates = state.players
      .filter((player) =>
        !excludedPlayerIds.has(player.id) &&
        player.primary_position !== position &&
        playerCanPosition(player, position)
      )
      .sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));
    return renderTeamSelectorSlot(position, primaryCandidates, secondaryCandidates, isSimulator);
    const primaryOptions = primaryCandidates.map((player) =>
      `<option value="${player.id}">${escapeHtml(player.name)} | ${scoreForPosition(player, position)}점 [주]</option>`
    ).join("");
    const secondaryOptions = secondaryCandidates.map((player) =>
      `<option value="${player.id}">${escapeHtml(player.name)} | ${scoreForPosition(player, position)}점 [부]</option>`
    ).join("");
    return `<label class="tournament-member-slot">
      <strong><span>${position}</span>${POSITION_NAMES[position]} 배치</strong>
      <select name="${position}" ${isSimulator ? "" : "required"}>
        <option value="">${POSITION_NAMES[position]} 선수 선택</option>
        ${primaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 주 포지션">${primaryOptions}</optgroup>` : ""}
        ${secondaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 부 포지션 가능">${secondaryOptions}</optgroup>` : ""}
      </select>
      <small>주 ${primaryCandidates.length}명 · 부 ${secondaryCandidates.length}명</small>
    </label>`;
    const candidateOptions = `
      ${primaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 주 포지션">
        ${primaryCandidates.map((player) =>
          `<option value="${player.id}">${escapeHtml(player.name)}　|　${scoreForPosition(player, position)}점　[주]</option>`
        ).join("")}
      </optgroup>` : ""}
      ${secondaryCandidates.length ? `<optgroup label="${POSITION_NAMES[position]} 부 포지션 가능">
        ${secondaryCandidates.map((player) =>
          `<option value="${player.id}">${escapeHtml(player.name)}　|　${scoreForPosition(player, position)}점　[부]</option>`
        ).join("")}
      </optgroup>` : ""}`;
    return `<label class="tournament-member-slot">
      <strong><span>${position}</span>${POSITION_NAMES[position]} 배치</strong>
      <select name="${position}" ${isSimulator ? "" : "required"}>
        <option value="">${POSITION_NAMES[position]} 선수 선택</option>
        ${candidateOptions}
      </select>
      <small>주 ${primaryCandidates.length}명 · 부 ${secondaryCandidates.length}명</small>
    </label>`;
  }).join("");
  POSITIONS.forEach((position) => {
    const select = form.elements[position];
    if ([...select.options].some((option) => option.value === currentSelections[position])) {
      select.value = currentSelections[position];
    }
  });
}

function calculateFormScore(formSelector) {
  const form = $(formSelector);
  const selections = POSITIONS.map((position) => ({
    position,
    id: form.elements[position]?.value,
  })).filter((selection) => selection.id);
  const ids = selections.map((selection) => selection.id);
  const score = selections.reduce(
    (sum, selection) =>
      sum + scoreForPosition(playerById(selection.id), selection.position),
    0
  );
  const limit = state.tournament.score_limit;
  const duplicate = ids.length !== new Set(ids).size;
  const complete = ids.length === POSITIONS.length;
  const over = score > limit;
  return { ids, score, limit, duplicate, complete, over };
}

function updateTeamScore() {
  if (!state || state.tournament.status !== "registration") return;
  const { score, limit, duplicate, complete, over } =
    calculateFormScore("#tournament-team-form");
  $("#team-current-score").textContent = score;
  const bar = $("#team-score-bar");
  bar.style.width = `${Math.min(100, limit ? score / limit * 100 : 0)}%`;
  bar.classList.toggle("over", over);
  const message = $("#team-score-message");
  message.classList.toggle("over", over || duplicate);
  message.textContent = duplicate ? "같은 선수를 두 포지션에 등록할 수 없습니다."
    : over ? `제한을 ${score - limit}점 초과했습니다.`
      : complete ? `등록 가능 · ${limit - score}점 여유`
        : "다섯 포지션의 선수를 선택해 주세요.";
  $("#team-register-button").disabled = !complete || over || duplicate;
}

function updateSimulatorScore() {
  if (!state) return;
  const { ids, score, limit, duplicate, complete, over } =
    calculateFormScore("#team-simulator-form");
  $("#simulator-current-score").textContent = score;
  const bar = $("#simulator-score-bar");
  bar.style.width = `${Math.min(100, limit ? score / limit * 100 : 0)}%`;
  bar.classList.toggle("over", over);
  const message = $("#simulator-score-message");
  message.classList.toggle("over", over || duplicate);
  message.textContent = duplicate ? "같은 선수를 두 포지션에 넣을 수 없습니다."
    : over ? `현재 고정 선수만으로 제한을 ${score - limit}점 초과했습니다.`
      : complete ? `사용 가능한 조합 · ${limit - score}점 여유`
        : ids.length
          ? `${ids.length}개 포지션 고정 · 빈 자리를 추천으로 채울 수 있습니다.`
          : "한 명 이상 선택하면 최적 조합을 추천합니다.";
  const recommendButton = $("#use-simulation-button");
  const emptyCount = POSITIONS.length - ids.length;
  recommendButton.textContent = emptyCount
    ? `빈 ${emptyCount}자리 최적 조합 추천`
    : "현재 조합과 가까운 대안 추천";
  recommendButton.disabled = ids.length === 0 || duplicate;
  const draft = Object.fromEntries(
    POSITIONS.map((position) => [
      position,
      $("#team-simulator-form").elements[position]?.value || "",
    ])
  );
  sessionStorage.setItem("tournament-team-draft", JSON.stringify(draft));
}

function loadSimulationDraft() {
  try {
    return JSON.parse(sessionStorage.getItem("tournament-team-draft") || "null");
  } catch {
    return null;
  }
}

function renderSimulatorRecommendations(recommendations) {
  $("#simulator-recommendations").innerHTML = recommendations.length
    ? recommendations.map((result, index) => `
      <article class="recommendation-card">
        <div class="recommendation-rank">${index + 1}</div>
        ${POSITIONS.map((position) => {
          const player = result.lineup[position];
          return `<div class="recommendation-member${player.is_off_position ? " off-position" : ""}${player.is_locked ? " locked" : ""}">
            <small>${position}${player.is_off_position ? " · 부 포지션" : ""}</small>
            <strong>${escapeHtml(player.name)}</strong>
            <span>${player.score}점</span>
          </div>`;
        }).join("")}
        <div class="recommendation-score">
          <small>목표 ${result.target_score} · 차이 ${result.score_difference}</small>
          <strong class="${result.score_difference === 0 ? "perfect" : ""}">${result.total_score}점</strong>
        </div>
        <button class="apply-recommendation" type="button" data-apply-recommendation="${index}">조합 적용</button>
      </article>`).join("")
    : '<div class="balance-empty">조건에 맞는 조합을 찾지 못했습니다.</div>';
  window.latestRecommendations = recommendations;
}

function renderTournamentBracket() {
  const tournament = state.tournament;
  const isHost = state.viewer.role === "host";
  const teamById = (id) => tournament.teams.find((team) => team.id === id);
  $("#tournament-champion").textContent = tournament.champion_id
    ? `🏆 ${teamById(tournament.champion_id)?.name || ""} 우승`
    : "";
  const roundLabel = (roundIndex) => {
    const remaining = tournament.rounds.length - roundIndex;
    if (remaining === 1) return "FINAL";
    if (remaining === 2) return "SEMI-FINALS";
    if (remaining === 3) return "QUARTER-FINALS";
    return `ROUND OF ${2 ** remaining}`;
  };
  $("#tournament-bracket").innerHTML = tournament.rounds.map((round, roundIndex) => `
    <section class="bracket-round">
      <div class="bracket-round-title">${escapeHtml(tournament.round_labels?.[roundIndex] || roundLabel(roundIndex))}</div>
      ${round.map((match, matchIndex) => `
        <div class="bracket-match">
          <div class="bracket-match-label">MATCH ${matchIndex + 1}${match.winner_id ? " · FINISHED" : ""}</div>
          ${["team1_id", "team2_id"].map((slot) => {
            const team = teamById(match[slot]);
            const canSelect = isHost && team && match.team1_id && match.team2_id && !match.winner_id;
            return `<button class="bracket-team${team ? " ready" : ""}${match.winner_id === team?.id ? " winner" : ""}" type="button"
              ${canSelect ? `data-match-winner="${team.id}" data-round-index="${roundIndex}" data-match-index="${matchIndex}"` : "disabled"}>
              <strong>${escapeHtml(team?.name || "TBD")}</strong>
              <span>${team ? `${team.total_score}점` : ""}</span>
            </button>`;
          }).join("")}
        </div>`).join("")}
    </section>`).join("");
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
      ? "강사님은 진행만 관리하며 입찰하지 않습니다."
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
  const presence = state.captain_presence || {
    online_captain_ids: [], connected: 0, total: state.captains.length, all_connected: false,
  };
  const presencePanel = $("#captain-presence");
  presencePanel.classList.toggle("hidden", state.viewer.role !== "host");
  presencePanel.innerHTML = `
    <div class="captain-presence-summary">
      <strong>팀장 접속 현황</strong>
      <span class="${presence.all_connected ? "ready" : ""}">${presence.connected} / ${presence.total} 접속</span>
    </div>
    <div class="captain-presence-list">
      ${state.captains.map((captain) => {
        const online = presence.online_captain_ids.includes(captain.id);
        return `<span class="${online ? "online" : "offline"}"><i></i>${escapeHtml(captain.name)} 팀</span>`;
      }).join("")}
    </div>`;
  $("#pause-button").classList.toggle(
    "hidden", state.viewer.role !== "host" || auction.status !== "running"
  );
  const startTimerButton = $("#start-timer-button");
  startTimerButton.classList.toggle(
    "hidden", state.viewer.role !== "host" || auction.status !== "ready"
  );
  startTimerButton.disabled = !presence.all_connected;
  startTimerButton.textContent = presence.all_connected
    ? "이 후보 타이머 시작"
    : `팀장 접속 대기 (${presence.connected}/${presence.total})`;
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
  const onlineCaptainIds = state.captain_presence?.online_captain_ids || [];
  $("#teams").innerHTML = state.captains.map((captain) => `
    <div class="team-card">
      <div class="team-head">
        <strong>${escapeHtml(captain.name)} 팀 <small class="connection-badge ${onlineCaptainIds.includes(captain.id) ? "online" : "offline"}">${onlineCaptainIds.includes(captain.id) ? "접속" : "미접속"}</small></strong>
        <span class="budget">${captain.remaining_budget.toLocaleString()} P</span>
      </div>
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
  if (state.auction.status === "ready") remaining = state.settings.countdown_seconds;
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

function renderCurrentView() {
  if (currentView === "poster") renderMainPoster();
  else if (currentView === "intro") renderIntro();
  else if (currentView === "score-intro") renderScoreIntro();
  else if (currentView === "setup") {
    renderSetup();
    renderScoreTableEditor();
  } else if (["team-simulator", "team-register", "tournament"].includes(currentView)) {
    renderTournament();
  } else if (currentView === "participation") renderParticipation();
  else if (currentView === "notices") renderNotices();
  else if (currentView === "mypage") renderMyPage();
  else if (currentView === "auction") renderAuction();
  else if (currentView === "scrim") {
    renderTournament();
    renderScrimRoomTabs();
  }
}

function render() {
  $("#room-title").textContent = state.settings.room_name;
  $("#member-roster-title").textContent = `${state.settings.room_name} 관리`;
  document.title = `${state.settings.room_name} · LoL Auction`;
  $("#deployment-warning").classList.toggle(
    "hidden",
    !state.deployment?.serverless || state.deployment?.persistent
  );
  renderRole();
  renderCompetitions();
  applyCompetitionMode();
  if (
    state.viewer.role !== "host"
    && state.auction.status === "setup"
    && ["setup", "auction"].includes(currentView)
  ) {
    currentView = "poster";
  }
  setView(currentView);
  renderCurrentView();
}

function connectSocket() {
  if (location.hostname.endsWith(".vercel.app")) {
    $("#socket-dot").classList.add("online");
    $("#socket-text").textContent = "자동 갱신";
    setInterval(pollState, STATE_POLL_INTERVAL_MS);
    return;
  }
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
      if (previousStatus === "setup" && state.auction.status === "ready") {
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

function meaningfulStateSignature(value) {
  const copy = structuredClone(value);
  delete copy.server_time;
  if (copy.auction) delete copy.auction.remaining_seconds;
  return JSON.stringify(copy);
}

async function pollState() {
  if (document.hidden) return;
  if (!shouldPollState()) return;
  if (pollStateInFlight || pendingApiCount > 0) return;
  pollStateInFlight = true;
  try {
    const data = await api("/api/state", { silent: true });
    const signature = meaningfulStateSignature(data);
    if (signature !== stateSignature) {
      state = data;
      stateSignature = signature;
      render();
    } else {
      state.server_time = data.server_time;
      state.auction.remaining_seconds = data.auction.remaining_seconds;
    }
  } catch {
    $("#socket-dot").classList.remove("online");
    $("#socket-text").textContent = "재연결 중";
  } finally {
    pollStateInFlight = false;
  }
}

$$(".position-select").forEach((select) => {
  select.innerHTML = positionOptions(select.classList.contains("optional"));
});
["#manual-player-form", "#riot-player-form"].forEach((selector) => {
  const form = $(selector);
  setupPositionSlots(form);
  form.elements.secondary_position.addEventListener("change", () =>
    updateSecondaryScoreField(form)
  );
  updateSecondaryScoreField(form);
});

$$(".tab").forEach((button) => button.addEventListener("click", () => {
  $$(".tab").forEach((tab) => tab.classList.remove("active"));
  button.classList.add("active");
  $("#manual-player-form").classList.toggle("hidden", button.dataset.tab !== "manual");
  $("#riot-player-form").classList.toggle("hidden", button.dataset.tab !== "riot");
}));

$("#captain-player").addEventListener("change", updateCaptainPreview);
$("#manual-tier").addEventListener("change", updateManualTierDivision);
$("#manual-tier-division").addEventListener("input", updateManualTierDivision);
updateManualTierDivision();

$$("[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.view === "auction") {
      enterAuctionView();
      return;
    }
    navigateView(button.dataset.view);
  });
});

$$("[data-navigate-view]").forEach((link) => {
  link.addEventListener("click", (event) => {
    event.preventDefault();
    navigateView(link.dataset.navigateView);
  });
});

$$("[data-scrim-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    scrimRoomTab = button.dataset.scrimTab || "progress";
    renderScrimRoomTabs();
  });
});

window.addEventListener("popstate", () => {
  currentView = location.pathname === "/score-players"
    ? "score-intro"
    : location.pathname === "/team-simulator"
    ? "team-simulator"
    : location.pathname === "/team-register" ? "team-register"
    : location.pathname === "/tournament" ? "tournament"
    : location.pathname === "/participation" ? "participation"
    : location.pathname === "/notices" ? "notices"
    : location.pathname === "/members" ? "members"
    : location.pathname === "/mypage" ? "mypage"
    : location.pathname === "/players" ? "intro"
    : ["/competition-room", "/scrim"].includes(location.pathname) ? "scrim" : "poster";
  if (state) navigateView(currentView);
});

function setAuthMode(mode) {
  authMode = mode;
  $("#login-form").classList.toggle("hidden", mode !== "login");
}

$("#login-button").addEventListener("click", () => {
  authPromptOpen = true;
  setAuthMode("login");
  renderRole();
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form));
  payload.riot_id = String(payload.riot_id || "").trim();
  const button = form.querySelector('button[type="submit"]');
  const status = $("#login-status");
  if (status) {
    status.className = "login-status loading";
    status.textContent = "로그인 중입니다...";
  }
  if (button) {
    button.disabled = true;
    button.textContent = "로그인 중...";
  }
  try {
    await api("/api/scrim/auth/login", { method: "POST", body: JSON.stringify(payload) });
    const nextState = await api("/api/state");
    if (!nextState.viewer?.authenticated) {
      throw new Error("로그인 세션을 저장하지 못했습니다. 새로고침 후 다시 시도해주세요.");
    }
    state = nextState;
    stateSignature = meaningfulStateSignature(state);
    authPromptOpen = false;
    if (status) {
      status.className = "login-status";
      status.textContent = "로그인 성공.";
    }
    render();
  } catch (error) {
    try {
      state = await api("/api/state", { silent: true });
      stateSignature = meaningfulStateSignature(state);
      authPromptOpen = !Boolean(state.viewer?.authenticated);
      render();
    } catch {}
    if (status) {
      status.className = "login-status error";
      status.textContent = `로그인 실패: ${error.message}`;
    }
    toast(`로그인 실패: ${error.message}`, true);
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = "로그인";
    }
  }
});



$("#logout-button").addEventListener("click", async () => {
  await api("/api/scrim/auth/logout", { method: "POST" });
  location.href = "/";
});

$("#room-title").setAttribute("role", "button");
$("#room-title").setAttribute("tabindex", "0");
$("#room-title").setAttribute("title", "메인으로 이동");
$("#room-title").addEventListener("click", () => {
  if (!state?.viewer?.authenticated) return;
  setView(mainViewForCompetition());
});
$("#room-title").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  if (!state?.viewer?.authenticated) return;
  setView(mainViewForCompetition());
});

$("#competition-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  try {
    data.poster_image = await readPosterImageInput(form.elements.poster_image);
    await api("/api/competitions", {
      method: "POST",
      body: JSON.stringify(data),
    });
    form.reset();
    await refreshState();
    toast("새 대회를 만들고 현재 대회로 선택했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#competition-form").elements.mode.addEventListener("change", (event) => {
  $("#competition-tournament-options").classList.toggle(
    "hidden", event.target.value !== "tournament"
  );
});

$("#teacher-score-limit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#save-tournament-settings");
  const scoreLimit = Number(
    new FormData(event.target).get("score_limit")
  );
  try {
    await withButtonLoading(button, "저장 중", () =>
      api("/api/tournament/settings", {
        method: "PUT",
        body: JSON.stringify(tournamentSettingsPayload(scoreLimit)),
      })
    );
    await refreshState();
    toast("점수제 대회 설정을 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#tournament-score-visible-input").addEventListener("change", (event) => {
  const label = $("#tournament-score-visible-label");
  if (label) label.textContent = event.target.checked ? "공개 예정" : "비공개";
});

function tournamentSettingsPayload(scoreLimit = Number($("#teacher-score-limit-input").value)) {
  return {
    score_limit: scoreLimit,
    score_visible: $("#tournament-score-visible-input").checked,
    format: $("#tournament-format-input").value || state.tournament.format || "single_elimination",
    group_count: Number($("#tournament-group-count-input").value || state.tournament.group_count || 2),
    qualifiers_per_group: Number($("#tournament-qualifiers-input").value || state.tournament.qualifiers_per_group || 2),
  };
}

function defaultBracketDraft() {
  const qualified = new Set(state.tournament.qualified_team_ids || []);
  const approved = state.tournament.teams.filter(
    (team) => team.status === "approved"
      && (!state.tournament.groups?.length || qualified.has(team.id))
  );
  const firstMatches = [];
  for (let index = 0; index < approved.length; index += 2) {
    firstMatches.push({
      team1_id: approved[index]?.id || null,
      team2_id: approved[index + 1]?.id || null,
      winner_to: null,
      loser_to: null,
    });
  }
  return [
    { label: "1라운드", matches: firstMatches.length ? firstMatches : [{ team1_id: null, team2_id: null, winner_to: null, loser_to: null }] },
    { label: "결승", matches: [{ team1_id: null, team2_id: null, winner_to: null, loser_to: null }] },
  ];
}

function openBracketEditor() {
  const tournament = state.tournament;
  bracketDraft = tournament.rounds.length
    ? tournament.rounds.map((round, roundIndex) => ({
        label: tournament.round_labels?.[roundIndex] || `라운드 ${roundIndex + 1}`,
        matches: round.map((match) => ({
          team1_id: match.team1_id,
          team2_id: match.team2_id,
          winner_to: match.winner_to || null,
          loser_to: match.loser_to || null,
        })),
      }))
    : defaultBracketDraft();
  $("#bracket-editor-panel").classList.remove("hidden");
  renderBracketEditor();
}

function bracketRouteValue(route) {
  return route ? `${route.round_index}:${route.match_index}:${route.slot}` : "";
}

function renderBracketEditor() {
  if (!bracketDraft) return;
  const qualified = new Set(state.tournament.qualified_team_ids || []);
  const teams = state.tournament.teams.filter(
    (team) => team.status === "approved"
      && (!state.tournament.groups?.length || qualified.has(team.id))
  );
  const teamOptions = (selected) => [
    '<option value="">미정</option>',
    ...teams.map((team) => `<option value="${team.id}" ${team.id === selected ? "selected" : ""}>${escapeHtml(team.name)}</option>`),
  ].join("");
  const routeOptions = (roundIndex, selected) => {
    const options = ['<option value="">이동 없음</option>'];
    bracketDraft.forEach((round, targetRound) => {
      if (targetRound <= roundIndex) return;
      round.matches.forEach((_, targetMatch) => {
        ["team1_id", "team2_id"].forEach((slot, slotIndex) => {
          const value = `${targetRound}:${targetMatch}:${slot}`;
          options.push(`<option value="${value}" ${value === selected ? "selected" : ""}>${escapeHtml(round.label)} · 경기 ${targetMatch + 1} · ${slotIndex + 1}번 칸</option>`);
        });
      });
    });
    return options.join("");
  };
  $("#bracket-editor-rounds").innerHTML = bracketDraft.map((round, roundIndex) => `
    <section class="bracket-editor-round">
      <div class="bracket-editor-round-head">
        <input value="${escapeHtml(round.label)}" data-bracket-round-label="${roundIndex}" aria-label="라운드 이름" />
        <button class="ghost" type="button" data-add-bracket-match="${roundIndex}">경기 추가</button>
        <button class="remove" type="button" data-remove-bracket-round="${roundIndex}">라운드 삭제</button>
      </div>
      ${round.matches.map((match, matchIndex) => `
        <article class="bracket-editor-match">
          <strong>경기 ${matchIndex + 1}</strong>
          <label>1번 팀<select data-bracket-team="${roundIndex}:${matchIndex}:team1_id">${teamOptions(match.team1_id)}</select></label>
          <label>2번 팀<select data-bracket-team="${roundIndex}:${matchIndex}:team2_id">${teamOptions(match.team2_id)}</select></label>
          <label>승자 이동<select data-bracket-route="${roundIndex}:${matchIndex}:winner_to">${routeOptions(roundIndex, bracketRouteValue(match.winner_to))}</select></label>
          <label>패자 이동<select data-bracket-route="${roundIndex}:${matchIndex}:loser_to">${routeOptions(roundIndex, bracketRouteValue(match.loser_to))}</select></label>
          <button class="remove" type="button" data-remove-bracket-match="${roundIndex}:${matchIndex}">삭제</button>
        </article>
      `).join("")}
    </section>
  `).join("");
}

$("#active-competition-select").addEventListener("change", async (event) => {
  if (state.viewer.role !== "host") {
    event.target.value = state.competition_registry.active_competition_id;
    toast("현재 대회 선택은 강사님만 변경할 수 있습니다.", true);
    return;
  }
  try {
    await api(`/api/competitions/${event.target.value}/select`, {
      method: "POST",
    });
    memberRosterCache = null;
    await refreshState();
  } catch (error) { toast(error.message, true); }
});

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  Object.keys(data).filter((key) => key !== "room_name")
    .forEach((key) => data[key] = Number(data[key]));
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(data) });
    await refreshState();
    toast("경매 설정을 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#notice-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    await api("/api/notices", {
      method: "POST",
      body: JSON.stringify(data),
    });
    event.target.reset();
    await refreshState();
    toast("공지사항을 등록했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#score-table-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const rows = [...event.target.querySelectorAll(".score-table-row")]
    .map((row) => {
      const field = (name) => row.querySelector(`[name="${name}"]`);
      return {
        tier_key: field("tier_key").value.trim(),
        top: Number(field("top").value || 0),
        jungle: Number(field("jungle").value || 0),
        mid: Number(field("mid").value || 0),
        adc: Number(field("adc").value || 0),
        support: Number(field("support").value || 0),
      };
    })
    .filter((row) => row.tier_key);
  try {
    await api("/api/roster-score-table", {
      method: "PUT",
      body: JSON.stringify({ rows }),
    });
    await refreshState();
    toast("점수표를 저장했습니다.");
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
  const data = collectPlayerFormData(event.target);
  if (event.target.closest("#member-player-registration-slot")) {
    const query = [data.name, data.riot_id].filter(Boolean).join(" ").trim();
    const searchInput = $("#member-search-form")?.elements.query;
    if (searchInput) searchInput.value = query;
    rosterPage = 1;
    await loadMembers();
    toast(query ? "회원 명단을 검색했습니다." : "검색할 이름 또는 Riot ID를 입력해주세요.", !query);
    return;
  }
  const selectedTier = data.tier;
  data.tier = DIVISION_TIERS.has(selectedTier)
    ? `${selectedTier} ${TIER_DIVISIONS[data.tier_division]}`
    : selectedTier;
  delete data.tier_division;
  data.secondary_position ||= null;
  data.score = Number(data.score || 0);
  data.secondary_score = data.secondary_position
    ? Number(data.secondary_score || data.score || 0)
    : data.score;
  try {
    await api("/api/players", { method: "POST", body: JSON.stringify(data) });
    event.target.reset();
    updateManualTierDivision();
    resetPositionSlots(event.target);
    updateSecondaryScoreField(event.target);
  } catch (error) { toast(error.message, true); }
});

$("#riot-player-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = collectPlayerFormData(event.target);
  data.secondary_position ||= null;
  data.score = Number(data.score || 0);
  data.secondary_score = data.secondary_position
    ? Number(data.secondary_score || data.score || 0)
    : data.score;
  const button = event.target.querySelector("button");
  button.disabled = true;
  button.textContent = "조회 중...";
  try {
    const preview = await api("/api/players/riot/preview", { method: "POST", body: JSON.stringify(data) });
    riotPreviewData = { form: data, preview };
    renderRiotPreview(preview);
    toast("Riot 정보 조회가 완료되었습니다.");
  } catch (error) { toast(error.message, true); }
  finally {
    button.disabled = false;
    button.textContent = "Riot API 조회";
  }
});


$("#tournament-team-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const members = Object.fromEntries(POSITIONS.map((position) => [position, data[position]]));
  try {
    await api("/api/tournament/teams", {
      method: "POST",
      body: JSON.stringify({
        name: data.name,
        registration_pin: data.registration_pin,
        members,
      }),
    });
    sessionStorage.removeItem("tournament-team-draft");
    event.target.reset();
    updateTeamScore();
    toast("팀 등록을 신청했습니다.");
    setTimeout(() => { location.href = "/tournament"; }, 500);
  } catch (error) {
    toast(error.message, true);
  }
});

$("#tournament-member-selects").addEventListener("change", updateTeamScore);
$("#simulator-member-selects").addEventListener("change", updateSimulatorScore);
$("#team-simulator-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const locked = Object.fromEntries(
    POSITIONS.map((position) => [position, data[position] || null])
  );
  const excluded_player_ids = [...registeredTournamentPlayerIds()];
  api("/api/tournament/recommend", {
    method: "POST",
    body: JSON.stringify({ locked, limit: 12, excluded_player_ids }),
  }).then((result) => {
    renderSimulatorRecommendations(result.recommendations);
  }).catch((error) => toast(error.message, true));
});
$("#start-tournament-button").addEventListener("click", async () => {
  if (state.tournament.format === "group_then_knockout") {
    groupDrawReady = true;
    scrimRoomTab = "groups";
    renderTournament();
    renderScrimRoomTabs();
    return;
  }
  try {
    await api("/api/tournament/start", { method: "POST" });
    await refreshState();
    toast("대진표를 생성했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#tournament-groups").addEventListener("click", async (event) => {
  const nextButton = event.target.closest("#next-group-draw-team");
  if (nextButton) {
    revealNextGroupDrawTeam();
    return;
  }
  const button = event.target.closest("#start-group-draw-animation");
  if (!button) return;
  button.disabled = true;
  button.textContent = "추첨 중...";
  try {
    await api("/api/tournament/start", { method: "POST" });
    await refreshState({ renderView: false });
    groupDrawReady = false;
    lastGroupDrawAnimationSignature = "";
    scrimRoomTab = "groups";
    render();
    window.setTimeout(startManualGroupDraw, 120);
  } catch (error) {
    button.disabled = false;
    button.textContent = "추첨 시작";
    toast(error.message, true);
  }
});

$("#play-group-draw-button")?.addEventListener("click", () => {
  startManualGroupDraw();
});

$("#group-result-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target));
  payload.best_of = Number(payload.best_of || 3);
  payload.team_a_score = Number(payload.team_a_score || 0);
  payload.team_b_score = Number(payload.team_b_score || 0);
  try {
    await api("/api/scrim/results", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshState();
    $("#group-result-entry").open = true;
    toast("조별 경기 결과를 저장했습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#build-test-teams-button")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "생성 중...";
  try {
    const result = await api("/api/admin/competitions/test2-score-open/bulk-build-teams", {
      method: "POST",
      body: JSON.stringify({ max_teams: 6 }),
    });
    await refreshState();
    button.classList.add("hidden");
    toast(`test 팀 ${result.created_teams || 0}개를 생성했습니다.`);
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
    button.textContent = "test 팀 생성";
  }
});

$("#setup-test-competitions-button")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = "세팅 중...";
  try {
    const result = await api("/api/admin/setup-test-competitions", {
      method: "POST",
    });
    await refreshState();
    toast(`test1 승인 ${result.test_approved || 0}명 세팅 완료`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "test1 5명 세팅";
  }
});

$$("[data-participation-host-view]").forEach((button) => {
  button.addEventListener("click", () => {
    setParticipationHostView(button.dataset.participationHostView);
    if (participationHostView === "approvals") loadParticipationApplications();
  });
});

$$("[data-participation-approval-view]").forEach((button) => {
  button.addEventListener("click", () => {
    setParticipationApprovalView(button.dataset.participationApprovalView);
  });
});

$$("[data-participation-approval-status]").forEach((button) => {
  button.addEventListener("click", () => {
    setParticipationApprovalStatus(button.dataset.participationApprovalStatus);
  });
});

$("#tournament-groups").addEventListener("change", async (event) => {
  const input = event.target.closest("[data-group-qualifier]");
  if (!input) return;
  const groupIndex = Number(input.dataset.groupQualifier);
  const teamIds = $$(`[data-group-qualifier="${groupIndex}"]:checked`).map((item) => item.value);
  try {
    await api("/api/tournament/groups/qualifiers", {
      method: "PUT",
      body: JSON.stringify({ group_index: groupIndex, team_ids: teamIds }),
    });
    await refreshState({ renderView: false });
    renderTournamentGroups();
  } catch (error) {
    input.checked = !input.checked;
    toast(error.message, true);
  }
});

$("#start-group-knockout-button").addEventListener("click", async () => {
  openBracketEditor();
});

$("#open-bracket-editor-button").addEventListener("click", openBracketEditor);
$("#cancel-bracket-editor-button").addEventListener("click", () => {
  bracketDraft = null;
  $("#bracket-editor-panel").classList.add("hidden");
});
$("#add-bracket-round-button").addEventListener("click", () => {
  bracketDraft.push({
    label: `라운드 ${bracketDraft.length + 1}`,
    matches: [{ team1_id: null, team2_id: null, winner_to: null, loser_to: null }],
  });
  renderBracketEditor();
});
$("#bracket-editor-rounds").addEventListener("input", (event) => {
  const roundIndex = event.target.dataset.bracketRoundLabel;
  if (roundIndex !== undefined) bracketDraft[Number(roundIndex)].label = event.target.value;
});
$("#bracket-editor-rounds").addEventListener("change", (event) => {
  if (event.target.dataset.bracketTeam) {
    const [roundIndex, matchIndex, slot] = event.target.dataset.bracketTeam.split(":");
    bracketDraft[Number(roundIndex)].matches[Number(matchIndex)][slot] = event.target.value || null;
  }
  if (event.target.dataset.bracketRoute) {
    const [roundIndex, matchIndex, field] = event.target.dataset.bracketRoute.split(":");
    const value = event.target.value;
    bracketDraft[Number(roundIndex)].matches[Number(matchIndex)][field] = value
      ? (() => {
          const [targetRound, targetMatch, slot] = value.split(":");
          return { round_index: Number(targetRound), match_index: Number(targetMatch), slot };
        })()
      : null;
  }
});
$("#bracket-editor-rounds").addEventListener("click", (event) => {
  const addRound = event.target.closest("[data-add-bracket-match]")?.dataset.addBracketMatch;
  if (addRound !== undefined) {
    bracketDraft[Number(addRound)].matches.push({
      team1_id: null, team2_id: null, winner_to: null, loser_to: null,
    });
    renderBracketEditor();
    return;
  }
  const removeMatch = event.target.closest("[data-remove-bracket-match]")?.dataset.removeBracketMatch;
  if (removeMatch) {
    const [roundIndex, matchIndex] = removeMatch.split(":").map(Number);
    if (bracketDraft[roundIndex].matches.length > 1) {
      bracketDraft[roundIndex].matches.splice(matchIndex, 1);
      renderBracketEditor();
    }
    return;
  }
  const removeRound = event.target.closest("[data-remove-bracket-round]")?.dataset.removeBracketRound;
  if (removeRound !== undefined && bracketDraft.length > 1) {
    bracketDraft.splice(Number(removeRound), 1);
    renderBracketEditor();
  }
});
$("#save-bracket-editor-button").addEventListener("click", async () => {
  try {
    await api("/api/tournament/bracket", {
      method: "PUT",
      body: JSON.stringify({ rounds: bracketDraft }),
    });
    await refreshState({ renderView: false });
    bracketDraft = null;
    $("#bracket-editor-panel").classList.add("hidden");
    render();
    toast("강사님이 구성한 본선 대진표를 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#participation-terms-agree").addEventListener("change", (event) => {
  const participation = state.participation || {};
  $("#participation-apply-button").disabled =
    !participation.enabled
    || participation.viewer_has_applied
    || !event.target.checked;
});

$("#participation-apply-button").addEventListener("click", async () => {
  try {
    await api("/api/participation/apply", {
      method: "POST",
      body: JSON.stringify({
        terms_agreed: $("#participation-terms-agree").checked,
      }),
    });
    await refreshState();
    toast("대회 참가 신청을 완료했습니다.");
  } catch (error) { toast(error.message, true); }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-participation-status]");
  if (!button) return;
  const originalText = button.textContent;
  const row = button.closest(".participation-user");
  row?.querySelectorAll("[data-participation-status]").forEach((action) => {
    action.disabled = true;
  });
  button.textContent = "처리 중";
  try {
    await api(`/api/participation/applications/${button.dataset.participationStatus}`, {
      method: "PATCH",
      body: JSON.stringify({ status: button.dataset.status }),
    });
    memberRosterCache = null;
    participationApplicationsSignature = "";
    await loadParticipationApplications({ force: true, signature: `manual:${Date.now()}` });
    if (currentView === "members") await reloadMembers();
    toast(button.dataset.status === "APPROVED" ? "참가를 승인했습니다." : "참가 신청을 거절했습니다.");
  } catch (error) {
    toast(error.message, true);
    row?.querySelectorAll("[data-participation-status]").forEach((action) => {
      action.disabled = false;
    });
    button.textContent = originalText;
  }
});

$("#participation-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
    await api("/api/participation/settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: form.elements.enabled.checked,
        score_visible: form.elements.score_visible.checked,
        terms: form.elements.terms.value,
      }),
    });
    state.participation.enabled = form.elements.enabled.checked;
    state.participation.score_visible = form.elements.score_visible.checked;
    state.participation.terms = form.elements.terms.value;
    stateSignature = meaningfulStateSignature(state);
    render();
    if (participationHostView === "approvals") {
      await loadParticipationApplications({ force: true, signature: `settings:${Date.now()}` });
    }
    toast("참가 신청 설정을 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});

document.addEventListener("click", async (event) => {
  const searchedPlayer = event.target.closest("[data-player-search-id]");
  if (searchedPlayer) {
    selectSearchedPlayer(
      searchedPlayer.dataset.playerSearchId,
      searchedPlayer.dataset.playerSearchView
    );
    return;
  }
  const noticeDeleteId = event.target.closest("[data-notice-delete]")?.dataset.noticeDelete;
  if (noticeDeleteId) {
    try {
      await api(`/api/notices/${noticeDeleteId}`, { method: "DELETE" });
      await refreshState();
      toast("공지사항을 삭제했습니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  const scoreIntroPosition =
    event.target.closest("[data-score-intro-position]")?.dataset.scoreIntroPosition;
  const scoreIntroRequestedIndex =
    event.target.closest("[data-score-intro-index]")?.dataset.scoreIntroIndex;
  if (scoreIntroPosition) {
    const players = sortedIntroPlayers();
    scoreIntroIndex = players.findIndex(
      (player) => player.primary_position === scoreIntroPosition
    );
    scoreIntroPlayerId = players[scoreIntroIndex]?.id || null;
    renderScoreIntro();
    return;
  }
  if (scoreIntroRequestedIndex !== undefined) {
    scoreIntroIndex = Number(scoreIntroRequestedIndex);
    scoreIntroPlayerId = sortedIntroPlayers()[scoreIntroIndex]?.id || null;
    renderScoreIntro();
    return;
  }
  const recommendationIndex =
    event.target.closest("[data-apply-recommendation]")?.dataset.applyRecommendation;
  if (recommendationIndex !== undefined) {
    const result = window.latestRecommendations?.[Number(recommendationIndex)];
    if (result) {
      POSITIONS.forEach((position) => {
        $("#team-simulator-form").elements[position].value =
          result.lineup[position].id;
      });
      updateSimulatorScore();
      toast("추천 조합을 시뮬레이터에 적용했습니다.");
    }
    return;
  }
  const scorePlayerId =
    event.target.closest("[data-save-player-score]")?.dataset.savePlayerScore;
  if (scorePlayerId) {
    const input = document.querySelector(`[data-player-score="${scorePlayerId}"]`);
    const secondaryInput = document.querySelector(
      `[data-player-secondary-score="${scorePlayerId}"]`
    );
    try {
      await api(`/api/players/${scorePlayerId}/score`, {
        method: "PATCH",
        body: JSON.stringify({
          score: Number(input.value),
          secondary_score: secondaryInput ? Number(secondaryInput.value) : null,
        }),
      });
      toast("포지션별 점수를 수정했습니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  const selectCompetitionId =
    event.target.closest("[data-competition-select]")?.dataset.competitionSelect;
  const renameCompetitionId =
    event.target.closest("[data-competition-rename]")?.dataset.competitionRename;
  const deleteCompetitionButton =
    event.target.closest("[data-competition-delete]");
  if (renameCompetitionId) {
    const input = document.querySelector(`[data-competition-name-input="${renameCompetitionId}"]`);
    const name = (input?.value || "").trim();
    if (!name) {
      toast("대회 이름을 입력해주세요.", true);
      return;
    }
    try {
      await api(`/api/competitions/${renameCompetitionId}`, {
        method: "PATCH",
        body: JSON.stringify({ name }),
      });
      await refreshState({ force: true });
      toast("대회 이름을 수정했습니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (selectCompetitionId) {
    try {
      await api(`/api/competitions/${selectCompetitionId}/select`, {
        method: "POST",
      });
      memberRosterCache = null;
      await refreshState();
    } catch (error) { toast(error.message, true); }
    return;
  }
  if (deleteCompetitionButton) {
    const competitionId = deleteCompetitionButton.dataset.competitionDelete;
    const competitionName = deleteCompetitionButton.dataset.competitionName;
    if (!confirm(`"${competitionName}" 대회와 모든 관련 데이터를 삭제할까요?`)) {
      return;
    }
    try {
      await api(`/api/competitions/${competitionId}`, { method: "DELETE" });
      memberRosterCache = null;
      await refreshState();
      toast("대회와 관련 데이터를 삭제했습니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  const introPosition = event.target.closest("[data-intro-position]")?.dataset.introPosition;
  const requestedIntroIndex = event.target.closest("[data-intro-index]")?.dataset.introIndex;
  if (introPosition) {
    const players = sortedIntroPlayers();
    introIndex = players.findIndex((player) => player.primary_position === introPosition);
    introPlayerId = players[introIndex]?.id || null;
    renderIntro();
    return;
  }
  if (requestedIntroIndex !== undefined) {
    introIndex = Number(requestedIntroIndex);
    introPlayerId = sortedIntroPlayers()[introIndex]?.id || null;
    renderIntro();
    return;
  }
  const approveTeamId = event.target.closest("[data-team-approve]")?.dataset.teamApprove;
  const rejectTeamId = event.target.closest("[data-team-reject]")?.dataset.teamReject;
  const deleteTeamId = event.target.closest("[data-team-delete]")?.dataset.teamDelete;
  const teamActionButton = event.target.closest("[data-team-approve], [data-team-reject], [data-team-delete]");
  const winnerButton = event.target.closest("[data-match-winner]");
  const setTeamActionBusy = (busy) => {
    if (!teamActionButton) return;
    const card = teamActionButton.closest(".registered-team");
    card?.querySelectorAll("[data-team-approve], [data-team-reject], [data-team-delete]")
      .forEach((button) => { button.disabled = busy; });
    if (busy) {
      teamActionButton.dataset.originalText = teamActionButton.textContent;
      teamActionButton.textContent = "처리 중";
    } else if (teamActionButton.dataset.originalText) {
      teamActionButton.textContent = teamActionButton.dataset.originalText;
      delete teamActionButton.dataset.originalText;
    }
  };
  try {
    if (approveTeamId || rejectTeamId) {
      const teamId = approveTeamId || rejectTeamId;
      setTeamActionBusy(true);
      await api(`/api/tournament/teams/${teamId}/approval`, {
        method: "POST",
        body: JSON.stringify({ approved: Boolean(approveTeamId) }),
      });
      await refreshState();
      toast(approveTeamId ? "팀 신청을 승인했습니다." : "팀 신청을 반려했습니다.");
      return;
    }
    if (deleteTeamId) {
      setTeamActionBusy(true);
      await api(`/api/tournament/teams/${deleteTeamId}`, { method: "DELETE" });
      await refreshState();
      toast("팀 신청을 삭제했습니다.");
      return;
    }
    if (winnerButton) {
      await api("/api/tournament/winner", {
        method: "POST",
        body: JSON.stringify({
          round_index: Number(winnerButton.dataset.roundIndex),
          match_index: Number(winnerButton.dataset.matchIndex),
          team_id: winnerButton.dataset.matchWinner,
        }),
      });
      await refreshState();
      return;
    }
  } catch (error) {
    setTeamActionBusy(false);
    toast(error.message, true);
    return;
  }
  const captainId = event.target.dataset.deleteCaptain;
  const playerId = event.target.dataset.deletePlayer;
  try {
    if (captainId) await api(`/api/captains/${captainId}`, { method: "DELETE" });
    if (playerId) await api(`/api/players/${playerId}`, { method: "DELETE" });
  } catch (error) { toast(error.message, true); }
});

$("#intro-prev").addEventListener("click", () => moveIntro(-1));
$("#intro-next").addEventListener("click", () => moveIntro(1));
$("#score-intro-prev").addEventListener("click", () => moveScoreIntro(-1));
$("#score-intro-next").addEventListener("click", () => moveScoreIntro(1));
$("#intro-search").addEventListener("input", () =>
  renderPlayerSearch("#intro-search", "#intro-search-results", "intro")
);
$("#score-intro-search").addEventListener("input", () =>
  renderPlayerSearch(
    "#score-intro-search",
    "#score-intro-search-results",
    "score-intro"
  )
);
$("#intro-search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const match = matchingIntroPlayers(event.currentTarget.value)[0];
  if (match) selectSearchedPlayer(match.id, "intro");
});
$("#score-intro-search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const match = matchingIntroPlayers(event.currentTarget.value)[0];
  if (match) selectSearchedPlayer(match.id, "score-intro");
});
document.addEventListener("keydown", (event) => {
  if (currentView !== "intro" || !state?.viewer?.authenticated) return;
  if (event.key === "ArrowLeft") moveIntro(-1);
  if (event.key === "ArrowRight") moveIntro(1);
});

$("#start-button").addEventListener("click", async () => {
  await enterAuctionView();
});
$("#start-timer-button").addEventListener("click", () =>
  api("/api/auction/timer/start", { method: "POST" })
    .then(() => toast("현재 후보의 타이머를 시작했습니다."))
    .catch((e) => toast(e.message, true)));
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

function renderScrimTeams() {
  const list = $("#team-list");
  const teams = state.tournament.teams;
  if (!teams.length) {
    selectedScrimTeamId = null;
    list.innerHTML = '<div class="empty-state">아직 등록된 팀이 없습니다.</div>';
    return;
  }
  if (selectedScrimTeamId && !teams.some((team) => team.id === selectedScrimTeamId)) {
    selectedScrimTeamId = null;
  }
  list.innerHTML = teams.map((team) => `
    <article class="team-item scrim-team-card${team.id === selectedScrimTeamId ? " selected" : ""}" data-scrim-team-id="${team.id}">
      <div class="team-head">
        <div>
          <strong>${escapeHtml(team.name)}</strong>
          <div class="meta">${team.status === "approved" ? "승인" : team.status === "rejected" ? "반려" : "승인 대기"} · 총 ${team.total_score}점</div>
        </div>
        <span class="team-status ${team.status}">${team.can_manage_scrim_result ? "경기 결과 등록 가능" : "읽기 전용"}</span>
      </div>
      <div class="member-list">
        ${POSITIONS.map((position) => {
          const player = playerById(team.members[position]);
          return `<span>${position} · ${escapeHtml(player?.name || "-")}</span>`;
        }).join("")}
      </div>
    </article>
  `).join("");
}

function manageableScrimTeams() {
  return state.tournament.teams.filter((team) => team.can_manage_scrim_result);
}

function renderScrimResultForm() {
  const form = $("#scrim-result-form");
  const locked = $("#scrim-result-locked");
  const allTeams = state.tournament.teams.filter((team) => team.status === "approved");
  const canManage = manageableScrimTeams().length > 0;
  form.classList.toggle("hidden", !canManage || allTeams.length < 2);
  locked.classList.toggle("hidden", canManage && allTeams.length >= 2);
  if (!canManage || allTeams.length < 2) return;
  ["team_a_id", "team_b_id"].forEach((name, index) => {
    const select = form.elements[name];
    const selected = select.value;
    select.innerHTML = allTeams.map((team) =>
      `<option value="${team.id}">${escapeHtml(team.name)}</option>`
    ).join("");
    if (allTeams.some((team) => team.id === selected)) select.value = selected;
    else select.selectedIndex = Math.min(index, allTeams.length - 1);
  });
  if (!form.elements.match_date.value) {
    form.elements.match_date.value = new Date().toISOString().slice(0, 10);
  }
}

function scrimStatsByTeam() {
  const stats = new Map(state.tournament.teams.map((team) => [team.id, {
    team, setWins: 0, setLosses: 0, seriesWins: 0, seriesLosses: 0,
    seriesDraws: 0, bo3Wins: 0, bo3Losses: 0, bo3Draws: 0,
    bo5Wins: 0, bo5Losses: 0, bo5Draws: 0,
  }]));
  (state.scrim_results || []).forEach((result) => {
    const a = stats.get(result.team_a_id);
    const b = stats.get(result.team_b_id);
    if (!a || !b) return;
    a.setWins += Number(result.team_a_score);
    a.setLosses += Number(result.team_b_score);
    b.setWins += Number(result.team_b_score);
    b.setLosses += Number(result.team_a_score);
    const draw = Number(result.team_a_score) === Number(result.team_b_score);
    const aWon = result.winner_team_id === result.team_a_id;
    a.seriesWins += !draw && aWon ? 1 : 0;
    a.seriesLosses += !draw && !aWon ? 1 : 0;
    a.seriesDraws += draw ? 1 : 0;
    b.seriesWins += !draw && !aWon ? 1 : 0;
    b.seriesLosses += !draw && aWon ? 1 : 0;
    b.seriesDraws += draw ? 1 : 0;
    const prefix = Number(result.best_of || 3) === 5 ? "bo5" : "bo3";
    a[`${prefix}Wins`] += !draw && aWon ? 1 : 0;
    a[`${prefix}Losses`] += !draw && !aWon ? 1 : 0;
    a[`${prefix}Draws`] += draw ? 1 : 0;
    b[`${prefix}Wins`] += !draw && !aWon ? 1 : 0;
    b[`${prefix}Losses`] += !draw && aWon ? 1 : 0;
    b[`${prefix}Draws`] += draw ? 1 : 0;
  });
  return [...stats.values()].sort((left, right) => {
    const leftRate = left.seriesWins / Math.max(1, left.seriesWins + left.seriesLosses);
    const rightRate = right.seriesWins / Math.max(1, right.seriesWins + right.seriesLosses);
    return rightRate - leftRate || right.seriesWins - left.seriesWins;
  });
}

function percent(wins, losses) {
  const total = wins + losses;
  return total ? `${Math.round(wins / total * 100)}%` : "-";
}

function renderScrimWinrates() {
  const list = $("#scrim-winrate-list");
  const stats = scrimStatsByTeam();
  list.innerHTML = stats.length ? stats.map((item, index) => `
    <article class="scrim-winrate-card">
      <div class="scrim-winrate-head">
        <strong>${index + 1}. ${escapeHtml(item.team.name)}</strong>
        <b>${percent(item.seriesWins, item.seriesLosses)}</b>
      </div>
      <div class="scrim-winrate-records">
        <span>세트 승률<strong>${percent(item.setWins, item.setLosses)} · ${item.setWins}승 ${item.setLosses}패</strong></span>
        <span>시리즈 승률<strong>${item.seriesWins}승 ${item.seriesDraws}무 ${item.seriesLosses}패</strong></span>
        <span>BO3<strong>${item.bo3Wins}승 ${item.bo3Draws}무 ${item.bo3Losses}패</strong></span>
        <span>BO5<strong>${item.bo5Wins}승 ${item.bo5Draws}무 ${item.bo5Losses}패</strong></span>
      </div>
    </article>
  `).join("") : '<div class="empty-state">등록된 팀이 없습니다.</div>';
}

function renderScrimResults() {
  const list = $("#scrim-result-list");
  const teamById = (id) => state.tournament.teams.find((team) => team.id === id);
  const results = [...(state.scrim_results || [])]
    .filter((result) => !selectedScrimTeamId
      || result.team_a_id === selectedScrimTeamId
      || result.team_b_id === selectedScrimTeamId)
    .sort((left, right) => String(right.match_date).localeCompare(String(left.match_date)));
  if (!results.length) {
    const selectedTeam = selectedScrimTeamId ? teamById(selectedScrimTeamId) : null;
    list.innerHTML = `<div class="empty-state">${selectedTeam ? `${escapeHtml(selectedTeam.name)} 팀의 등록된 결과가 없습니다.` : "아직 등록된 결과가 없습니다."}</div>`;
    return;
  }
  list.innerHTML = results.map((result) => {
    const teamA = teamById(result.team_a_id);
    const teamB = teamById(result.team_b_id);
    const canEdit = Boolean(teamA?.can_manage_scrim_result || teamB?.can_manage_scrim_result);
    return `
      <article class="team-item scrim-result-item">
        <div class="team-head">
          <div>
            <strong>${escapeHtml(teamA?.name || "삭제된 팀")} ${result.team_a_score} : ${result.team_b_score} ${escapeHtml(teamB?.name || "삭제된 팀")}</strong>
            <div class="meta">${escapeHtml(result.match_date)} · BO${result.best_of || 3}${result.memo ? ` · ${escapeHtml(result.memo)}` : ""}</div>
          </div>
          ${canEdit ? `<button class="ghost" type="button" data-edit-scrim-result="${result.id}">수정</button>` : ""}
        </div>
      </article>`;
  }).join("");
}

function renderScrimAdminUsers(users) {
  const list = $("#admin-user-list");
  if (!users.length) {
    list.innerHTML = '<div class="empty-state">검색 결과가 없습니다.</div>';
    return;
  }
  list.innerHTML = users.map((user) => `
    <article class="admin-user">
      <div class="admin-user-head">
        <div>
          <strong>${escapeHtml(user.name)}</strong>
          <div class="meta">본 ${escapeHtml(user.riot_id)}${user.secondary_riot_id ? ` · 부 ${escapeHtml(user.secondary_riot_id)}` : ""} · ${user.role}</div>
        </div>
        <span class="user-approval ${user.approved ? "approved" : "pending"}">
          ${user.role === "ADMIN" ? "강사님" : user.approved ? "참가자" : "승인 대기"}
        </span>
      </div>
      ${user.role !== "ADMIN" ? `
        <div class="admin-user-actions">
          <button class="${user.approved ? "ghost" : "accent"}" type="button" data-user-approval="${user.id}" data-approved="${user.approved ? "false" : "true"}">
            ${user.approved ? "승인 해제" : "참가 승인"}
          </button>
          <button class="remove" type="button" data-user-delete="${user.id}" data-user-name="${escapeHtml(user.name)}">삭제</button>
        </div>
      ` : ""}
      <form data-password-reset="${user.id}">
        <input name="new_password" type="password" minlength="4" maxlength="128" placeholder="새 비밀번호" required />
        <button class="ghost" type="submit">재설정</button>
      </form>
    </article>
  `).join("");
}

async function loadScrimTeams() {
  renderScrimTeams();
  renderScrimResultForm();
  renderScrimWinrates();
  renderScrimResults();
  renderScrimRoomTabs();
}

async function searchScrimUsers(query) {
  if (state.viewer.role !== "host") return;
  const data = await api(`/api/scrim/admin/users?query=${encodeURIComponent(query)}`);
  renderScrimAdminUsers(data.users);
}

async function resetMemberPassword(form) {
  await api(`/api/scrim/admin/users/${form.dataset.passwordReset}/password`, {
    method: "PATCH",
    body: JSON.stringify(Object.fromEntries(new FormData(form))),
  });
  form.reset();
  toast("비밀번호를 재설정했습니다.");
}

async function setMemberApproval(button) {
  await api(`/api/scrim/admin/users/${button.dataset.userApproval}/approval`, {
    method: "PATCH",
    body: JSON.stringify({ approved: button.dataset.approved === "true" }),
  });
  if (currentView === "members") {
    await reloadMembers();
  } else {
    await searchScrimUsers($("#admin-search-form").elements.query.value || "");
  }
  toast(button.dataset.approved === "true" ? "회원을 승인했습니다." : "승인을 해제했습니다.");
}

async function deleteScrimUser(button) {
  const name = button.dataset.userName || "선택한 회원";
  if (!confirm(`${name} 계정을 삭제할까요? 삭제한 계정의 Riot ID는 다시 등록할 수 있습니다.`)) return;
  await api(`/api/scrim/admin/users/${button.dataset.userDelete}`, { method: "DELETE" });
  if (currentView === "members") {
    await reloadMembers();
  } else {
    await searchScrimUsers($("#admin-search-form").elements.query.value || "");
  }
  toast("회원 계정을 삭제했습니다.");
}

async function loadScrimData() {
  try {
    await loadScrimTeams();
    if (state.viewer.role === "host") await searchScrimUsers("");
  } catch (error) {
    toast(error.message, true);
  }
}

$("#team-create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target));
  payload.game_count = Number(payload.game_count || 0);
  payload.top_rank ||= null;
  try {
    await api("/api/scrim/teams", { method: "POST", body: JSON.stringify(payload) });
    event.target.reset();
    await loadScrimTeams();
    toast("팀을 만들었습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#team-join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/scrim/teams/join", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(event.target))),
    });
    event.target.reset();
    await loadScrimTeams();
    toast("팀에 가입했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#refresh-teams").addEventListener("click", () =>
  loadScrimTeams().then(() => toast("팀 목록을 새로고침했습니다.")).catch((error) => toast(error.message, true))
);

$("#team-list").addEventListener("click", (event) => {
  const card = event.target.closest("[data-scrim-team-id]");
  if (!card) return;
  selectedScrimTeamId =
    selectedScrimTeamId === card.dataset.scrimTeamId ? null : card.dataset.scrimTeamId;
  renderScrimTeams();
  renderScrimResultForm();
  renderScrimResults();
  $("#scrim-result-list").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("#scrim-result-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  const resultId = data.result_id;
  delete data.result_id;
  data.best_of = Number(data.best_of);
  data.team_a_score = Number(data.team_a_score);
  data.team_b_score = Number(data.team_b_score);
  data.memo ||= null;
  try {
    await api(
      resultId ? `/api/scrim/results/${resultId}` : "/api/scrim/results",
      {
        method: resultId ? "PUT" : "POST",
        body: JSON.stringify(data),
      }
    );
    form.reset();
    form.elements.result_id.value = "";
    $("#cancel-result-edit").classList.add("hidden");
    await refreshState();
    toast(resultId ? "결과를 수정했습니다." : "결과를 등록했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#cancel-result-edit").addEventListener("click", () => {
  $("#scrim-result-form").reset();
  $("#scrim-result-form").elements.result_id.value = "";
  $("#cancel-result-edit").classList.add("hidden");
  renderScrimResultForm();
});

$("#scrim-result-list").addEventListener("click", (event) => {
  const resultId = event.target.closest("[data-edit-scrim-result]")?.dataset.editScrimResult;
  if (!resultId) return;
  const result = (state.scrim_results || []).find((item) => item.id === resultId);
  if (!result) return;
  const form = $("#scrim-result-form");
  renderScrimResultForm();
  $("#scrim-result-entry").open = true;
  form.elements.result_id.value = result.id;
  form.elements.match_date.value = result.match_date;
  form.elements.best_of.value = result.best_of || 3;
  form.elements.team_a_id.value = result.team_a_id;
  form.elements.team_b_id.value = result.team_b_id;
  form.elements.team_a_score.value = result.team_a_score;
  form.elements.team_b_score.value = result.team_b_score;
  form.elements.memo.value = result.memo || "";
  $("#cancel-result-edit").classList.remove("hidden");
  form.scrollIntoView({ behavior: "smooth", block: "center" });
});

$("#admin-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await searchScrimUsers(new FormData(event.target).get("query") || "");
  } catch (error) { toast(error.message, true); }
});

$("#admin-user-list").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-password-reset]");
  if (!form) return;
  event.preventDefault();
  try {
    await resetMemberPassword(form);
  } catch (error) { toast(error.message, true); }
});

$("#admin-user-list").addEventListener("click", async (event) => {
  const deleteButton = event.target.closest("[data-user-delete]");
  if (deleteButton) {
    try {
      await deleteScrimUser(deleteButton);
    } catch (error) { toast(error.message, true); }
    return;
  }
  const button = event.target.closest("[data-user-approval]");
  if (!button) return;
  try {
    await setMemberApproval(button);
  } catch (error) { toast(error.message, true); }
});

$("#member-create-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target));
  payload.password = "1234";
  payload.secondary_riot_id ||= null;
  try {
    await api("/api/scrim/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    event.target.reset();
    await reloadMembers();
    toast("회원 계정을 생성했습니다. 기본 비밀번호는 1234입니다.");
  } catch (error) { toast(error.message, true); }
});

$("#member-search-form").addEventListener("input", async (event) => {
  if (!event.target.matches('input[name="query"]')) return;
  rosterPage = 1;
  memberRosterCache = null;
  window.clearTimeout(window.memberSearchTimer);
  window.memberSearchTimer = window.setTimeout(loadMembers, 180);
});

$("#member-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  rosterPage = 1;
  memberRosterCache = null;
  await loadMembers();
});

$("#add-roster-member-button")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  rosterCreateOpen = !rosterCreateOpen;
  button.classList.toggle("active", rosterCreateOpen);
  await loadMembers();
  if (rosterCreateOpen) {
    $("#member-list [data-roster-create] input[name='name']")?.focus();
  }
});

$("#save-all-roster-button").addEventListener("click", async () => {
  if (!dirtyRosterIds.size) {
    toast("변경된 명단이 없습니다.");
    return;
  }
  const rows = [...dirtyRosterIds].map((id) => {
    const entry = memberRosterCache.entries.find((item) => item.id === id);
    return Object.fromEntries([
      ["id", id],
      ...ROSTER_EDIT_FIELDS.map((field) => [field, entry[field] === "" ? null : entry[field]]),
    ]);
  });
  const button = $("#save-all-roster-button");
  button.disabled = true;
  button.textContent = `${rows.length}명 저장 중...`;
  try {
    await api("/api/roster", {
      method: "PATCH",
      body: JSON.stringify({ rows }),
    });
    await reloadMembers();
    toast(`${rows.length}명의 명단을 한 번에 저장했습니다.`);
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = "변경사항 전체 저장";
  }
});

$("#member-list").addEventListener("input", (event) => {
  const form = event.target.closest("[data-roster-entry]");
  if (!form) return;
  form.classList.add("dirty");
  dirtyRosterIds.add(Number(form.dataset.rosterEntry));
  const cached = memberRosterCache?.entries.find(
    (entry) => entry.id === Number(form.dataset.rosterEntry)
  );
  if (cached && event.target.name) cached[event.target.name] = event.target.value;
});

$("#member-list").addEventListener("submit", async (event) => {
  const createForm = event.target.closest("[data-roster-create]");
  if (createForm) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(createForm));
    Object.keys(payload).forEach((key) => {
      if (payload[key] === "") payload[key] = null;
    });
    if (!payload.name || !String(payload.name).trim()) {
      toast("이름을 입력해 주세요.", true);
      createForm.elements.name?.focus();
      return;
    }
    try {
      await api("/api/roster", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      rosterCreateOpen = false;
      $("#add-roster-member-button")?.classList.remove("active");
      rosterFilter = "all";
      document.querySelectorAll("[data-roster-filter]").forEach((item) => {
        item.classList.toggle("active", item.dataset.rosterFilter === "all");
      });
      rosterPage = 1;
      await reloadMembers();
      toast("멤버를 추가했습니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  const rosterForm = event.target.closest("[data-roster-entry]");
  if (rosterForm) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(rosterForm));
    Object.keys(payload).forEach((key) => {
      if (payload[key] === "") payload[key] = null;
    });
    try {
      const updated = await api(`/api/roster/${rosterForm.dataset.rosterEntry}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const id = Number(rosterForm.dataset.rosterEntry);
      const cached = memberRosterCache?.entries.find((entry) => entry.id === id);
      if (cached) Object.assign(cached, updated);
      dirtyRosterIds.delete(id);
      await loadMembers();
      toast("명단을 저장했습니다. Riot ID가 있으면 계정도 발급됩니다.");
    } catch (error) { toast(error.message, true); }
    return;
  }
  const form = event.target.closest("[data-password-reset]");
  if (!form) return;
  event.preventDefault();
  try {
    await resetMemberPassword(form);
  } catch (error) { toast(error.message, true); }
});

$("#member-list").addEventListener("click", async (event) => {
  const rosterDeleteButton = event.target.closest("[data-roster-delete]");
  if (rosterDeleteButton) {
    const name = rosterDeleteButton.dataset.rosterName || "선택한 명단";
    if (!confirm(`${name} 명단을 삭제할까요? 연결된 계정이 더 이상 쓰이지 않으면 함께 비활성화됩니다.`)) {
      return;
    }
    try {
      await api(`/api/roster/${rosterDeleteButton.dataset.rosterDelete}`, {
        method: "DELETE",
      });
      await reloadMembers();
      toast("명단을 삭제했습니다.");
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  if (event.target.closest("[data-roster-create-cancel]")) {
    rosterCreateOpen = false;
    $("#add-roster-member-button")?.classList.remove("active");
    await loadMembers();
    return;
  }
  const riotFillButton = event.target.closest("[data-roster-riot-fill]");
  if (riotFillButton) {
    const form = riotFillButton.closest("[data-roster-entry], [data-roster-create]");
    if (!form) return;
    try {
      await autofillRosterFromRiot(form, riotFillButton);
    } catch (error) {
      toast(error.message, true);
    }
    return;
  }
  const paymentButton = event.target.closest("[data-payment-toggle]");
  if (paymentButton) {
    const form = paymentButton.closest("[data-roster-entry]");
    const input = form?.elements.payment_status;
    if (!form || !input) return;
    input.value = input.value === "O" ? "X" : "O";
    paymentButton.textContent = input.value;
    paymentButton.classList.toggle("paid", input.value === "O");
    paymentButton.classList.toggle("unpaid", input.value !== "O");
    form.classList.add("dirty");
    const id = Number(form.dataset.rosterEntry);
    dirtyRosterIds.add(id);
    const cached = memberRosterCache?.entries.find((entry) => entry.id === id);
    if (cached) cached.payment_status = input.value;
    return;
  }
  const participationButton = event.target.closest("[data-participation-count]");
  if (participationButton) {
    const id = participationButton.dataset.participationCount;
    document.querySelectorAll(".participation-popover").forEach((popover) => {
      popover.classList.toggle(
        "hidden",
        popover.dataset.participationPopover !== id || !popover.classList.contains("hidden")
      );
    });
    return;
  }
  const button = event.target.closest("[data-user-approval]");
  if (!button) return;
  try {
    await setMemberApproval(button);
  } catch (error) { toast(error.message, true); }
});

document.addEventListener("click", async (event) => {
  const pageButton = event.target.closest("[data-roster-page]");
  if (!pageButton) return;
  rosterPage = Number(pageButton.dataset.rosterPage);
  memberRosterCache = null;
  await loadMembers();
});

document.addEventListener("click", async (event) => {
  if (event.target.id !== "add-riot-preview-player" || !riotPreviewData) return;
  try {
    await api("/api/players/riot", {
      method: "POST",
      body: JSON.stringify(riotPreviewData.form),
    });
    $("#riot-player-form").reset();
    resetPositionSlots($("#riot-player-form"));
    updateSecondaryScoreField($("#riot-player-form"));
    $("#riot-player-preview")?.remove();
    riotPreviewData = null;
    toast("Riot 정보로 참가자를 추가했습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

document.querySelectorAll("[data-roster-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    rosterFilter = button.dataset.rosterFilter;
    rosterPage = 1;
    memberRosterCache = null;
    document.querySelectorAll("[data-roster-filter]").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    await loadMembers();
  });
});

$("#mypage-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = Object.fromEntries(new FormData(event.target));
  payload.secondary_riot_id ||= null;
  payload.nickname ||= null;
  if (!payload.password) delete payload.password;
  try {
    await api("/api/scrim/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    toast("마이페이지를 저장했습니다.");
    await refreshState();
  } catch (error) { toast(error.message, true); }
});

setInterval(updateTimer, 100);
async function initializeApp() {
  const data = await api("/api/state");
  state = data;
  stateSignature = meaningfulStateSignature(data);
  authPromptOpen = !Boolean(data.viewer?.authenticated);
  setAuthMode("login");
  render();
  connectSocket();
}

initializeApp().catch((error) => {
  $("#login-status").className = "login-status error";
  $("#login-status").textContent = `초기화 실패: ${error.message}`;
});
