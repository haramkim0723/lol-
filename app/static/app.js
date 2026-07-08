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
  : location.pathname === "/participation"
    ? "participation"
  : location.pathname === "/members"
    ? "members"
  : location.pathname === "/mypage"
    ? "mypage"
  : location.pathname === "/scrim"
    ? "scrim"
    : "intro";
let authPromptOpen = false;
let authMode = "login";
let introIndex = 0;
let introPlayerId = null;
let scoreIntroIndex = 0;
let scoreIntroPlayerId = null;
let toastTimer = null;
let stateSignature = "";
let riotPreviewData = null;
let rosterPage = 1;

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
  $("#participation-panel").classList.toggle("hidden", view !== "participation");
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
    : view === "members" ? "/members"
    : view === "mypage" ? "/mypage"
    : view === "scrim" ? "/scrim" : "/";
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

function movePlayerRegistrationToMembers() {
  const slot = $("#member-player-registration-slot");
  const panel = $(".players-panel");
  if (slot && panel && !slot.contains(panel)) {
    slot.appendChild(panel);
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
  $$('[data-view="mypage"]').forEach((button) =>
    button.classList.toggle("hidden", !viewer.authenticated)
  );
  $("#competition-switcher").classList.toggle("hidden", !browsable);

  let label = "관전자";
  if (viewer.role === "host") label = "강사님";
  if (viewer.role === "participant") label = "참가자";
  if (viewer.role === "captain") {
    label = `${captainById(viewer.captain_id)?.name || "팀장"} 팀`;
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
  $$('[data-view="score-intro"], [data-view="team-simulator"], [data-view="team-register"], [data-view="tournament"], [data-view="participation"], [data-view="members"], [data-view="mypage"]').forEach((button) => {
    button.classList.toggle("hidden", isAuction);
  });
  $(".tournament-score-settings").classList.toggle("hidden", isAuction);
  $(".settings-panel").classList.toggle("hidden", !isAuction);
  $(".captain-panel").classList.toggle("hidden", !isAuction);

  const allowedViews = isAuction
    ? ["intro", "setup", "auction", "scrim", "members", "mypage"]
    : ["setup", "score-intro", "team-simulator", "team-register", "tournament", "participation", "scrim", "members", "mypage"];
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

function renderParticipation() {
  const participation = state.participation || {
    enabled: false,
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
    form.elements.terms.value = participation.terms || "";
    loadParticipationApplications();
  }
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
        <small>${user.approved ? "승인 회원" : "승인 대기"}${user.applied_at ? ` · ${formatDateTime(user.applied_at)}` : ""}</small>
      </article>
    `).join("")
    : '<div class="empty-state">해당 인원이 없습니다.</div>';
}

async function loadParticipationApplications() {
  if (state.viewer.role !== "host" || currentView !== "participation") return;
  try {
    const data = await api("/api/participation/applications");
    $("#applied-count").textContent = data.applied.length;
    $("#not-applied-count").textContent = data.not_applied.length;
    renderParticipationUsers("#applied-users", data.applied);
    renderParticipationUsers("#not-applied-users", data.not_applied);
  } catch (error) {
    toast(error.message, true);
  }
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

function rosterField(entry, name, label, placeholder = "") {
  return `
    <label>${label}
      <input name="${name}" value="${escapeHtml(entry[name] || "")}" placeholder="${escapeHtml(placeholder)}" />
    </label>
  `;
}

function renderMemberRows(entries) {
  const list = $("#member-list");
  if (!entries.length) {
    list.innerHTML = '<div class="empty-state">조건에 맞는 명단이 없습니다.</div>';
    return;
  }
  list.innerHTML = entries.map((entry) => `
    <form class="roster-admin-row" data-roster-entry="${entry.id}">
      <div class="roster-admin-head">
        <div>
          <strong>${escapeHtml(entry.name)}</strong>
          <div class="meta">
            엑셀 ${entry.source_row}행
            ${entry.riot_id ? ` · 본 ${escapeHtml(entry.riot_id)}` : " · Riot ID 없음"}
            ${entry.secondary_riot_id ? ` · 부 ${escapeHtml(entry.secondary_riot_id)}` : ""}
          </div>
        </div>
        <div class="roster-badges">
          <span class="user-approval ${rosterStatusClass(entry.account_status)}">${entry.account_status === "ISSUED" ? "발급완료" : "미발급"}</span>
          <span class="user-approval ${participationClass(entry.tournament_status)}">${escapeHtml(entry.tournament_label)}</span>
          <span class="user-approval payment">${escapeHtml(entry.payment_status || "입금 X")}</span>
        </div>
      </div>
      <div class="roster-admin-fields">
        ${rosterField(entry, "name", "이름")}
        ${rosterField(entry, "riot_id", "본 아이디", "Riot ID#KR1")}
        ${rosterField(entry, "secondary_riot_id", "부 아이디", "선택 입력")}
        ${rosterField(entry, "preferred_lines", "참가라인")}
        ${rosterField(entry, "tier", "티어")}
        ${rosterField(entry, "payment_status", "입금")}
        ${rosterField(entry, "participation_status_text", "참가여부")}
        ${rosterField(entry, "absence_reason", "불참사유")}
        ${rosterField(entry, "top_adjustment", "탑레조정")}
        ${rosterField(entry, "game_count_adjustment", "판수조정")}
        ${rosterField(entry, "notes", "기타")}
      </div>
      <div class="roster-score-fields">
        ${rosterField(entry, "score_top", "탑")}
        ${rosterField(entry, "score_jungle", "정글")}
        ${rosterField(entry, "score_mid", "미드")}
        ${rosterField(entry, "score_adc", "원딜")}
        ${rosterField(entry, "score_support", "서폿")}
      </div>
      <div class="admin-user-actions">
        <span class="mini-status">저장 시 Riot ID가 있으면 계정이 자동 발급됩니다. 초기 비밀번호 1234</span>
        <button class="primary" type="submit">수정 저장</button>
      </div>
    </form>
  `).join("");
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
    const query = $("#member-search-form")?.elements.query.value || "";
    const data = await api(`/api/roster?filter=${encodeURIComponent(rosterFilter)}&query=${encodeURIComponent(query)}&page=${rosterPage}`);
    $("#member-stat-total").textContent = data.stats.total;
    $("#member-stat-with-id").textContent = data.stats.with_riot_id;
    $("#member-stat-without-id").textContent = data.stats.without_riot_id;
    $("#member-stat-issued").textContent = data.stats.account_issued;
    $("#member-stat-applied").textContent = data.stats.applied;
    $("#member-stat-not-applied").textContent = data.stats.not_applied;
    renderMemberRows(data.entries);
    renderRosterPagination(data.pagination);
  } catch (error) {
    toast(error.message, true);
  }
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
  form.elements.riot_id.value = viewer.riot_id || "";
  form.elements.secondary_riot_id.value = viewer.secondary_riot_id || "";
  form.elements.nickname.value = viewer.nickname || "";
}

function formatDateTime(timestamp) {
  return new Date(Number(timestamp) * 1000).toLocaleString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
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
  renderParticipation();
  renderMyPage();
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
    : location.pathname === "/tournament" ? "tournament"
    : location.pathname === "/participation" ? "participation"
    : location.pathname === "/members" ? "members"
    : location.pathname === "/mypage" ? "mypage"
    : location.pathname === "/scrim" ? "scrim" : "intro";
  if (state) setView(currentView);
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
  const payload = Object.fromEntries(new FormData(event.target));
  try {
    await api("/api/scrim/auth/login", { method: "POST", body: JSON.stringify(payload) });
    location.reload();
  } catch (error) {
    toast(error.message, true);
  }
});

$("#logout-button").addEventListener("click", async () => {
  await api("/api/scrim/auth/logout", { method: "POST" });
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
    const preview = await api("/api/players/riot/preview", { method: "POST", body: JSON.stringify(data) });
    riotPreviewData = { form: data, preview };
    renderRiotPreview(preview);
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
    state = await api("/api/state");
    stateSignature = meaningfulStateSignature(state);
    render();
    toast("대회 참가 신청을 완료했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#participation-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
    await api("/api/participation/settings", {
      method: "PUT",
      body: JSON.stringify({
        enabled: form.elements.enabled.checked,
        terms: form.elements.terms.value,
      }),
    });
    state = await api("/api/state");
    stateSignature = meaningfulStateSignature(state);
    render();
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

function renderScrimTeams() {
  const list = $("#team-list");
  const teams = state.tournament.teams;
  if (!teams.length) {
    list.innerHTML = '<div class="empty-state">아직 등록된 팀이 없습니다.</div>';
    return;
  }
  list.innerHTML = teams.map((team) => `
    <article class="team-item">
      <div class="team-head">
        <div>
          <strong>${escapeHtml(team.name)}</strong>
          <div class="meta">${team.status === "approved" ? "승인" : team.status === "rejected" ? "반려" : "승인 대기"} · 총 ${team.total_score}점</div>
        </div>
        <span class="team-status ${team.status}">${team.can_manage_scrim_result ? "결과 등록 가능" : "읽기 전용"}</span>
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
  const teams = manageableScrimTeams();
  form.classList.toggle("hidden", !teams.length);
  locked.classList.toggle("hidden", Boolean(teams.length));
  if (!teams.length) return;
  const select = form.elements.team_id;
  const selected = select.value;
  select.innerHTML = teams.map((team) =>
    `<option value="${team.id}">${escapeHtml(team.name)}</option>`
  ).join("");
  if (teams.some((team) => team.id === selected)) {
    select.value = selected;
  }
  if (!form.elements.match_date.value) {
    form.elements.match_date.value = new Date().toISOString().slice(0, 10);
  }
}

function renderScrimResults() {
  const list = $("#scrim-result-list");
  const teamById = (id) => state.tournament.teams.find((team) => team.id === id);
  const results = [...(state.scrim_results || [])].sort(
    (left, right) => String(right.match_date).localeCompare(String(left.match_date))
  );
  if (!results.length) {
    list.innerHTML = '<div class="empty-state">아직 등록된 결과가 없습니다.</div>';
    return;
  }
  list.innerHTML = results.map((result) => {
    const team = teamById(result.team_id);
    const canEdit = Boolean(team?.can_manage_scrim_result);
    const resultLabel = result.result === "WIN" ? "승" : result.result === "LOSE" ? "패" : "무";
    const image = result.image_url && !result.image_archived
      ? `<a class="scrim-result-image" href="${escapeHtml(result.image_url)}" target="_blank" rel="noreferrer">
          <img src="${escapeHtml(result.image_url)}" alt="스크림 결과 이미지" loading="lazy" />
        </a>`
      : result.image_url
        ? '<div class="scrim-result-archived">이미지 보관됨 · 10일 초과 또는 팀별 보관 한도 초과</div>'
        : "";
    return `
      <article class="team-item scrim-result-item">
        <div class="team-head">
          <div>
            <strong>${escapeHtml(team?.name || "삭제된 팀")} ${result.our_score} : ${result.opponent_score} ${escapeHtml(result.opponent_team_name)}</strong>
            <div class="meta">${escapeHtml(result.match_date)} · ${resultLabel}${result.memo ? ` · ${escapeHtml(result.memo)}` : ""}</div>
          </div>
          ${canEdit ? `<button class="ghost" type="button" data-edit-scrim-result="${result.id}">수정</button>` : ""}
        </div>
        ${image}
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
  renderScrimResults();
}

async function searchScrimUsers(query) {
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
    await loadMembers();
  } else {
    await searchScrimUsers($("#admin-search-form").elements.query.value || "");
  }
  toast(button.dataset.approved === "true" ? "회원을 승인했습니다." : "승인을 해제했습니다.");
}

function loadImageFromFile(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("이미지를 읽을 수 없습니다."));
    };
    image.src = url;
  });
}

function canvasToBlob(canvas, type, quality) {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

async function compressScrimImage(file, maxBytes = 1048576) {
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    throw new Error("JPG, PNG, WebP 이미지만 업로드할 수 있습니다.");
  }
  const image = await loadImageFromFile(file);
  let width = image.naturalWidth || image.width;
  let height = image.naturalHeight || image.height;
  const maxSide = 1600;
  if (Math.max(width, height) > maxSide) {
    const ratio = maxSide / Math.max(width, height);
    width = Math.round(width * ratio);
    height = Math.round(height * ratio);
  }
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  let quality = 0.86;
  let blob = null;
  for (let attempt = 0; attempt < 10; attempt += 1) {
    canvas.width = width;
    canvas.height = height;
    context.drawImage(image, 0, 0, width, height);
    blob = await canvasToBlob(canvas, "image/webp", quality);
    if (blob && blob.size <= maxBytes) break;
    if (quality > 0.52) {
      quality -= 0.08;
    } else {
      width = Math.round(width * 0.86);
      height = Math.round(height * 0.86);
    }
  }
  if (!blob || blob.size > maxBytes) {
    throw new Error("이미지를 1MB 이하로 압축하지 못했습니다. 더 작은 이미지를 선택해 주세요.");
  }
  return new File(
    [blob],
    `${file.name.replace(/\.[^.]+$/, "") || "scrim-result"}.webp`,
    { type: "image/webp" }
  );
}

async function uploadScrimResultImage(file) {
  const form = $("#scrim-result-form");
  const teamId = form.elements.team_id.value;
  if (!teamId) throw new Error("팀을 먼저 선택해 주세요.");
  const compressed = await compressScrimImage(file);
  const response = await fetch(
    `/api/scrim/results/image?team_id=${encodeURIComponent(teamId)}&filename=${encodeURIComponent(compressed.name)}`,
    {
      method: "POST",
      headers: { "Content-Type": compressed.type },
      body: compressed,
    }
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || "이미지 업로드에 실패했습니다.");
  if (!data.url) throw new Error("이미지 업로드 결과 URL이 없습니다.");
  form.elements.image_url.value = data.url;
  form.elements.image_size_bytes.value = data.size_bytes;
  form.elements.image_pathname.value = data.pathname || "";
  return data;
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

$("#scrim-result-image-file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    toast("이미지를 1MB 이하로 압축하고 업로드 중입니다.");
    const data = await uploadScrimResultImage(file);
    toast(`이미지 업로드 완료 (${Math.round(data.size_bytes / 1024)}KB)`);
  } catch (error) {
    event.target.value = "";
    toast(error.message, true);
  }
});

$("#scrim-result-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  const resultId = data.result_id;
  delete data.result_id;
  data.our_score = Number(data.our_score);
  data.opponent_score = Number(data.opponent_score);
  data.memo ||= null;
  data.image_url ||= null;
  data.image_size_bytes = data.image_size_bytes ? Number(data.image_size_bytes) : null;
  data.image_pathname ||= null;
  try {
    await api(
      resultId ? `/api/scrim/results/${resultId}` : "/api/scrim/results",
      {
        method: resultId ? "PUT" : "POST",
        body: JSON.stringify(data),
      }
    );
    form.reset();
    $("#scrim-result-image-file").value = "";
    form.elements.result_id.value = "";
    $("#cancel-result-edit").classList.add("hidden");
    state = await api("/api/state");
    stateSignature = meaningfulStateSignature(state);
    render();
    toast(resultId ? "결과를 수정했습니다." : "결과를 등록했습니다.");
  } catch (error) { toast(error.message, true); }
});

$("#cancel-result-edit").addEventListener("click", () => {
  $("#scrim-result-form").reset();
  $("#scrim-result-image-file").value = "";
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
  form.elements.result_id.value = result.id;
  form.elements.team_id.value = result.team_id;
  form.elements.match_date.value = result.match_date;
  form.elements.opponent_team_name.value = result.opponent_team_name;
  form.elements.our_score.value = result.our_score;
  form.elements.opponent_score.value = result.opponent_score;
  form.elements.memo.value = result.memo || "";
  form.elements.image_url.value = result.image_url || "";
  form.elements.image_size_bytes.value = result.image_size_bytes || "";
  form.elements.image_pathname.value = result.image_pathname || "";
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
    await loadMembers();
    toast("회원 계정을 생성했습니다. 기본 비밀번호는 1234입니다.");
  } catch (error) { toast(error.message, true); }
});

$("#member-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  rosterPage = 1;
  await loadMembers();
});

$("#member-list").addEventListener("submit", async (event) => {
  const rosterForm = event.target.closest("[data-roster-entry]");
  if (rosterForm) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(rosterForm));
    Object.keys(payload).forEach((key) => {
      if (payload[key] === "") payload[key] = null;
    });
    try {
      await api(`/api/roster/${rosterForm.dataset.rosterEntry}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
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
    setTimeout(() => location.reload(), 500);
  } catch (error) { toast(error.message, true); }
});

setInterval(updateTimer, 100);
api("/api/state").then((data) => {
  state = data;
  stateSignature = meaningfulStateSignature(data);
  render();
});
connectSocket();
