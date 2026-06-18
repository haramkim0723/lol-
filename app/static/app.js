const POSITIONS = ["TOP", "JUG", "MID", "ADC", "SUP"];
const POSITION_NAMES = {
  TOP: "탑", JUG: "정글", MID: "미드", ADC: "원딜", SUP: "서폿",
};
const TIER_DIVISIONS = { 1: "I", 2: "II", 3: "III", 4: "IV" };
const DIVISION_TIERS = new Set([
  "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND",
]);
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
let currentView = location.pathname === "/score-players"
  ? "score-intro"
  : location.pathname === "/team-simulator"
  ? "team-simulator"
  : location.pathname === "/team-register"
    ? "team-register"
  : location.pathname === "/tournament"
    ? "tournament"
    : "intro";
let loginRole = "spectator";
let introIndex = 0;
let introPlayerId = null;
let scoreIntroIndex = 0;
let scoreIntroPlayerId = null;
let toastTimer = null;
let stateSignature = "";

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

function scoreForPosition(player, position) {
  if (
    player?.secondary_position === position &&
    player?.primary_position !== position
  ) {
    return Number(player.secondary_score ?? player.score ?? 0);
  }
  return Number(player?.score || 0);
}

function setView(view) {
  if (view === "setup" && state.viewer.role !== "host") {
    view = "intro";
  }
  if (view === "auction" && state.auction.status === "setup") {
    toast("강사님이 아직 이 대회의 경매를 열지 않았습니다.");
    view = "intro";
  }
  currentView = view;
  $("#intro-panel").classList.toggle("hidden", view !== "intro");
  $("#setup-panel").classList.toggle("hidden", view !== "setup");
  $("#score-intro-panel").classList.toggle("hidden", view !== "score-intro");
  $("#team-simulator-panel").classList.toggle("hidden", view !== "team-simulator");
  $("#team-register-panel").classList.toggle("hidden", view !== "team-register");
  $("#tournament-panel").classList.toggle("hidden", view !== "tournament");
  $("#auction-panel").classList.toggle("hidden", view !== "auction");
  $$("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  const path = view === "team-simulator" ? "/team-simulator"
    : view === "score-intro" ? "/score-players"
    : view === "team-register" ? "/team-register"
    : view === "tournament" ? "/tournament" : "/";
  if (location.pathname !== path) {
    history.pushState({ view }, "", path);
  }
}

async function enterAuctionView() {
  if (state.auction.status === "setup") {
    if (state.viewer.role !== "host") {
      toast("강사님이 아직 이 대회의 경매를 열지 않았습니다.");
      return;
    }
    try {
      await api("/api/auction/start", { method: "POST" });
      state = await api("/api/state");
      stateSignature = meaningfulStateSignature(state);
      render();
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
  const publicPage = ["/score-players", "/team-simulator", "/team-register", "/tournament"].includes(location.pathname);
  $("#login-overlay").classList.toggle("hidden", viewer.authenticated || publicPage);
  $("#main-nav").classList.toggle("hidden", !viewer.authenticated && !publicPage);
  $("#logout-button").classList.toggle("hidden", !viewer.authenticated);
  $("#setup-nav").classList.toggle("hidden", viewer.role !== "host");
  $("#competition-switcher").classList.toggle(
    "hidden",
    !viewer.authenticated && !publicPage
  );

  let label = "참가자";
  if (viewer.role === "host") label = "강사님";
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
          <small>${competition.mode === "auction" ? "경매 대회" : "점수제 대회"} · 참가자 ${competition.player_count}명 · 팀 ${competition.team_count}개</small>
        </div>
        <div class="competition-actions">
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

function applyCompetitionMode() {
  const isAuction = (activeCompetition()?.mode || "auction") === "auction";
  $$('[data-view="intro"], [data-view="auction"]').forEach((button) => {
    button.classList.toggle("hidden", !isAuction);
  });
  $$('[data-view="score-intro"], [data-view="team-simulator"], [data-view="team-register"], [data-view="tournament"]').forEach((button) => {
    button.classList.toggle("hidden", isAuction);
  });
  $('[data-login-role="captain"]').classList.toggle("hidden", !isAuction);
  $(".tournament-score-settings").classList.toggle("hidden", isAuction);
  $(".settings-panel").classList.toggle("hidden", !isAuction);
  $(".captain-panel").classList.toggle("hidden", !isAuction);

  const allowedViews = isAuction
    ? ["intro", "setup", "auction"]
    : ["setup", "score-intro", "team-simulator", "team-register", "tournament"];
  if (!allowedViews.includes(currentView)) {
    currentView = isAuction ? "intro" : "tournament";
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
  $("#score-intro-progress").innerHTML = players.map((item, index) =>
    `<button type="button" class="${index === scoreIntroIndex ? "active" : ""}" data-score-intro-index="${index}" aria-label="${escapeHtml(item.name)}"></button>`
  ).join("");
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
  $("#intro-progress").innerHTML = players.map((item, index) =>
    `<button type="button" class="${index === introIndex ? "active" : ""}" data-intro-index="${index}" aria-label="${escapeHtml(item.name)}"></button>`
  ).join("");
  $("#intro-prev").disabled = introIndex === 0;
  $("#intro-next").disabled = introIndex === players.length - 1;
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

function renderSetup() {
  if (state.viewer.role !== "host") return;
  $("#teacher-score-limit-input").value = state.tournament.score_limit;
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
  const registrationOpen = tournament.status === "registration";
  $("#tournament-status").textContent =
    tournament.status === "registration" ? "TEAM REGISTRATION"
      : tournament.status === "running" ? "TOURNAMENT LIVE" : "TOURNAMENT FINISHED";
  $("#tournament-team-form").classList.toggle("hidden", !registrationOpen);
  $("#team-registration-closed").classList.toggle("hidden", registrationOpen);
  $("#tournament-registration-area").classList.toggle("hidden", !registrationOpen);
  $("#team-registration-closed-tournament").classList.toggle("hidden", registrationOpen);
  $("#tournament-bracket-section").classList.toggle("hidden", registrationOpen);
  $("#tournament-host-controls").classList.toggle("hidden", !isHost);
  $("#tournament-score-limit-input").value = tournament.score_limit;
  $("#team-score-limit").textContent = tournament.score_limit;
  $("#simulator-score-limit").textContent = tournament.score_limit;
  $("#open-team-register").classList.toggle("hidden", !registrationOpen);

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

function renderTeamSelectors(formSelector, containerSelector, initial = null) {
  const form = $(formSelector);
  const isSimulator = formSelector === "#team-simulator-form";
  const currentSelections = Object.fromEntries(
    POSITIONS.map((position) => [
      position,
      form.elements[position]?.value || initial?.[position] || "",
    ])
  );
  $(containerSelector).innerHTML = POSITIONS.map((position) => {
    const primaryCandidates = state.players
      .filter((player) => player.primary_position === position)
      .sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));
    const secondaryCandidates = state.players
      .filter((player) =>
        player.primary_position !== position &&
        player.secondary_position === position
      )
      .sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));
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
  $("#tournament-bracket").innerHTML = tournament.rounds.map((round, roundIndex) => `
    <section class="bracket-round">
      <div class="bracket-round-title">${roundIndex === tournament.rounds.length - 1 ? "FINAL" : `ROUND ${roundIndex + 1}`}</div>
      ${round.map((match, matchIndex) => `
        <div class="bracket-match">
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

function render() {
  $("#room-title").textContent = state.settings.room_name;
  document.title = `${state.settings.room_name} · LoL Auction`;
  $("#deployment-warning").classList.toggle(
    "hidden",
    !state.deployment?.serverless || state.deployment?.persistent
  );
  renderRole();
  renderCompetitions();
  applyCompetitionMode();
  renderIntro();
  renderSetup();
  renderTournament();
  renderAuction();
  if (
    state.viewer.role !== "host"
    && state.auction.status === "setup"
    && ["setup", "auction"].includes(currentView)
  ) {
    currentView = "intro";
  }
  setView(currentView);
}

function connectSocket() {
  if (location.hostname.endsWith(".vercel.app")) {
    $("#socket-dot").classList.add("online");
    $("#socket-text").textContent = "자동 갱신";
    setInterval(pollState, 1000);
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
  try {
    const data = await api("/api/state");
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
  }
}

$$(".position-select").forEach((select) => {
  select.innerHTML = positionOptions(select.classList.contains("optional"));
});
["#manual-player-form", "#riot-player-form"].forEach((selector) => {
  const form = $(selector);
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
    setView(button.dataset.view);
  });
});

window.addEventListener("popstate", () => {
  currentView = location.pathname === "/score-players"
    ? "score-intro"
    : location.pathname === "/team-simulator"
    ? "team-simulator"
    : location.pathname === "/team-register" ? "team-register"
    : location.pathname === "/tournament" ? "tournament" : "intro";
  if (state) setView(currentView);
});

$$(".login-tab").forEach((button) => button.addEventListener("click", () => {
  loginRole = button.dataset.loginRole;
  $$(".login-tab").forEach((tab) => tab.classList.toggle("active", tab === button));
  $("#captain-login-fields").classList.toggle("hidden", loginRole !== "captain");
  $("#pin-login-field").classList.toggle("hidden", loginRole === "spectator");
  $("#login-submit").textContent =
    loginRole === "host" ? "강사님으로 입장"
      : loginRole === "captain" ? "팀장으로 입장" : "참가자로 입장";
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
  location.href = "/";
});

$("#competition-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    await api("/api/competitions", {
      method: "POST",
      body: JSON.stringify(data),
    });
    event.target.reset();
    toast("새 대회를 만들고 현재 대회로 선택했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#teacher-pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  if (data.new_pin !== data.confirm_pin) {
    toast("새 PIN 확인이 일치하지 않습니다.", true);
    return;
  }
  try {
    await api("/api/teacher/pin", {
      method: "POST",
      body: JSON.stringify({
        current_pin: data.current_pin,
        new_pin: data.new_pin,
      }),
    });
    event.target.reset();
    alert("강사님 PIN이 변경되었습니다. 새 PIN으로 다시 입장해 주세요.");
    location.href = "/";
  } catch (error) { toast(error.message, true); }
});

$("#teacher-score-limit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const scoreLimit = Number(
    new FormData(event.target).get("score_limit")
  );
  try {
    await api("/api/tournament/settings", {
      method: "PUT",
      body: JSON.stringify({ score_limit: scoreLimit }),
    });
    toast(`점수제 팀 총점을 ${scoreLimit}점으로 설정했습니다.`);
  } catch (error) { toast(error.message, true); }
});

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
  } catch (error) { toast(error.message, true); }
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
    updateSecondaryScoreField(event.target);
  } catch (error) { toast(error.message, true); }
});

