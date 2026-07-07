const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

let currentUser = null;
let toastTimer = null;

function toast(message, isError = false) {
  const node = $("#scrim-toast");
  node.textContent = message;
  node.className = `toast show${isError ? " error" : ""}`;
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

function formPayload(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function setAuthMode(mode) {
  const isLogin = mode === "login";
  $("#login-form").classList.toggle("hidden", !isLogin);
  $("#signup-form").classList.toggle("hidden", isLogin);
  $("#show-login").classList.toggle("active", isLogin);
  $("#show-signup").classList.toggle("active", !isLogin);
}

function renderShell() {
  const authenticated = Boolean(currentUser);
  $("#auth-view").classList.toggle("hidden", authenticated);
  $("#app-view").classList.toggle("hidden", !authenticated);
  $("#scrim-logout").classList.toggle("hidden", !authenticated);
  $("#scrim-user-badge").classList.toggle("hidden", !authenticated);
  if (!authenticated) return;

  $("#scrim-user-badge").textContent =
    `${currentUser.name} · ${currentUser.role === "ADMIN" ? "관리자" : "회원"}`;
  $("#admin-panel").classList.toggle("hidden", currentUser.role !== "ADMIN");
}

function renderTeams(teams) {
  const list = $("#team-list");
  if (!teams.length) {
    list.innerHTML = '<div class="empty-state">아직 등록된 팀이 없습니다.</div>';
    return;
  }
  list.innerHTML = teams.map((team) => `
    <article class="team-item">
      <div class="team-head">
        <div>
          <strong>${escapeHtml(team.name)}</strong>
          <div class="meta">${team.status} · ${team.active_member_count ?? team.members?.length ?? 0}명</div>
        </div>
        <span class="code-pill">${escapeHtml(team.invite_code)}</span>
      </div>
      ${team.members ? `
        <div class="member-list">
          ${team.members.map((member) =>
            `<span>${escapeHtml(member.name)}${member.role === "LEADER" ? " · 팀장" : ""}</span>`
          ).join("")}
        </div>` : ""}
    </article>
  `).join("");
}

function renderAdminUsers(users) {
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
          <div class="meta">${escapeHtml(user.riot_id)} · ${user.role}</div>
        </div>
      </div>
      <form data-password-reset="${user.id}">
        <input name="new_password" type="password" minlength="4" maxlength="128" placeholder="새 비밀번호" required />
        <button class="ghost" type="submit">재설정</button>
      </form>
    </article>
  `).join("");
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  }[char]));
}

async function loadHealth() {
  try {
    const health = await api("/api/scrim/health");
    $("#scrim-backend").textContent = `DB · ${health.backend}`;
  } catch (error) {
    $("#scrim-backend").textContent = "DB 연결 실패";
    toast(error.message, true);
  }
}

async function loadMe() {
  try {
    currentUser = await api("/api/scrim/me");
  } catch {
    currentUser = null;
  }
  renderShell();
  if (currentUser) {
    await loadTeams();
    if (currentUser.role === "ADMIN") await searchUsers("");
  }
}

async function loadTeams() {
  const data = await api("/api/scrim/teams");
  renderTeams(data.teams);
}

async function searchUsers(query) {
  const data = await api(`/api/scrim/admin/users?query=${encodeURIComponent(query)}`);
  renderAdminUsers(data.users);
}

$("#show-login").addEventListener("click", () => setAuthMode("login"));
$("#show-signup").addEventListener("click", () => setAuthMode("signup"));

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    currentUser = await api("/api/scrim/auth/login", {
      method: "POST",
      body: JSON.stringify(formPayload(event.currentTarget)),
    });
    event.currentTarget.reset();
    renderShell();
    await loadTeams();
    if (currentUser.role === "ADMIN") await searchUsers("");
    toast("로그인했습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    currentUser = await api("/api/scrim/users", {
      method: "POST",
      body: JSON.stringify(formPayload(event.currentTarget)),
    });
    event.currentTarget.reset();
    renderShell();
    await loadTeams();
    toast("회원가입이 완료되었습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#scrim-logout").addEventListener("click", async () => {
  await api("/api/scrim/auth/logout", { method: "POST" });
  currentUser = null;
  renderShell();
  toast("로그아웃했습니다.");
});

$("#team-create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = formPayload(event.currentTarget);
  payload.game_count = Number(payload.game_count || 0);
  payload.top_rank ||= null;
  try {
    await api("/api/scrim/teams", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    event.currentTarget.reset();
    await loadTeams();
    toast("팀을 만들었습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#team-join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/scrim/teams/join", {
      method: "POST",
      body: JSON.stringify(formPayload(event.currentTarget)),
    });
    event.currentTarget.reset();
    await loadTeams();
    toast("팀에 가입했습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#refresh-teams").addEventListener("click", () =>
  loadTeams().then(() => toast("팀 목록을 새로고침했습니다.")).catch((error) => toast(error.message, true))
);

$("#admin-search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await searchUsers(new FormData(event.currentTarget).get("query") || "");
  } catch (error) {
    toast(error.message, true);
  }
});

$("#admin-user-list").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-password-reset]");
  if (!form) return;
  event.preventDefault();
  try {
    await api(`/api/scrim/admin/users/${form.dataset.passwordReset}/password`, {
      method: "PATCH",
      body: JSON.stringify(formPayload(form)),
    });
    form.reset();
    toast("비밀번호를 재설정했습니다.");
  } catch (error) {
    toast(error.message, true);
  }
});

loadHealth();
loadMe();