$("#riot-player-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.secondary_position ||= null;
  data.score = Number(data.score || 0);
  data.secondary_score = data.secondary_position
    ? Number(data.secondary_score || data.score || 0)
    : data.score;
  const button = event.target.querySelector("button");
  button.disabled = true;
  button.textContent = "조회 중...";
  try {
    await api("/api/players/riot", { method: "POST", body: JSON.stringify(data) });
    event.target.reset();
    updateSecondaryScoreField(event.target);
    toast("Riot 정보를 확인해 추가했습니다.");
  } catch (error) { toast(error.message, true); }
  finally {
    button.disabled = false;
    button.textContent = "티어 조회 후 추가";
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
  api("/api/tournament/recommend", {
    method: "POST",
    body: JSON.stringify({ locked, limit: 12 }),
  }).then((result) => {
    renderSimulatorRecommendations(result.recommendations);
  }).catch((error) => toast(error.message, true));
});
$("#save-tournament-settings").addEventListener("click", async () => {
  try {
    await api("/api/tournament/settings", {
      method: "PUT",
      body: JSON.stringify({ score_limit: Number($("#tournament-score-limit-input").value) }),
    });
    toast("팀 총점 제한을 저장했습니다.");
  } catch (error) { toast(error.message, true); }
});
$("#start-tournament-button").addEventListener("click", async () => {
  try {
    await api("/api/tournament/start", { method: "POST" });
    toast("대진표를 생성했습니다.");
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
  const deleteCompetitionButton =
    event.target.closest("[data-competition-delete]");
  if (selectCompetitionId) {
    try {
      await api(`/api/competitions/${selectCompetitionId}/select`, {
        method: "POST",
      });
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
  const winnerButton = event.target.closest("[data-match-winner]");
  try {
    if (approveTeamId || rejectTeamId) {
      const teamId = approveTeamId || rejectTeamId;
      await api(`/api/tournament/teams/${teamId}/approval`, {
        method: "POST",
        body: JSON.stringify({ approved: Boolean(approveTeamId) }),
      });
      return;
    }
    if (deleteTeamId) {
      await api(`/api/tournament/teams/${deleteTeamId}`, { method: "DELETE" });
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
      return;
    }
  } catch (error) {
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

setInterval(updateTimer, 100);
api("/api/state").then((data) => {
  state = data;
  stateSignature = meaningfulStateSignature(data);
  render();
});
connectSocket();
