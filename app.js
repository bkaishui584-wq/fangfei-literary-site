(() => {
  "use strict";

  const categories = ["全部", "小说", "诗歌", "散文", "随笔", "剧本", "科幻", "杂文", "其他"];
  const THEMES = {
    starry: { name: "星穹·探索", image: "images/styles/starry.jpg", description: "星空、远方与未完成的句子。" },
    deepsea: { name: "深海·幻境", image: "images/styles/deepsea.jpg", description: "安静下潜，听见文字里的回声。" },
    sky: { name: "晴空·幻想", image: "images/styles/sky.jpg", description: "明亮轻盈，适合写下新的开始。" },
    flower: { name: "花羽·梦境", image: "images/styles/flower.png", description: "花瓣、羽毛和柔软的叙事。" },
    dragon: { name: "星龙·秘境", image: "images/styles/dragon.jpg", description: "史诗、奇想与辽阔的想象。" },
    qingli: { name: "青璃·映界", image: "images/styles/qingli.webp", description: "清透青绿与柔和暖光交织。" }
  };
  const THEME_KEY = "fangfei_theme_v1";
  const DEFAULT_RANKING_WEIGHTS = Object.freeze({ views: 1, likes: 8, favorites: 10, comments: 4 });
  const DATA_VERSION = 6;
  const EMPTY_STATE = {
    schemaVersion: DATA_VERSION,
    currentUser: { id: "", name: "访客", role: "guest" },
    followed: [],
    blocked: [],
    blockedUsers: [],
    likedWorks: [],
    favoritedWorks: [],
    notifications: [],
    works: [],
    authors: [],
    activities: [],
    announcements: [],
    reports: [],
    auditLogs: [],
    messageSettings: { allowStrangers: true, recallMinutes: 2, notifications: true },
    monthlyPicks: [],
    monthlyAwards: [],
    conversations: [],
    users: [],
    adminRoles: [],
    adminTransfers: [],
    rankings: {},
    rankingWeights: { ...DEFAULT_RANKING_WEIGHTS }
  };
  const loadState = () => structuredClone(EMPTY_STATE);

  let state = loadState();
  let route = location.hash.replace(/^#\/?/, "") || "home";
  let workFilter = "全部";
  let searchTerm = "";
  let activeConversation = state.conversations[0]?.id || null;
  let replyTo = null;
  let adminTab = "概览";
  let profileTab = "works";
  let rankingPeriod = "month";
  let rankingBoard = "works";
  let rankingAuthorMetric = "works";

  const app = document.querySelector("#app");
  const modalLayer = document.querySelector("#modal-layer");
  const modalContent = document.querySelector("#modal-content");
  const toast = document.querySelector("#toast");
  let csrfToken = "";
  let actionBusy = false;
  let dialogResolver = null;
  const numericId = (value) => Number(String(value || "").replace(/^[^\d]*/, ""));
  const apiRequest = async (path, options = {}) => {
    const method = options.method || "GET";
    const headers = Object.assign({ Accept: "application/json" }, options.headers || {});
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    });
    let payload = {};
    try { payload = await response.json(); } catch {}
    if (!response.ok) {
      const error = new Error(payload.error || "请求失败，请稍后重试");
      error.status = response.status;
      throw error;
    }
    return payload;
  };
  const applyBootstrap = (payload) => {
    if (!payload || typeof payload !== "object") return;
    if (payload.csrfToken) csrfToken = payload.csrfToken;
    if (payload.state) {
      state = Object.assign(structuredClone(EMPTY_STATE), payload.state);
      activeConversation = state.conversations.find((conversation) => !conversation.hidden)?.id || null;
    }
  };
  const refreshState = async (shouldRender = false) => {
    applyBootstrap(await apiRequest("/api/bootstrap"));
    if (shouldRender) render();
  };
  const handleApiError = (error) => {
    if (error?.status === 401) {
      openAuth("login");
      showToast("请先登录后再继续");
      return;
    }
    showToast(error?.message || "操作失败，请稍后重试");
  };
  const ensureLoggedIn = () => {
    if (state.currentUser?.role !== "guest" && state.currentUser?.id) return true;
    openAuth("login");
    showToast("请先登录后再继续");
    return false;
  };
  async function performAction(path, body = {}, successMessage = "", after = null) {
    if (actionBusy || !ensureLoggedIn()) return false;
    actionBusy = true;
    try {
      applyBootstrap(await apiRequest(path, { method: "POST", body }));
      if (typeof after === "function") after();
      if (successMessage) showToast(successMessage);
      return true;
    } catch (error) {
      handleApiError(error);
      return false;
    } finally {
      actionBusy = false;
    }
  }
  const save = () => {};
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const byId = (id, list) => list.find((item) => item.id === id);
  const workById = (id) => byId(id, state.works);
  const isAdmin = () => state.currentUser?.role === "admin";
  const isSuperAdmin = () => isAdmin() && state.currentUser?.adminLevel === "super";
  const currentUserId = () => state.currentUser?.id || "";
  const isPublishedWork = (work) => work?.status === "published" && work.isPublic !== false;
  const publicWorks = () => state.works.filter(isPublishedWork);
  const myWorks = () => state.works.filter((work) => work.createdBy === currentUserId());
  const userById = (id) => state.users.find((user) => user.id === id) || null;
  const avatarHtml = (user, className = "avatar") => `<span class="${className}">${escapeHtml(String(user?.avatar || user?.name || "芳").slice(0, 2))}</span>`;
  const statusLabel = (status) => ({ draft: "草稿", pending: "审核中", published: "已发布", rejected: "未通过", hidden: "已下架" }[status] || status || "未知");
  const worksByAuthor = (name) => state.works.filter((work) => work.author === name && isPublishedWork(work));
  const readingMinutes = (work) => Math.max(1, Math.round((work.body || []).join("").length / 420));
  const wordCount = (work) => (work.body || []).join("").replace(/\s/g, "").length;
  const workTags = (work) => Array.isArray(work.tags) ? work.tags.filter(Boolean) : [];
  const authorKey = (name) => `writer-${Array.from(String(name || "作者")).map((char) => char.codePointAt(0).toString(36)).join("")}`;
  const formatDate = (value) => {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? date.toLocaleDateString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }) : "";
  };
  const formatRelativeTime = (value) => {
    const diff = Date.now() - new Date(value).getTime();
    if (!Number.isFinite(diff) || diff < 0) return "刚刚";
    if (diff < 60000) return "刚刚";
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return `${Math.floor(diff / 86400000)} 天前`;
  };

  function allAuthors() {
    const explicit = Array.isArray(state.authors) ? state.authors : [];
    const byName = new Map(explicit.map((author) => [author.name, { awards: null, ...author }]));
    state.works.forEach((work) => {
      if (!work.author) return;
      if (!byName.has(work.author)) byName.set(work.author, { id: authorKey(work.author), name: work.author, bio: "", awards: null, derived: true });
    });
    return [...byName.values()];
  }

  const authorById = (id) => allAuthors().find((author) => author.id === id) || null;
  const authorIdByName = (name) => allAuthors().find((author) => author.name === name)?.id || "";

  function showToast(message) {
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(showToast.timer);
    showToast.timer = setTimeout(() => { toast.hidden = true; }, 2200);
  }

  function applyTheme(themeId) {
    const theme = THEMES[themeId] || THEMES.qingli;
    const id = THEMES[themeId] ? themeId : "qingli";
    document.documentElement.dataset.theme = id;
    document.documentElement.style.setProperty("--theme-image", `url("${theme.image}")`);
    localStorage.setItem(THEME_KEY, id);
  }

  function openAuth(mode = "login") {
    const currentMode = mode === "register" ? "register" : "login";
    const register = currentMode === "register";
    const html = `
      <div class="auth-tabs">
        <button class="${register ? "" : "is-active"}" type="button" data-auth-mode="login">登录</button>
        <button class="${register ? "is-active" : ""}" type="button" data-auth-mode="register">注册</button>
      </div>
      <form id="auth-form">
        ${register ? '<div class="field"><label>昵称</label><input class="input" name="displayName" maxlength="40" required autofocus></div>' : ''}
        <div class="field"><label>用户名</label><input class="input" name="username" maxlength="32" autocomplete="username" required ${register ? '' : 'autofocus'}></div>
        <div class="field"><label>密码</label><input class="input" name="password" type="password" minlength="8" maxlength="128" autocomplete="${register ? "new-password" : "current-password"}" required></div>
        ${register ? '<div class="field"><label>确认密码</label><input class="input" name="confirmPassword" type="password" minlength="8" maxlength="128" autocomplete="new-password" required></div>' : ''}
      </form>
    `;
    openModal(register ? "注册账号" : "登录", html, '<div class="modal-actions"><button class="button button-primary" type="submit" form="auth-form">' + (register ? "创建账号" : "登录") + '</button></div>');
    document.querySelectorAll("[data-auth-mode]").forEach((button) => {
      button.addEventListener("click", () => openAuth(button.dataset.authMode));
    });
    document.querySelector("#auth-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      if (!form.reportValidity()) return;
      const data = new FormData(form);
      const password = String(data.get("password") || "");
      if (register && password !== String(data.get("confirmPassword") || "")) {
        showToast("两次输入的密码不一致");
        return;
      }
      try {
        const body = register
          ? { username: String(data.get("username") || "").trim(), displayName: String(data.get("displayName") || "").trim(), password }
          : { username: String(data.get("username") || "").trim(), password };
        applyBootstrap(await apiRequest(register ? "/api/auth/register" : "/api/auth/login", { method: "POST", body }));
        closeModal();
        render();
        showToast(register ? "账号已创建" : "登录成功");
      } catch (error) {
        handleApiError(error);
      }
    });
  }

  function openProfile() {
    if (!ensureLoggedIn()) return;
    setRoute("profile");
  }

  function openSettings() {
    const current = document.documentElement.dataset.theme || "qingli";
    openModal("设置", `<section><h3 class="section-title">主题</h3><p class="muted">当前主题：${escapeHtml((THEMES[current] || THEMES.qingli).name)}</p><div class="theme-options">${Object.entries(THEMES).map(([id, theme]) => `<button class="theme-option ${id === current ? "is-selected" : ""}" type="button" data-theme-choice="${id}"><img src="${theme.image}" alt=""><span><strong>${escapeHtml(theme.name)}</strong><small>${escapeHtml(theme.description)}</small></span></button>`).join("")}</div></section><div class="modal-actions"><button class="button" type="button" data-close-modal>关闭</button></div>`);
  }

  function profileWorkList(works) {
    if (!works.length) return '<div class="empty compact-empty">这里还没有内容。</div>';
    return `<div class="profile-work-list">${works.map((work) => `<article class="profile-work-row"><div><span class="work-category">${escapeHtml(work.category || "未分类")}</span><h3>${escapeHtml(work.title)}</h3><small>${escapeHtml(work.excerpt || "")}</small></div><div class="profile-work-actions"><span class="status-pill">${escapeHtml(statusLabel(work.status))}</span><button class="button button-small" type="button" data-work="${work.id}">查看</button>${["draft", "rejected"].includes(work.status) ? `<button class="button button-small button-primary" type="button" data-edit-work="${work.id}">编辑</button>` : ""}</div></article>`).join("")}</div>`;
  }


  function renderProfile() {
    if (!state.currentUser?.id) return renderMissing("请先登录后查看个人中心");
    const user = state.currentUser;
    const works = myWorks();
    const published = works.filter(isPublishedWork);
    const awards = state.monthlyAwards.filter((award) => award.authorId === currentUserId());
    const liked = state.likedWorks.map(workById).filter(Boolean);
    const favorited = state.favoritedWorks.map(workById).filter(Boolean);
    const comments = state.works.flatMap((work) => (work.comments || []).map((comment) => ({ ...comment, workTitle: work.title }))).filter((comment) => comment.userId === currentUserId());
    const author = state.authors.find((item) => item.id === currentUserId());
    const tabs = [["works", "我的作品"], ["favorites", "我的收藏"], ["likes", "我的点赞"], ["comments", "我的评论"], ["awards", "我的获奖"], ["activities", "我的活动"], ["settings", "账户设置"]];
    let content = "";
    if (profileTab === "works") {
      const statusCards = ["published", "pending", "draft", "rejected"].map((status) => `<span><strong>${works.filter((work) => work.status === status).length}</strong>${statusLabel(status)}</span>`).join("");
      content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">创作档案</p><h2 class="section-title">我的作品</h2></div><button class="button button-small button-primary" type="button" data-publish>新建投稿</button></div><div class="profile-status-summary">${statusCards}</div>${profileWorkList(works)}</section>`;
    }
    if (profileTab === "favorites") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">读者书架</p><h2 class="section-title">我的收藏</h2></div></div>${favorited.length ? `<div class="work-grid">${favorited.map(workCard).join("")}</div>` : '<div class="empty compact-empty">暂无收藏作品。</div>'}</section>`;
    if (profileTab === "likes") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">留下掌声</p><h2 class="section-title">我的点赞</h2></div></div>${liked.length ? `<div class="work-grid">${liked.map(workCard).join("")}</div>` : '<div class="empty compact-empty">暂无点赞作品。</div>'}</section>`;
    if (profileTab === "comments") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">阅读痕迹</p><h2 class="section-title">我的评论</h2></div></div>${comments.length ? `<ul class="admin-list">${comments.map((comment) => `<li class="admin-row"><span><strong>${escapeHtml(comment.text)}</strong><small class="admin-note">评论《${escapeHtml(comment.workTitle)}》</small></span></li>`).join("")}</ul>` : '<div class="empty compact-empty">暂无评论记录。</div>'}</section>`;
    if (profileTab === "awards") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">文学社荣誉</p><h2 class="section-title">我的获奖</h2></div></div>${awards.length ? `<ul class="admin-list">${awards.map((award) => `<li class="admin-row"><span><strong>${escapeHtml(workById(award.workId)?.title || "作品")}</strong><small class="admin-note">${escapeHtml(award.month)} · ${escapeHtml(award.category || "综合")} · 由 ${escapeHtml(award.selectedByName || "编辑部")} 评选</small></span><button class="button button-small" type="button" data-work="${award.workId}">阅读</button></li>`).join("")}</ul>` : '<div class="empty compact-empty">暂无获奖记录。</div>'}</section>`;
    if (profileTab === "activities") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">参与记录</p><h2 class="section-title">我的活动</h2></div></div><div class="empty compact-empty">当前系统暂未保存活动报名关系，暂无可展示记录。</div></section>`;
    if (profileTab === "settings") content = `<section class="profile-section"><div class="section-head"><div><p class="eyebrow">账号与偏好</p><h2 class="section-title">账户设置</h2></div></div><div class="settings-grid"><button class="setting-card" type="button" data-profile-edit><strong>个人资料</strong><small>笔名、头像、简介、背景图和文学偏好</small></button><button class="setting-card" type="button" data-open-settings><strong>主题设置</strong><small>保留现有六套主题并即时切换</small></button><button class="setting-card" type="button" data-profile-privacy><strong>隐私与私信</strong><small>陌生人私信、拉黑名单和撤回时间</small></button><button class="setting-card" type="button" data-profile-notifications><strong>通知设置</strong><small>控制站内通知与未读提醒</small></button><button class="setting-card" type="button" data-profile-password><strong>安全设置</strong><small>修改登录密码</small></button><button class="setting-card" type="button" data-route="messages"><strong>我的私信</strong><small>查看会话和未读消息</small></button><button class="setting-card is-danger" type="button" data-logout><strong>退出登录</strong><small>结束当前浏览器会话</small></button></div></section>`;
    app.innerHTML = `<div class="page profile-page"><header class="profile-hero" ${user.coverTheme && THEMES[user.coverTheme] ? `style="--profile-cover:url('${THEMES[user.coverTheme].image}')"` : ""}><div class="profile-hero-main">${avatarHtml(user, "avatar profile-avatar")}<div><p class="eyebrow">个人中心</p><h1>${escapeHtml(user.name)}</h1><p>${escapeHtml(user.bio || "还没有写下个人简介。")}</p><small>加入于 ${escapeHtml(user.joinedAt || "未知时间")}</small></div></div><div class="profile-stats"><span><strong>${published.length}</strong>已发布作品</span><span><strong>${awards.length}</strong>获奖</span><span><strong>${favorited.length}</strong>收藏</span><span><strong>${Number(author?.followerCount) || 0}</strong>关注者</span></div></header><nav class="profile-tabs">${tabs.map(([id, label]) => `<button class="${profileTab === id ? "is-active" : ""}" type="button" data-profile-tab="${id}">${label}</button>`).join("")}</nav>${content}</div>`;
  }


  function openProfileEditor() {
    const user = state.currentUser;
    const genres = Array.isArray(user.genres) ? user.genres : [];
    openModal("编辑个人资料", `<form id="profile-form"><div class="form-grid"><div class="field"><label>笔名</label><input class="input" name="displayName" maxlength="40" value="${escapeHtml(user.name)}" required autofocus></div><div class="field"><label>头像文字</label><input class="input" name="avatar" maxlength="4" value="${escapeHtml(user.avatar || "")}" placeholder="1-2 个字"></div></div><div class="field"><label>个人简介</label><textarea class="textarea" name="bio" maxlength="300" placeholder="介绍你的写作与兴趣">${escapeHtml(user.bio || "")}</textarea></div><div class="field"><label>背景图</label><select class="select" name="coverTheme"><option value="">默认背景</option>${Object.entries(THEMES).map(([id, theme]) => `<option value="${id}" ${user.coverTheme === id ? "selected" : ""}>${escapeHtml(theme.name)}</option>`).join("")}</select></div><div class="field"><label>文学偏好</label><textarea class="textarea" name="preferences" maxlength="500" placeholder="例如：偏爱安静、克制、带有现实质感的叙事">${escapeHtml(user.preferences || "")}</textarea></div><div class="field"><label>擅长类型</label><div class="choice-grid">${categories.slice(1).map((category) => `<label><input type="checkbox" name="genres" value="${category}" ${genres.includes(category) ? "checked" : ""}> ${category}</label>`).join("")}</div></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="save-profile">保存资料</button></div>');
    document.querySelector("#save-profile").addEventListener("click", async () => {
      const form = document.querySelector("#profile-form");
      if (!form.reportValidity()) return;
      const data = new FormData(form);
      await performAction("/api/profile", {
        displayName: String(data.get("displayName") || "").trim(),
        avatar: String(data.get("avatar") || "").trim(),
        bio: String(data.get("bio") || "").trim(),
        coverTheme: String(data.get("coverTheme") || ""),
        preferences: String(data.get("preferences") || "").trim(),
        genres: data.getAll("genres")
      }, "个人资料已保存", () => { closeModal(); render(); });
    });
  }


  function openChangePassword() {
    openModal("安全设置", `<form id="password-form"><div class="field"><label>当前密码</label><input class="input" type="password" name="currentPassword" autocomplete="current-password" required autofocus></div><div class="field"><label>新密码</label><input class="input" type="password" name="newPassword" minlength="8" maxlength="128" autocomplete="new-password" required></div><div class="field"><label>确认新密码</label><input class="input" type="password" name="confirmPassword" minlength="8" maxlength="128" autocomplete="new-password" required></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="save-password">修改密码</button></div>');
    document.querySelector("#save-password").addEventListener("click", async () => {
      const data = new FormData(document.querySelector("#password-form"));
      const next = String(data.get("newPassword") || "");
      if (next !== String(data.get("confirmPassword") || "")) return showToast("两次输入的新密码不一致");
      await performAction("/api/auth/change-password", { currentPassword: String(data.get("currentPassword") || ""), newPassword: next }, "密码已修改", () => closeModal());
    });
  }


  function openPrivacySettings() {
    const blocked = state.blockedUsers?.length ? state.blockedUsers : state.blocked.map((id) => authorById(id)).filter(Boolean);
    openModal("隐私与私信", `<p class="muted">私信权限由账户设置控制，拉黑名单只影响你的账号。</p><div class="profile-summary"><div><strong>${state.messageSettings.allowStrangers ? "允许陌生人私信" : "仅允许关注者私信"}</strong><small>${state.messageSettings.notifications ? "消息提醒已开启" : "消息提醒已关闭"}</small></div></div><section class="section"><h3 class="section-title">已拉黑用户</h3>${blocked.length ? `<ul class="admin-list">${blocked.map((author) => `<li class="admin-row"><span>${escapeHtml(author.name)}</span><button class="button button-small" type="button" data-block-author="${author.id}">解除拉黑</button></li>`).join("")}</ul>` : '<div class="empty compact-empty">暂无拉黑用户。</div>'}</section>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>关闭</button><button class="button button-primary" type="button" data-message-settings>管理私信设置</button></div>');
  }


  async function logoutAccount() {
    try {
      applyBootstrap(await apiRequest("/api/auth/logout", { method: "POST", body: {} }));
      setRoute("home");
      showToast("已退出登录");
    } catch (error) {
      handleApiError(error);
    }
  }


  function publishedAnnouncement() {
    return state.announcements.find((item) => item.status === "published") || null;
  }

  function openModal(title, html, actions = "") {
    modalContent.innerHTML = `<header class="modal-head"><div><span class="eyebrow">FANGFEI LITERARY SOCIETY</span><h2 id="modal-title">${escapeHtml(title)}</h2></div></header><div class="modal-body">${html}</div>${actions ? `<div class="modal-footer">${actions}</div>` : ""}`;
    modalLayer.hidden = false;
    document.body.style.overflow = "hidden";
    modalContent.querySelector("[autofocus]")?.focus();
  }

  function closeModal() {
    const resolve = dialogResolver;
    dialogResolver = null;
    modalLayer.hidden = true;
    modalContent.innerHTML = "";
    document.body.style.overflow = "";
    if (resolve) resolve(false);
  }

  function settleDialog(value) {
    const resolve = dialogResolver;
    dialogResolver = null;
    closeModal();
    if (resolve) resolve(value);
  }

  function confirmDialog(message, title = "请确认") {
    return new Promise((resolve) => {
      dialogResolver = resolve;
      openModal(title, `<p>${escapeHtml(message)}</p>`, '<div class="modal-actions"><button class="button" type="button" data-dialog-cancel>取消</button><button class="button button-danger" type="button" data-dialog-confirm>确认</button></div>');
      modalContent.querySelector("[data-dialog-cancel]")?.addEventListener("click", () => settleDialog(false));
      modalContent.querySelector("[data-dialog-confirm]")?.addEventListener("click", () => settleDialog(true));
    });
  }

  function promptDialog(title, message, defaultValue = "") {
    return new Promise((resolve) => {
      dialogResolver = resolve;
      openModal(title, `<p>${escapeHtml(message)}</p><div class="field"><input class="input" id="dialog-input" value="${escapeHtml(defaultValue)}"></div>`, '<div class="modal-actions"><button class="button" type="button" data-dialog-cancel>取消</button><button class="button button-primary" type="button" data-dialog-confirm>确认</button></div>');
      const input = modalContent.querySelector("#dialog-input");
      input?.focus();
      modalContent.querySelector("[data-dialog-cancel]")?.addEventListener("click", () => settleDialog(null));
      modalContent.querySelector("[data-dialog-confirm]")?.addEventListener("click", () => settleDialog(input?.value ?? ""));
    });
  }

  function setRoute(next) {
    route = next;
    location.hash = next === "home" ? "" : `/${next}`;
    render();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderHeader() {
    document.querySelectorAll("[data-route]").forEach((button) => {
      const target = button.dataset.route;
      button.classList.toggle("is-active", route === target || route.startsWith(`${target}/`));
    });
    document.querySelectorAll("[data-admin-only]").forEach((element) => { element.hidden = !isAdmin(); });
    const userButton = document.querySelector("#user-button");
    if (userButton) userButton.innerHTML = state.currentUser?.role === "guest" ? "登录 / 注册" : `<span>${escapeHtml(state.currentUser.name.slice(0, 1))}</span> 我的`;
    const unread = state.conversations.filter((conversation) => !conversation.hidden).reduce((sum, conversation) => sum + conversation.unread, 0);
    const unreadElement = document.querySelector("#nav-unread");
    unreadElement.textContent = unread;
    unreadElement.hidden = unread === 0;
    const unreadNotifications = state.messageSettings.notifications ? state.notifications.filter((item) => !item.read).length : 0;
    const notificationCount = document.querySelector("#notification-count");
    notificationCount.textContent = unreadNotifications;
    notificationCount.hidden = unreadNotifications === 0;
    document.querySelector("#notification-button")?.setAttribute("aria-label", unreadNotifications ? `${unreadNotifications} 条通知` : "通知");
  }

  function workCard(work) {
    const featured = state.monthlyPicks.includes(work.id);
    const tags = workTags(work);
    const published = formatDate(work.createdAt || work.publishedAt);
    const likes = Number(work.likes) || 0;
    const views = Number(work.views) || 0;
    const favorites = Number(work.favorites) || 0;
    const comments = Array.isArray(work.comments) ? work.comments.length : 0;
    return `<article class="work-card ${featured ? "is-featured" : ""}">
      <div class="work-card-top"><span class="work-category">${escapeHtml(work.category || "未分类")}</span>${work.status !== "published" ? `<span class="work-flag">${escapeHtml(statusLabel(work.status))}</span>` : featured ? '<span class="work-flag">本月优秀</span>' : ""}</div>
      <button class="work-card-title work-title-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button>
      <p class="work-excerpt">${escapeHtml(work.excerpt || (work.body || []).join("").slice(0, 110))}</p>
      ${tags.length ? `<div class="tag-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
      <div class="work-meta"><button class="link-button" type="button" data-author="${(work.authorId || authorIdByName(work.author))}">${escapeHtml(work.author || "匿名作者")}</button>${published ? `<span>${escapeHtml(published)}</span>` : ""}</div>
      <div class="work-stats"><span>${views} 阅读</span><span>${likes} 点赞</span><span>${favorites} 收藏</span><span>${comments} 评论</span></div>
      <div class="work-card-foot"><span>约 ${readingMinutes(work)} 分钟</span><button class="link-button" type="button" data-work="${work.id}">阅读全文</button></div>
    </article>`;
  }

  function renderHome() {
    const latest = publicWorks().sort((a, b) => Number(b.createdAt || b.publishedAt || 0) - Number(a.createdAt || a.publishedAt || 0));
    const latestAwardMonth = state.monthlyAwards[0]?.month || "";
    const monthly = (state.monthlyAwards.length
      ? state.monthlyAwards.filter((award) => award.month === latestAwardMonth).map((award) => workById(award.workId))
      : state.monthlyPicks.map(workById)).filter(Boolean);
    const hotAuthors = allAuthors().map((author) => {
      const works = worksByAuthor(author.name);
      return { ...author, works, likes: works.reduce((sum, work) => sum + (Number(work.likes) || 0), 0) };
    }).filter((author) => author.works.length).sort((a, b) => b.likes - a.likes || b.works.length - a.works.length).slice(0, 3);
    const announcement = publishedAnnouncement();
    app.innerHTML = `<div class="page">
      <section class="hero home-hero">
        <div class="hero-copy">
          <p class="eyebrow">文学创作与交流平台</p>
          <h1>芳菲文学社</h1>
          <p class="hero-lead">让文字被认真读完，让作者彼此看见。</p>
          <div class="hero-actions"><button class="button button-primary" type="button" data-route="works">浏览作品</button><button class="button" type="button" data-route="activities">文学活动</button></div>
        </div>
        <aside class="hero-poem hero-note-card"><span>关于芳菲</span><p>这里保存公开作品、作者主页、评论和文学活动。你可以阅读，也可以投稿自己的作品。</p></aside>
      </section>

      <section class="section">
        <div class="section-head"><div><p class="eyebrow">编辑推荐</p><h2 class="section-title">本月优秀</h2></div><button class="section-link" type="button" data-route="monthly">查看月度页面</button></div>
        ${monthly.length ? `<div class="monthly-ribbon">${monthly.map((work, index) => `<article><span>${String(index + 1).padStart(2, "0")}</span><button class="link-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><small>${escapeHtml(work.author)} · ${Number(work.likes) || 0} 点赞</small></article>`).join("")}</div>` : '<div class="empty compact-empty">本月暂无优秀作品。</div>'}
      </section>

      <section class="section">
        <div class="section-head"><div><p class="eyebrow">刚刚更新</p><h2 class="section-title">最新作品</h2></div><button class="section-link" type="button" data-route="works">查看全部作品</button></div>
        ${latest.length ? `<div class="work-grid">${latest.slice(0, 6).map(workCard).join("")}</div>` : '<div class="empty compact-empty">还没有公开作品。<button class="link-button" type="button" data-publish>投稿第一篇作品</button></div>'}
      </section>

      <div class="section-split">
        <section class="section">
          <div class="section-head"><div><p class="eyebrow">写作者</p><h2 class="section-title">热门作者</h2></div><button class="section-link" type="button" data-route="authors">全部作者</button></div>
          ${hotAuthors.length ? `<div class="author-grid">${hotAuthors.map(authorCard).join("")}</div>` : '<div class="empty compact-empty">暂无公开作品作者。</div>'}
        </section>
        <section class="section">
          <div class="section-head"><div><p class="eyebrow">活动日程</p><h2 class="section-title">文学活动</h2></div><button class="section-link" type="button" data-route="activities">全部活动</button></div>
          ${state.activities.length ? `<div class="activity-grid">${state.activities.slice(0, 4).map(activityCard).join("")}</div>` : '<div class="empty compact-empty">暂无已发布活动。</div>'}
        </section>
      </div>

      <section class="section">
        <div class="section-head"><div><p class="eyebrow">文学社公告</p><h2 class="section-title">芳菲动态</h2></div></div>
        ${announcement ? `<article class="home-announcement"><div><span class="work-category">公告</span><h3>${escapeHtml(announcement.title)}</h3><p>${escapeHtml(announcement.content)}</p></div><time>${escapeHtml(announcement.at || "")}</time></article>` : '<div class="empty compact-empty">暂无文学社公告。</div>'}
      </section>
    </div>`;
  }

  function renderWorks() {
    const term = searchTerm.trim().toLowerCase();
    const works = publicWorks().filter((work) => (workFilter === "全部" || work.category === workFilter) && (!term || `${work.title}${work.author}${work.excerpt}`.toLowerCase().includes(term)));
    app.innerHTML = `<div class="page">
      <header class="page-head"><div><p class="eyebrow">作品阅览室</p><h1 class="page-title">作品</h1></div><p class="page-note">按体裁浏览，或搜索标题、作者和正文摘录。</p></header>
      <div class="toolbar"><label class="search-box"><span aria-hidden="true">⌕</span><input id="work-search" type="search" placeholder="搜索作品" value="${escapeHtml(searchTerm)}"></label>${categories.map((category) => `<button class="filter-chip ${workFilter === category ? "is-active" : ""}" type="button" data-filter="${category}">${category}</button>`).join("")}</div>
      ${works.length ? `<div class="work-grid">${works.map(workCard).join("")}</div>` : `<div class="empty">没有找到匹配的作品，换个关键词试试。</div>`}
    </div>`;
    const search = document.querySelector("#work-search");
    search?.addEventListener("input", (event) => { searchTerm = event.target.value; renderWorks(); document.querySelector("#work-search")?.focus(); });
  }

  function renderWork(id) {
    const work = workById(id);
    if (!work) return renderMissing("这篇作品暂时无法找到");
    const author = authorById((work.authorId || authorIdByName(work.author)));
    const tags = workTags(work);
    const published = formatDate(work.createdAt || work.publishedAt);
    const liked = state.likedWorks.includes(work.id);
    const favorited = state.favoritedWorks.includes(work.id);
    const comments = Array.isArray(work.comments) ? work.comments : [];
    const canRead = isPublishedWork(work);
    const canComment = canRead && work.allowComments !== false;
    const canFavorite = canRead && work.allowFavorites !== false;
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="works">← 返回作品列表</button><div class="article-layout reading-layout">
      <article class="article-body reading-article">
        <header class="reading-head"><div class="reading-kicker"><span class="work-category">${escapeHtml(work.category || "未分类")}</span>${!canRead ? `<span class="status-pill">${escapeHtml(statusLabel(work.status))}</span>` : ""}</div><h1>${escapeHtml(work.title)}</h1><div class="reading-meta">${author ? `<button class="link-button" type="button" data-author="${author.id}">${escapeHtml(work.author || "匿名作者")}</button>` : `<span>${escapeHtml(work.author || "匿名作者")}</span>`}${published ? `<time>${escapeHtml(published)}</time>` : ""}<span>${Number(work.views) || 0} 阅读</span><span>约 ${readingMinutes(work)} 分钟</span></div>${tags.length ? `<div class="tag-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}${work.reviewNote ? `<p class="review-note">审核意见：${escapeHtml(work.reviewNote)}</p>` : ""}<div class="reading-actions"><button class="button button-small ${liked ? "is-active" : ""}" type="button" data-like-work="${work.id}" ${canRead ? "" : "disabled"}>${liked ? "已点赞" : "点赞"} ${Number(work.likes) || 0}</button><button class="button button-small ${favorited ? "is-active" : ""}" type="button" data-favorite-work="${work.id}" ${canFavorite ? "" : "disabled"}>${favorited ? "已收藏" : "收藏"} ${Number(work.favorites) || 0}</button><button class="button button-small" type="button" data-share-work="${work.id}">分享</button><button class="button button-small" type="button" data-report-work="${work.id}" ${canRead ? "" : "disabled"}>举报</button>${author ? `<button class="button button-small" type="button" data-message-author="${author.id}">私信作者</button>` : ""}</div></header>
        <div class="reading-content">${(work.body || []).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}</div>
      </article>
      <aside class="article-aside"><section class="author-brief">${author ? `${avatarHtml(author)}<h2>${escapeHtml(author.name)}</h2>${author.bio ? `<p>${escapeHtml(author.bio)}</p>` : ""}<button class="link-button" type="button" data-author="${author.id}">查看作者主页</button>` : '<p class="muted">作者信息暂无。</p>'}</section><section class="comment-section"><h2 class="section-title">评论 <span class="muted">${comments.length}</span></h2><div id="comment-list">${comments.length ? comments.map(commentItem).join("") : '<p class="muted">还没有评论。</p>'}</div>${canComment ? `<form id="comment-form"><div class="field"><textarea class="textarea" name="comment" maxlength="500" required placeholder="写下具体、真诚的阅读感受"></textarea></div><button class="button button-primary" type="submit">发表评论</button></form>` : '<p class="muted">当前暂不开放评论。</p>'}</section></aside>
    </div></div>`;
    document.querySelector("#comment-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!ensureLoggedIn()) return;
      const text = String(new FormData(event.currentTarget).get("comment") || "").trim();
      if (!text) return;
      await performAction(`/api/works/${numericId(id)}/comments`, { text }, "评论已发表", () => renderWork(id));
    });
    if (canRead && !sessionStorage.getItem(`viewed:${work.id}`)) {
      sessionStorage.setItem(`viewed:${work.id}`, "1");
      apiRequest(`/api/works/${numericId(work.id)}/view`, { method: "POST", body: {} }).then(() => refreshState(false)).catch(() => {});
    }
  }

  function commentItem(comment) {
    const at = typeof comment.at === "number" ? formatRelativeTime(comment.at) : String(comment.at || "");
    return `<div class="comment"><div class="comment-head"><strong>${escapeHtml(comment.who)}</strong><time>${escapeHtml(at)}</time></div><p>${escapeHtml(comment.text)}</p></div>`;
  }

  function authorCard(author) {
    const works = worksByAuthor(author.name);
    const likes = works.reduce((sum, work) => sum + (Number(work.likes) || 0), 0);
    return `<article class="author-card"><div class="author-card-head"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><div><h3>${escapeHtml(author.name)}</h3>${author.awardCount ? `<span class="author-level">${Number(author.awardCount) || 0} 次获奖</span>` : ""}</div></div>${author.bio ? `<p>${escapeHtml(author.bio)}</p>` : ""}<div class="author-stats"><span><strong>${works.length}</strong> 篇作品</span><span><strong>${likes}</strong> 次点赞</span></div>${works[0] ? `<small class="author-latest">作品《${escapeHtml(works[0].title)}》</small>` : ""}<div class="form-row"><button class="button button-small" type="button" data-author="${author.id}">查看主页</button><button class="button button-small button-primary" type="button" data-message-author="${author.id}">私信</button></div></article>`;
  }

  function renderAuthors() {
    const authors = allAuthors().filter((author) => worksByAuthor(author.name).length);
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">作者会客厅</p><h1 class="page-title">作者</h1></div><p class="page-note">作者信息来自公开作品与站内公开资料。</p></header>${authors.length ? `<div class="author-grid" style="margin-top:28px">${authors.map(authorCard).join("")}</div>` : '<div class="empty compact-empty">暂无可展示的作者。</div>'}</div>`;
  }

  function renderAuthor(id) {
    const author = authorById(id);
    if (!author) return renderMissing("这位作者暂时无法找到");
    const works = worksByAuthor(author.name);
    const monthly = works.filter((work) => state.monthlyAwards.some((award) => award.workId === work.id));
    const likes = works.reduce((sum, work) => sum + (Number(work.likes) || 0), 0);
    const words = works.reduce((sum, work) => sum + wordCount(work), 0);
    const followed = state.followed.includes(author.id);
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="authors">← 返回作者列表</button>
      <header class="author-profile"><div class="author-profile-main"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><div><p class="eyebrow">作者主页</p><h1 class="page-title">${escapeHtml(author.name)}</h1>${author.bio ? `<p class="page-note">${escapeHtml(author.bio)}</p>` : ""}</div></div><div class="author-profile-actions"><button class="button" type="button" data-follow="${author.id}">${followed ? "已关注" : "关注作者"}</button><button class="button button-primary" type="button" data-message-author="${author.id}">私信作者</button></div></header>
      <section class="author-dashboard"><article><strong>${works.length}</strong><span>作品数量</span></article><article><strong>${monthly.length}</strong><span>月度优秀</span></article><article><strong>${likes}</strong><span>获得点赞</span></article><article><strong>${words}</strong><span>总字数</span></article></section>
      ${author.awardCount ? `<section class="section"><div class="section-head"><h2 class="section-title">获奖记录</h2></div><p>${Number(author.awardCount) || 0} 次获奖。</p></section>` : ""}
      <section class="section"><div class="section-head"><div><p class="eyebrow">作品集</p><h2 class="section-title">公开作品</h2></div></div>${works.length ? `<div class="work-grid">${works.map(workCard).join("")}</div>` : '<div class="empty compact-empty">这位作者还没有公开作品。</div>'}</section>
    </div>`;
  }

  function renderMessages() {
    if (!state.currentUser?.id) return renderMissing("请先登录后查看私信");
    const visible = state.conversations.filter((conversation) => !conversation.hidden);
    const current = visible.find((conversation) => conversation.id === activeConversation) || visible[0];
    const unread = visible.reduce((sum, conversation) => sum + conversation.unread, 0);
    if (current) activeConversation = current.id;
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">只对彼此可见</p><h1 class="page-title">私信</h1><p class="page-note">与作者讨论作品、交流写作计划。删除会话只会从你的列表隐藏，不会删除双方历史消息。</p></div><div class="message-head-actions"><span class="message-unread-summary">${unread ? `${unread} 条未读` : "消息已读完"}</span><button class="button button-small" type="button" data-message-settings>私信设置</button></div></header>
      <div class="messages-layout" style="margin-top:28px">
        <aside class="conversation-list"><div class="conversation-list-head"><strong>会话</strong><label class="search-box"><input id="conversation-search" type="search" placeholder="搜索作者"></label></div><div id="conversation-items">${visible.map(conversationItem).join("") || '<div class="empty">暂无会话</div>'}</div></aside>
        <section class="chat-panel">${current ? chatPanel(current) : '<div class="empty">从一个作者主页发起私信，开始第一次交流。</div>'}</section>
      </div></div>`;
    const search = document.querySelector("#conversation-search");
    search?.addEventListener("input", (event) => {
      const term = event.target.value.trim().toLowerCase();
      document.querySelectorAll(".conversation-item").forEach((item) => {
        item.hidden = !item.dataset.name.toLowerCase().includes(term);
      });
    });
    bindChat(current);
  }

  function conversationItem(conversation) {
    const author = authorById(conversation.userId) || { name: "未知用户" };
    const last = conversation.messages.filter((message) => !message.recalled).at(-1);
    return `<button class="conversation-item ${conversation.id === activeConversation ? "is-active" : ""}" type="button" data-conversation="${conversation.id}" data-name="${escapeHtml(author.name)}"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><span><strong>${escapeHtml(author.name)}</strong><small>${last ? escapeHtml(last.text) : "暂无消息"}</small></span><time>${last ? formatRelativeTime(last.at) : ""}${conversation.unread ? `<b>${conversation.unread}</b>` : ""}</time></button>`;
  }

  function chatPanel(conversation) {
    const author = authorById(conversation.userId) || { name: "未知用户" };
    const blocked = state.blocked.includes(author.id);
    return `<header class="chat-head"><div><strong>${escapeHtml(author.name)}</strong><small>${blocked ? "已拉黑，暂不能发送消息" : "私信内容仅双方可见"}</small></div><div class="chat-tools"><button class="button button-small" type="button" data-block="${conversation.id}">${blocked ? "解除拉黑" : "拉黑"}</button><button class="button button-small" type="button" data-report-conversation="${conversation.id}">举报</button><button class="button button-small" type="button" data-delete-conversation="${conversation.id}">删除会话</button></div></header>
      <div class="chat-body" id="chat-body">${conversation.messages.map((message) => messageItem(conversation, message)).join("") || '<div class="empty">还没有消息，先说一句你好。</div>'}</div>
      <form class="chat-form" id="chat-form">${replyTo ? `<div class="reply-preview"><span>回复：${escapeHtml(findMessage(conversation, replyTo)?.text || "")}</span><button type="button" data-cancel-reply>取消</button></div>` : ""}<div class="form-row" style="margin:0"><input class="input" name="message" maxlength="1000" autocomplete="off" placeholder="${blocked ? "已拉黑该用户" : "输入消息……"}" ${blocked ? "disabled" : ""}><button class="button button-primary" type="submit" ${blocked ? "disabled" : ""}>发送</button></div></form>`;
  }

  function findMessage(conversation, id) {
    return conversation.messages.find((message) => message.id === id);
  }

  function canRecall(message) {
    const minutes = Number(state.messageSettings.recallMinutes) || 2;
    return message.mine && !message.recalled && Date.now() - message.at <= minutes * 60 * 1000;
  }

  function messageItem(conversation, message) {
    const replied = message.replyTo ? findMessage(conversation, message.replyTo) : null;
    const content = message.recalled ? "这条消息已撤回" : escapeHtml(message.text);
    return `<div class="message ${message.mine ? "is-me" : ""}"><div class="message-bubble">${replied ? `<blockquote>${escapeHtml(replied.recalled ? "这条消息已撤回" : replied.text)}</blockquote>` : ""}${content}</div><div class="message-meta"><span>${new Date(message.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>${!message.recalled ? `<button type="button" data-reply="${message.id}">回复</button><button type="button" data-copy-message="${message.id}">复制</button>` : ""}${!message.recalled && !message.mine ? `<button type="button" data-report-message="${message.id}">举报</button>` : ""}${canRecall(message) ? `<button type="button" data-recall="${message.id}">撤回</button>` : ""}</div></div>`;
  }

  function bindChat(conversation) {
    if (!conversation) return;
    const conversationId = numericId(conversation.id);
    document.querySelectorAll("[data-conversation]").forEach((button) => button.addEventListener("click", async () => {
      activeConversation = button.dataset.conversation;
      replyTo = null;
      await performAction(`/api/conversations/${numericId(activeConversation)}/read`, {}, "", () => renderMessages());
    }));
    document.querySelector("#chat-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!ensureLoggedIn()) return;
      const text = String(new FormData(event.currentTarget).get("message") || "").trim();
      if (!text) return;
      const reply = replyTo;
      replyTo = null;
      await performAction(`/api/conversations/${conversationId}/messages`, { text, replyTo: reply || "" }, "", () => renderMessages());
    });
    document.querySelector("[data-cancel-reply]")?.addEventListener("click", () => { replyTo = null; renderMessages(); });
    document.querySelectorAll("[data-reply]").forEach((button) => button.addEventListener("click", () => { replyTo = button.dataset.reply; renderMessages(); }));
    document.querySelectorAll("[data-copy-message]").forEach((button) => button.addEventListener("click", async () => {
      const message = findMessage(conversation, button.dataset.copyMessage);
      if (!message) return;
      try { await navigator.clipboard.writeText(message.text); showToast("消息已复制"); }
      catch { showToast("浏览器未允许复制"); }
    }));
    document.querySelectorAll("[data-recall]").forEach((button) => button.addEventListener("click", async () => {
      const message = findMessage(conversation, button.dataset.recall);
      if (!canRecall(message)) return showToast("超过可撤回时间");
      await performAction(`/api/conversations/${conversationId}/messages/${numericId(button.dataset.recall)}/recall`, {}, "消息已撤回", () => renderMessages());
    }));
    document.querySelectorAll("[data-report-message]").forEach((button) => button.addEventListener("click", () => reportDialog("举报消息", conversation, button.dataset.reportMessage)));
    document.querySelector(`[data-report-conversation="${conversation.id}"]`)?.addEventListener("click", () => reportDialog("举报用户", conversation, null));
    document.querySelector(`[data-block="${conversation.id}"]`)?.addEventListener("click", async () => {
      const author = authorById(conversation.userId) || { id: conversation.userId, name: "未知用户" };
      await performAction(`/api/users/${numericId(author.id)}/block`, {}, "", () => renderMessages());
    });
    document.querySelector(`[data-delete-conversation="${conversation.id}"]`)?.addEventListener("click", () => {
      openModal("删除会话", "<p>会话只会从你的私信列表隐藏。服务器消息、对方记录和审核记录都会保留。</p>", '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="confirm-delete-conversation">确认删除</button></div>');
      document.querySelector("#confirm-delete-conversation").addEventListener("click", async () => {
        const ok = await performAction(`/api/conversations/${conversationId}/hide`, {}, "会话已删除", () => { activeConversation = null; closeModal(); renderMessages(); });
        if (!ok) closeModal();
      });
    });
    requestAnimationFrame(() => { const body = document.querySelector("#chat-body"); if (body) body.scrollTop = body.scrollHeight; });
  }

  function openMessageSettings() {
    if (!ensureLoggedIn()) return;
    const settings = state.messageSettings;
    openModal("私信设置", `<form id="message-settings-form"><label class="setting-row"><span><strong>接收陌生人消息</strong><small>关闭后，未关注的作者仍可查看你的主页。</small></span><input type="checkbox" name="allowStrangers" ${settings.allowStrangers ? "checked" : ""}></label><label class="setting-row"><span><strong>消息提醒</strong><small>新消息会在顶部通知区域显示未读数量。</small></span><input type="checkbox" name="notifications" ${settings.notifications ? "checked" : ""}></label><div class="field"><label for="recall-minutes">消息可撤回时间</label><select class="select" id="recall-minutes" name="recallMinutes">${[2, 5, 10].map((minutes) => `<option value="${minutes}" ${Number(settings.recallMinutes) === minutes ? "selected" : ""}>${minutes} 分钟</option>`).join("")}</select></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="save-message-settings">保存设置</button></div>');
    document.querySelector("#save-message-settings").addEventListener("click", async () => {
      const form = document.querySelector("#message-settings-form");
      const data = new FormData(form);
      await performAction("/api/message-settings", {
        allowStrangers: Boolean(data.get("allowStrangers")),
        notifications: Boolean(data.get("notifications")),
        recallMinutes: Number(data.get("recallMinutes"))
      }, "私信设置已保存", () => { closeModal(); renderMessages(); });
    });
  }

  function openNotificationSettings() {
    if (!ensureLoggedIn()) return;
    const settings = state.messageSettings;
    openModal("通知设置", `<form id="notification-settings-form"><label class="setting-row"><span><strong>接收站内通知</strong><small>关闭后顶部未读提醒会隐藏，已有通知仍会保留。</small></span><input type="checkbox" name="notifications" ${settings.notifications ? "checked" : ""}></label></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="save-notification-settings">保存设置</button></div>');
    document.querySelector("#save-notification-settings").addEventListener("click", async () => {
      const enabled = new FormData(document.querySelector("#notification-settings-form")).get("notifications") === "on";
      await performAction("/api/message-settings", {
        allowStrangers: settings.allowStrangers,
        notifications: enabled,
        recallMinutes: Number(settings.recallMinutes)
      }, "通知设置已保存", () => { closeModal(); renderHeader(); });
    });
  }


  function reportDialog(title, conversation, messageId) {
    if (!ensureLoggedIn()) return;
    const reasons = ["骚扰或辱骂", "色情或低俗内容", "暴力或威胁", "违法内容", "垃圾信息", "其他"];
    const author = authorById(conversation.userId) || { id: conversation.userId, name: "未知用户" };
    const message = messageId ? findMessage(conversation, messageId) : null;
    openModal(title, `<p>举报后只向管理员提交被举报消息和必要上下文，不会扫描全部私信。</p><form id="report-form"><div class="field"><label>举报原因</label><select class="select" name="reason">${reasons.map((reason) => `<option>${reason}</option>`).join("")}</select></div><div class="field"><label>补充说明</label><textarea class="textarea" name="detail" maxlength="500" placeholder="可补充具体情况"></textarea></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="submit-report">提交举报</button></div>');
    document.querySelector("#submit-report").addEventListener("click", async () => {
      const data = new FormData(document.querySelector("#report-form"));
      await performAction("/api/reports", {
        type: message ? "私信消息" : "用户",
        targetId: author.id,
        target: author.name,
        reason: String(data.get("reason") || ""),
        detail: String(data.get("detail") || ""),
        message: message?.text || ""
      }, "举报已提交", () => closeModal());
    });
  }

  function renderMonthly() {
    const awards = state.monthlyAwards.length ? state.monthlyAwards : state.monthlyPicks.map((workId, index) => ({ id: `legacy-${workId}`, workId, rank: index + 1, month: "往期", category: "", reason: "", selectedByName: "" }));
    const months = [...new Set(awards.map((award) => award.month))];
    const stage = months.length ? months.map((month) => {
      const rows = awards.filter((award) => award.month === month).sort((a, b) => Number(a.rank) - Number(b.rank));
      return `<section class="monthly-group"><div class="section-head"><div><p class="eyebrow">${escapeHtml(month)}</p><h2 class="section-title">月度优秀作品</h2></div><span class="muted">${rows.length} 部作品</span></div><div class="monthly-stage">${rows.map((award) => {
        const work = workById(award.workId);
        if (!work) return "";
        return `<article class="monthly-card"><span class="monthly-rank">${String(award.rank || 1).padStart(2, "0")}</span><div><span class="work-category">${escapeHtml(award.category || work.category || "综合")}</span><h2>${escapeHtml(work.title)}</h2><p>${escapeHtml(award.reason || work.excerpt || "")}</p><small>${escapeHtml(work.author)} · ${Number(work.likes) || 0} 点赞 · ${Number(work.views) || 0} 阅读</small>${award.selectedByName ? `<small class="monthly-byline">评选人：${escapeHtml(award.selectedByName)}</small>` : ""}<button class="button button-small button-primary" type="button" data-work="${work.id}">阅读作品</button></div></article>`;
      }).join("")}</div></section>`;
    }).join("") : '<div class="empty compact-empty">暂无月度优秀记录。</div>';
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">编辑评选与公开记录</p><h1 class="page-title">月度优秀作品</h1><p class="page-note">月度优秀由管理员按公开作品评选，记录评选人、时间与推荐理由，不等同于排行榜第一名。</p></div></header>${stage}</div>`;
  }

  function rankingStart(period) {
    const now = new Date();
    if (period === "month") return new Date(now.getFullYear(), now.getMonth(), 1).getTime();
    if (period === "quarter") return new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1).getTime();
    if (period === "year") return new Date(now.getFullYear(), 0, 1).getTime();
    return 0;
  }


  function rankingScore(work) {
    const weights = state.rankingWeights || DEFAULT_RANKING_WEIGHTS;
    return (Number(work.views) || 0) * Number(weights.views || 0)
      + (Number(work.likes) || 0) * Number(weights.likes || 0)
      + (Number(work.favorites) || 0) * Number(weights.favorites || 0)
      + (Number(work.commentsCount ?? work.comments) || 0) * Number(weights.comments || 0);
  }


  function rankedWorks() {
    const rows = state.rankings?.[rankingPeriod]?.works;
    if (Array.isArray(rows)) return rows;
    const start = rankingStart(rankingPeriod);
    return publicWorks().filter((work) => Number(work.publishedAt || work.createdAt || 0) >= start).sort((a, b) => rankingScore(b) - rankingScore(a) || Number(b.views || 0) - Number(a.views || 0));
  }


  function rankedAuthors() {
    const rows = state.rankings?.[rankingPeriod]?.authors;
    const authors = Array.isArray(rows) && rows.length ? rows : allAuthors().map((author) => {
      const works = worksByAuthor(author.name);
      const words = works.reduce((sum, work) => sum + wordCount(work), 0);
      const popularity = works.reduce((sum, work) => sum + (Number(work.likes) || 0) + (Number(work.favorites) || 0), 0);
      return { ...author, works: works.length, awards: Number(author.awardCount) || 0, words, popularity };
    }).filter((author) => author.works || author.awards || author.words);
    const key = ({ works: "works", awards: "awards", words: "words", popularity: "popularity" })[rankingAuthorMetric] || "works";
    return [...authors].sort((a, b) => Number(b[key]) - Number(a[key]) || Number(b.popularity) - Number(a.popularity));
  }


  function renderRanking() {
    const periods = [["month", "本月"], ["quarter", "本季"], ["year", "本年"], ["all", "总榜"]];
    const workRows = rankedWorks();
    const authorRows = rankedAuthors();
    const authorLabels = { works: "作品数量", awards: "获奖数量", words: "创作字数", popularity: "人气作者" };
    const authorKeys = { works: "works", awards: "awards", words: "words", popularity: "popularity" };
    const workPanel = workRows.length ? `<div class="rank-podium">${workRows.slice(0, 3).map((work, index) => `<article class="rank-podium-card rank-${index + 1}"><span>${index + 1}</span><button class="link-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><small>${escapeHtml(work.author)}</small><strong>${Number(work.score ?? rankingScore(work))} 热度</strong><small>${Number(work.views) || 0} 阅读 · ${Number(work.likes) || 0} 点赞 · ${Number(work.favorites) || 0} 收藏</small></article>`).join("")}</div><ol class="rank-list">${workRows.slice(3).map((work, index) => `<li class="rank-item"><span class="rank-number">${String(index + 4).padStart(2, "0")}</span><button class="link-button rank-title" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><span class="muted">${escapeHtml(work.author)} · ${Number(work.score ?? rankingScore(work))} 热度 · ${Number(work.views) || 0} 阅读 · ${Number(work.likes) || 0} 点赞 · ${Number(work.comments) || 0} 评论</span></li>`).join("")}</ol>` : '<div class="empty compact-empty">所选周期暂无排行数据。</div>';
    const authorPanel = authorRows.length ? `<ol class="rank-list">${authorRows.map((author, index) => `<li class="rank-item"><span class="rank-number">${String(index + 1).padStart(2, "0")}</span><button class="link-button rank-title" type="button" data-author="${author.id}">${escapeHtml(author.name)}</button><span class="muted">${authorLabels[rankingAuthorMetric]} ${Number(author[authorKeys[rankingAuthorMetric]]) || 0} · ${Number(author.works) || 0} 篇作品 · ${Number(author.awards) || 0} 次获奖 · ${Number(author.words) || 0} 字</span></li>`).join("")}</ol>` : '<div class="empty compact-empty">暂无作者排行数据。</div>';
    const weights = state.rankingWeights || DEFAULT_RANKING_WEIGHTS;
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">真实数据，不合成虚假结果</p><h1 class="page-title">排行榜</h1><p class="page-note">只统计已审核、已公开且未删除作品。月度 / 季度 / 年度热度只计算所选周期内的真实互动；总榜使用现有累计阅读。热度 = 阅读 ${weights.views} + 点赞 ${weights.likes} + 收藏 ${weights.favorites} + 评论 ${weights.comments} 的加权结果。</p></div></header><div class="ranking-controls"><div class="rank-tabs">${periods.map(([id, label]) => `<button class="${rankingPeriod === id ? "is-active" : ""}" type="button" data-rank-period="${id}">${label}</button>`).join("")}</div><div class="rank-tabs"><button class="${rankingBoard === "works" ? "is-active" : ""}" type="button" data-rank-board="works">作品榜</button><button class="${rankingBoard === "authors" ? "is-active" : ""}" type="button" data-rank-board="authors">作者榜</button></div></div>${rankingBoard === "works" ? workPanel : `<div class="rank-tabs rank-subtabs">${Object.entries(authorLabels).map(([id, label]) => `<button class="${rankingAuthorMetric === id ? "is-active" : ""}" type="button" data-rank-author-metric="${id}">${label}</button>`).join("")}</div>${authorPanel}`}</div>`;
  }

  function activityCard(activity) {
    return `<article class="activity-card"><div class="activity-date">${escapeHtml(activity.date || "")}<br><small>${escapeHtml(activity.status || "")}</small></div><div><h3>${escapeHtml(activity.title)}</h3><p class="muted">${escapeHtml(activity.desc || "")}</p><button class="button button-small" type="button" data-activity="${activity.id}">查看活动</button></div></article>`;
  }

  function renderActivities() {
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">把写作带到现场</p><h1 class="page-title">文学活动</h1></div><p class="page-note">共读、写作实验室和改稿会。</p></header>${state.activities.length ? `<div class="activity-grid" style="margin-top:28px">${state.activities.map(activityCard).join("")}</div>` : '<div class="empty compact-empty">暂无已发布活动。</div>'}</div>`;
  }

  function renderAdmin() {
    if (!isAdmin()) return renderMissing("需要管理员权限才能进入管理后台");
    const tabs = ["概览", "作品审核", "评论管理", "私信举报", "用户管理", "月度评选", "文学活动", "公告", "Agent 审核", "安全日志"];
    if (isSuperAdmin()) tabs.splice(5, 0, "管理员管理");
    if (!tabs.includes(adminTab)) adminTab = "概览";
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">运营控制台</p><h1 class="page-title">管理后台</h1><p class="page-note">服务端校验高级管理员与超级管理员权限，前端只负责显示可执行操作。</p></div></header><nav class="admin-tabs">${tabs.map((tab) => `<button class="${adminTab === tab ? "is-active" : ""}" type="button" data-admin-tab="${tab}">${tab}</button>`).join("")}</nav><section id="admin-content">${adminContent()}</section></div>`;
    document.querySelectorAll("[data-admin-tab]").forEach((button) => button.addEventListener("click", () => { adminTab = button.dataset.adminTab; renderAdmin(); }));
    bindAdminActions();
  }

  function bindAdminActions() {
    document.querySelector("#admin-ann-create")?.addEventListener("click", async () => {
      if (!ensureLoggedIn()) return;
      const title = document.querySelector("#admin-ann-title").value.trim();
      const content = document.querySelector("#admin-ann-content").value.trim();
      if (!title || !content) return showToast("请填写公告标题和内容");
      await performAction("/api/admin/announcements", { title, content }, "公告已发布", () => renderAdmin());
    });
    document.querySelectorAll("[data-ann-toggle]").forEach((button) => button.addEventListener("click", async () => {
      const item = state.announcements.find((announcement) => announcement.id === button.dataset.annToggle);
      if (!item) return;
      await performAction(`/api/admin/announcements/${numericId(item.id)}/toggle`, {}, item.status === "published" ? "公告已撤回" : "公告已发布", () => renderAdmin());
    }));
    document.querySelectorAll("[data-review-action]").forEach((button) => button.addEventListener("click", async () => {
      const action = button.dataset.reviewAction;
      let note = "";
      if (action === "reject") note = await promptDialog("退回意见", "可选，作者会看到。", "") || "";
      await performAction(`/api/admin/works/${numericId(button.dataset.reviewWork)}/review`, { action, note }, "审核状态已更新", () => renderAdmin());
    }));
    document.querySelectorAll("[data-comment-delete]").forEach((button) => button.addEventListener("click", async () => {
      if (!await confirmDialog("确定删除这条评论吗？")) return;
      await performAction(`/api/admin/comments/${numericId(button.dataset.commentDelete)}/delete`, {}, "评论已删除", () => renderAdmin());
    }));
    document.querySelectorAll("[data-report-status]").forEach((select) => select.addEventListener("change", () => performAction(`/api/admin/reports/${numericId(select.dataset.reportStatus)}/status`, { status: select.value }, "举报状态已更新", () => renderAdmin())));
    document.querySelectorAll("[data-user-status]").forEach((button) => button.addEventListener("click", async () => {
      const status = button.dataset.userStatus;
      if (!await confirmDialog(status === "suspended" ? "确定暂停该用户吗？" : "确定恢复该用户吗？")) return;
      await performAction(`/api/admin/users/${numericId(button.dataset.userId)}/status`, { status }, "用户状态已更新", () => renderAdmin());
    }));
    document.querySelectorAll("[data-appoint-admin]").forEach((button) => button.addEventListener("click", async () => {
      if (!await confirmDialog("确定任命该用户为高级管理员吗？")) return;
      await performAction("/api/admin/admins/appoint", { userId: button.dataset.appointAdmin }, "高级管理员已任命", () => renderAdmin());
    }));
    document.querySelectorAll("[data-revoke-admin]").forEach((button) => button.addEventListener("click", async () => {
      if (!await confirmDialog("确定撤销该高级管理员吗？")) return;
      await performAction("/api/admin/admins/revoke", { userId: button.dataset.revokeAdmin }, "高级管理员已撤销", () => renderAdmin());
    }));
    document.querySelector("#admin-award-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      await performAction("/api/admin/monthly-awards", {
        workId: String(data.get("workId") || ""),
        month: String(data.get("month") || ""),
        rank: Number(data.get("rank") || 1),
        reason: String(data.get("reason") || "").trim()
      }, "月度优秀已记录", () => renderAdmin());
    });
    document.querySelectorAll("[data-revoke-award]").forEach((button) => button.addEventListener("click", async () => {
      if (!await confirmDialog("确定撤销这条月度优秀记录吗？")) return;
      await performAction(`/api/admin/monthly-awards/${numericId(button.dataset.revokeAward)}/revoke`, {}, "月度优秀已撤销", () => renderAdmin());
    }));
    document.querySelector("#admin-activity-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      await performAction("/api/admin/activities", {
        title: String(data.get("title") || "").trim(),
        description: String(data.get("description") || "").trim(),
        startsAt: String(data.get("startsAt") || ""),
        endsAt: String(data.get("endsAt") || ""),
        status: String(data.get("status") || "筹备中"),
        rules: String(data.get("rules") || "").trim()
      }, "活动已创建", () => renderAdmin());
    });
    document.querySelector("#admin-appoint-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      await performAction("/api/admin/admins/appoint", {
        userId: String(data.get("userId") || "")
      }, "高级管理员已任命", () => renderAdmin());
    });
    document.querySelector("#admin-transfer-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(event.currentTarget);
      await performAction("/api/admin/admins/transfer", {
        oldAdminId: String(data.get("oldAdminId") || ""),
        newAdminId: String(data.get("newAdminId") || ""),
        reason: String(data.get("reason") || "").trim()
      }, "高级管理员权限已转交", () => renderAdmin());
    });
  }

  function adminContent() {
    const comments = state.works.flatMap((work) => (work.comments || []).map((comment) => ({ ...comment, workTitle: work.title })));
    const pending = state.works.filter((work) => work.status === "pending");
    const activeAwards = state.monthlyAwards.filter((award) => award.status === "active");
    const userRows = state.users.length ? state.users : allAuthors();
    if (adminTab === "概览") return `<div class="admin-grid"><div class="metric"><strong>${pending.length}</strong><span>待审核投稿</span></div><div class="metric"><strong>${state.works.length}</strong><span>作品总数</span></div><div class="metric"><strong>${state.reports.filter((item) => item.status === "待处理").length}</strong><span>待处理举报</span></div><div class="metric"><strong>${activeAwards.length}</strong><span>月度优秀</span></div><div class="metric"><strong>${state.users.length}</strong><span>用户账号</span></div><div class="metric"><strong>${state.activities.length}</strong><span>文学活动</span></div></div><ul class="admin-list"><li class="admin-row"><span><strong>审核流程</strong><small class="admin-note">投稿先进入审核中，管理员可发布、退回或下架。</small></span><span class="muted">服务端校验</span></li><li class="admin-row"><span><strong>Agent 边界</strong><small class="admin-note">Agent 只辅助分析，不自动决定作品是否发布。</small></span><span class="status-pill">PASSIVE</span></li><li class="admin-row"><span><strong>最近操作</strong><small class="admin-note">${escapeHtml(state.auditLogs[0]?.text || "暂无操作记录")}</small></span><span class="muted">${escapeHtml(state.auditLogs[0]?.at || "")}</span></li></ul>`;
    if (adminTab === "作品审核") return `<div class="panel admin-panel"><div class="section-head"><div><h2 class="section-title">作品审核</h2><p class="muted">公开作品与待审核投稿都从真实数据库读取。</p></div><span class="muted">${pending.length} 篇待处理</span></div><ul class="admin-list">${state.works.length ? state.works.map((work) => `<li class="admin-row"><span><strong>${escapeHtml(work.title)}</strong><small class="admin-note">${escapeHtml(work.author)} · ${escapeHtml(work.category)} · ${escapeHtml(statusLabel(work.status))} · ${Number(work.views) || 0} 阅读${work.reviewNote ? ` · 审核意见：${escapeHtml(work.reviewNote)}` : ""}</small></span><div class="admin-actions">${work.status === "pending" ? `<button class="button button-small" type="button" data-review-action="reject" data-review-work="${work.id}">退回</button><button class="button button-small button-primary" type="button" data-review-action="publish" data-review-work="${work.id}">通过</button>` : work.status === "published" ? `<button class="button button-small button-quiet" type="button" data-review-action="hide" data-review-work="${work.id}">下架</button>` : `<button class="button button-small button-primary" type="button" data-review-action="publish" data-review-work="${work.id}">重新公开</button>`}</div></li>`).join("") : '<li class="empty">暂无作品。</li>'}</ul></div>`;
    if (adminTab === "评论管理") return `<div class="panel admin-panel"><div class="section-head"><h2 class="section-title">评论管理</h2><span class="muted">${comments.length} 条</span></div><ul class="admin-list">${comments.length ? comments.map((comment) => `<li class="admin-row"><span><strong>${escapeHtml(comment.who)}</strong><small class="admin-note">${escapeHtml(comment.text)} · 《${escapeHtml(comment.workTitle)}》</small></span><button class="button button-small button-danger" type="button" data-comment-delete="${comment.id}">删除</button></li>`).join("") : '<li class="empty">当前没有读者评论。</li>'}</ul></div>`;
    if (adminTab === "私信举报") return `<div class="panel admin-panel"><h2 class="section-title">举报处理</h2><p class="muted">只处理被举报内容和必要上下文，不扫描普通私信。</p><ul class="admin-list">${state.reports.length ? state.reports.map((report) => `<li class="admin-row"><span><strong>${escapeHtml(report.target)} · ${escapeHtml(report.reason)}</strong><small class="admin-note">${escapeHtml(report.detail || report.message || "未补充说明")} · ${escapeHtml(report.at)}</small></span><select class="select select-small" data-report-status="${report.id}">${["待处理", "处理中", "已处理", "已驳回"].map((status) => `<option ${report.status === status ? "selected" : ""}>${status}</option>`).join("")}</select></li>`).join("") : '<li class="empty">当前没有举报记录。</li>'}</ul></div>`;
    if (adminTab === "用户管理") return `<div class="panel admin-panel"><h2 class="section-title">用户与作者</h2><ul class="admin-list">${userRows.map((user) => `<li class="admin-row"><span><strong>${escapeHtml(user.name)}</strong><small class="admin-note">${escapeHtml(user.bio || "暂无简介")} · ${escapeHtml(user.adminLevel === "super" ? "超级管理员" : user.adminLevel === "senior" ? "高级管理员" : "普通用户")} · ${escapeHtml(user.accountStatus === "suspended" ? "已暂停" : "正常")}</small></span><div class="admin-actions">${user.id !== currentUserId() && !user.adminLevel ? `<button class="button button-small ${user.accountStatus === "suspended" ? "button-primary" : "button-quiet"}" type="button" data-user-id="${user.id}" data-user-status="${user.accountStatus === "suspended" ? "active" : "suspended"}">${user.accountStatus === "suspended" ? "恢复" : "暂停"}</button>` : ""}</div></li>`).join("")}</ul></div>`;
    if (adminTab === "管理员管理") return `<div class="panel admin-panel"><h2 class="section-title">高级管理员设置</h2><p class="muted">超级管理员最多任命 2 名高级管理员，名额限制由服务端强制校验。</p><div class="admin-form-grid"><form id="admin-appoint-form" class="admin-form"><h3>任命高级管理员</h3><div class="field"><label>普通用户</label><select class="select" name="userId">${userRows.filter((user) => !user.adminLevel && user.role !== "admin").map((user) => `<option value="${user.id}">${escapeHtml(user.name)}</option>`).join("") || '<option value="">暂无可任命用户</option>'}</select></div><button class="button button-primary" type="submit">任命</button></form><form id="admin-transfer-form" class="admin-form"><h3>转移高级管理员</h3><div class="field"><label>原高级管理员</label><select class="select" name="oldAdminId">${state.adminRoles.filter((role) => role.level === "senior").map((role) => `<option value="${role.userId}">${escapeHtml(role.name || role.userId)}</option>`).join("") || '<option value="">暂无高级管理员</option>'}</select></div><div class="field"><label>接任普通用户</label><select class="select" name="newAdminId">${userRows.filter((user) => !user.adminLevel && user.role !== "admin").map((user) => `<option value="${user.id}">${escapeHtml(user.name)}</option>`).join("") || '<option value="">暂无可接任用户</option>'}</select></div><div class="field"><label>转交原因</label><input class="input" name="reason" maxlength="300" required placeholder="填写转交原因"></div><button class="button button-primary" type="submit">转交权限</button></form></div><h3 class="section-title">当前管理员</h3><ul class="admin-list">${state.adminRoles.map((role) => `<li class="admin-row"><span><strong>${escapeHtml(role.name || role.userId)}</strong><small class="admin-note">${escapeHtml(role.level === "super" ? "超级管理员" : "高级管理员")} · 任命于 ${escapeHtml(role.appointedAt)}</small></span>${role.level === "senior" && isSuperAdmin() ? `<button class="button button-small button-danger" type="button" data-revoke-admin="${role.userId}">撤销</button>` : '<span class="status-pill">最高权限</span>'}</li>`).join("")}</ul><h3 class="section-title">权限转交记录</h3><ul class="admin-list">${state.adminTransfers.length ? state.adminTransfers.map((item) => `<li class="admin-row"><span><strong>${escapeHtml(item.oldName || item.oldAdminId)} → ${escapeHtml(item.newName || item.newAdminId)}</strong><small class="admin-note">${escapeHtml(item.reason)} · 操作人 ${escapeHtml(item.operatorName || item.operatorId)} · ${escapeHtml(item.at)}</small></span></li>`).join("") : '<li class="empty">暂无转交记录。</li>'}</ul></div>`;
    if (adminTab === "月度评选") { const publicOptions = state.works.filter(isPublishedWork); return `<div class="panel admin-panel"><h2 class="section-title">月度优秀评选</h2><p class="muted">只允许公开作品进入候选池。获奖记录会保存月份、类别、评选人、时间和推荐理由。</p><form id="admin-award-form" class="award-form"><div class="form-grid"><div class="field"><label>月份</label><input class="input" type="month" name="month" value="${new Date().toISOString().slice(0, 7)}" required></div><div class="field"><label>作品</label><select class="select" name="workId" required>${publicOptions.map((work) => `<option value="${work.id}">${escapeHtml(work.title)} · ${escapeHtml(work.author)}</option>`).join("") || '<option value="">暂无公开作品</option>'}</select></div><div class="field"><label>名次</label><input class="input" type="number" name="rank" min="1" max="20" value="1" required></div></div><div class="field"><label>推荐理由</label><textarea class="textarea" name="reason" maxlength="300" placeholder="说明该作品的文学价值或评选理由"></textarea></div><button class="button button-primary" type="submit">保存评选</button></form><h3 class="section-title">正式获奖记录</h3><ul class="admin-list">${activeAwards.length ? activeAwards.map((award) => `<li class="admin-row"><span><strong>${escapeHtml(award.month)} · ${escapeHtml(workById(award.workId)?.title || "作品")}</strong><small class="admin-note">${escapeHtml(award.category || "综合")} · 第 ${award.rank} 名 · ${escapeHtml(award.reason || "暂无推荐理由")} · 由 ${escapeHtml(award.selectedByName || "管理员")} 评选</small></span><button class="button button-small button-danger" type="button" data-revoke-award="${award.id}">撤销</button></li>`).join("") : '<li class="empty">暂无月度优秀记录。</li>'}</ul></div>`; }
    if (adminTab === "文学活动") return `<div class="panel admin-panel"><h2 class="section-title">文学活动</h2><form id="admin-activity-form" class="admin-form"><div class="form-grid"><div class="field"><label>活动名称</label><input class="input" name="title" maxlength="80" required></div><div class="field"><label>状态</label><select class="select" name="status">${["筹备中", "报名中", "进行中", "已结束"].map((status) => `<option>${status}</option>`).join("")}</select></div><div class="field"><label>开始时间</label><input class="input" type="date" name="startsAt"></div><div class="field"><label>截止时间</label><input class="input" type="date" name="endsAt"></div></div><div class="field"><label>活动介绍</label><textarea class="textarea" name="description" maxlength="1000"></textarea></div><div class="field"><label>活动规则</label><textarea class="textarea" name="rules" maxlength="1000"></textarea></div><button class="button button-primary" type="submit">创建活动</button></form><ul class="admin-list">${state.activities.length ? state.activities.map((activity) => `<li class="admin-row"><span><strong>${escapeHtml(activity.title)}</strong><small class="admin-note">${escapeHtml(activity.desc)} · ${escapeHtml(activity.date || "时间待定")} · ${escapeHtml(activity.status)}</small></span></li>`).join("") : '<li class="empty">暂无活动。</li>'}</ul></div>`;
    if (adminTab === "公告") return `<div class="admin-announcement"><div class="field"><label>公告标题</label><input class="input" id="admin-ann-title" maxlength="80" placeholder="例如：十月共读会开始报名"></div><div class="field"><label>公告内容</label><textarea class="textarea" id="admin-ann-content" maxlength="1000" placeholder="填写需要告知全体用户的简短内容"></textarea></div><button class="button button-primary" type="button" id="admin-ann-create">发布公告</button></div><ul class="admin-list">${state.announcements.length ? state.announcements.map((item) => `<li class="admin-row"><span><strong>${escapeHtml(item.title)}</strong><small class="admin-note">${escapeHtml(item.status === "published" ? "已发布" : "已归档")} · ${escapeHtml(item.content)}</small></span><button class="button button-small ${item.status === "published" ? "button-quiet" : "button-primary"}" type="button" data-ann-toggle="${item.id}">${item.status === "published" ? "撤回" : "发布"}</button></li>`).join("") : '<li class="empty">暂无公告。</li>'}</ul>`;
    if (adminTab === "Agent 审核") return `<div class="panel admin-panel"><div class="section-head"><h2 class="section-title">Agent 审核</h2><span class="status-pill">PASSIVE</span></div><div class="admin-grid"><div class="metric"><strong>${state.works.length + comments.length}</strong><span>公开内容队列</span></div><div class="metric"><strong>${state.reports.length}</strong><span>举报上下文</span></div><div class="metric"><strong>0</strong><span>自动处置</span></div></div><ul class="admin-list"><li class="admin-row"><span>风险分级<small class="admin-note">LOW · MEDIUM · HIGH · CRITICAL</small></span><span class="muted">等待审核</span></li><li class="admin-row"><span>最终动作<small class="admin-note">模型只输出结构化分析，管理员确认 ALLOW、REVIEW 或 BLOCK。</small></span><span class="muted">人工确认</span></li><li class="admin-row"><span>隐私边界<small class="admin-note">普通私信不扫描，只有举报消息和必要上下文进入审核。</small></span><span class="muted">已启用</span></li></ul></div>`;
    if (adminTab === "安全日志") return `<div class="panel admin-panel"><h2 class="section-title">操作与审核日志</h2><ul class="admin-list">${state.auditLogs.length ? state.auditLogs.map((item) => `<li class="admin-row"><span><strong>${escapeHtml(item.actorName || "系统")}</strong><small class="admin-note">${escapeHtml(item.text)}</small></span><time class="muted">${escapeHtml(item.at)}</time></li>`).join("") : '<li class="empty">暂无操作记录。</li>'}</ul></div>`;
    return `<div class="panel admin-panel"><h2 class="section-title">${escapeHtml(adminTab)}</h2><p class="muted">当前分类没有待处理记录。</p></div>`;
  }

  function renderNotifications() {
    if (!ensureLoggedIn()) return;
    openModal("通知", state.notifications.length ? `<ul class="admin-list">${state.notifications.map((item) => `<li class="admin-row"><span>${escapeHtml(item.text)}</span><time class="muted">${escapeHtml(item.at)}</time></li>`).join("")}</ul>` : "<p>暂无通知。</p>");
    performAction("/api/notifications/read", {}, "", () => renderHeader());
  }

  function openPublish(workId = "") {
    if (!ensureLoggedIn()) return;
    const existing = workId ? workById(workId) : null;
    if (workId && !existing) return showToast("作品不存在");
    const bodyText = (existing?.body || []).join("\n\n");
    const form = `
      <form id="publish-form" class="publish-form">
        <section class="publish-section"><div class="publish-section-head"><span>01</span><div><h3>基础信息</h3><p>标题、体裁、标签与作品简介。</p></div></div>
          <div class="form-grid"><div class="field"><label>作品标题</label><input class="input" name="title" maxlength="80" value="${escapeHtml(existing?.title || "")}" required autofocus></div><div class="field"><label>作品类型</label><select class="select" name="category">${categories.slice(1).map((category) => `<option ${existing?.category === category ? "selected" : ""}>${category}</option>`).join("")}</select></div></div>
          <div class="field"><label>标签</label><input class="input" name="tags" maxlength="120" value="${escapeHtml((existing?.tags || []).join("，"))}" placeholder="多个标签用逗号分隔"></div>
          <div class="field"><label>作品简介</label><textarea class="textarea" name="excerpt" maxlength="200" placeholder="一句话说明作品内容，可选">${escapeHtml(existing?.excerpt || "")}</textarea></div>
        </section>
        <section class="publish-section"><div class="publish-section-head"><span>02</span><div><h3>正文</h3><p>用空行分隔段落。提交前请检查作品完整性。</p></div></div>
          <div class="field"><textarea class="textarea publish-body" name="body" maxlength="10000" placeholder="在这里写下作品正文">${escapeHtml(bodyText)}</textarea></div>
          <div class="publish-status"><span id="publish-word-count">${bodyText.replace(/\s/g, "").length} 字</span><span id="publish-save-state">尚未保存</span></div>
        </section>
        <section class="publish-section"><div class="publish-section-head"><span>03</span><div><h3>投稿设置</h3><p>以下开关由服务端保存。</p></div></div>
          <label class="setting-row"><span><strong>公开展示</strong><small>审核通过后允许所有访客阅读。</small></span><input type="checkbox" name="isPublic" ${existing?.isPublic === false ? "" : "checked"}></label>
          <label class="setting-row"><span><strong>允许评论</strong><small>关闭后读者不能发表评论。</small></span><input type="checkbox" name="allowComments" ${existing?.allowComments === false ? "" : "checked"}></label>
          <label class="setting-row"><span><strong>允许收藏</strong><small>关闭后读者不能收藏作品。</small></span><input type="checkbox" name="allowFavorites" ${existing?.allowFavorites === false ? "" : "checked"}></label>
        </section>
        <section class="publish-section"><div class="publish-section-head"><span>04</span><div><h3>原创声明</h3><p>确认后才能提交审核。</p></div></div>
          <label class="setting-row"><span><strong>原创与发表权确认</strong><small>我确认这是我的原创作品，或我拥有合法发表权。</small></span><input type="checkbox" name="originalConfirmed" ${existing?.originalConfirmed ? "checked" : ""}></label>
          <label class="setting-row"><span><strong>公开展示授权</strong><small>我同意芳菲文学社按照平台规则公开展示该作品。</small></span><input type="checkbox" name="rightsConfirmed" ${existing?.rightsConfirmed ? "checked" : ""}></label>
        </section>
      </form>`;
    openModal(existing ? "编辑投稿" : "投稿作品", form, '<div class="modal-actions publish-actions"><button class="button" type="button" id="save-draft">保存草稿</button><button class="button button-primary" type="button" id="submit-review">提交审核</button></div>');
    const body = document.querySelector(".publish-body");
    const wordCount = document.querySelector("#publish-word-count");
    const saveState = document.querySelector("#publish-save-state");
    body?.addEventListener("input", () => { wordCount.textContent = `${body.value.replace(/\s/g, "").length} 字`; saveState.textContent = "有未保存修改"; });
    const saveDraft = async (action) => {
      const formElement = document.querySelector("#publish-form");
      if (!formElement.reportValidity()) return;
      const data = new FormData(formElement);
      const bodyParts = String(data.get("body") || "").replace(/\r/g, "").split(/\n\s*\n/).map((part) => part.trim()).filter(Boolean);
      if (action === "submit" && bodyParts.length === 0) return showToast("提交审核前需要填写正文");
      if (action === "submit" && (!data.get("originalConfirmed") || !data.get("rightsConfirmed"))) return showToast("请先确认原创与公开展示授权");
      const payload = {
        action,
        title: String(data.get("title") || "").trim(),
        category: String(data.get("category") || "其他"),
        tags: String(data.get("tags") || "").split(/[,，]/).map((tag) => tag.trim()).filter(Boolean),
        excerpt: String(data.get("excerpt") || "").trim(),
        body: bodyParts,
        isPublic: data.get("isPublic") === "on",
        allowComments: data.get("allowComments") === "on",
        allowFavorites: data.get("allowFavorites") === "on",
        originalConfirmed: data.get("originalConfirmed") === "on",
        rightsConfirmed: data.get("rightsConfirmed") === "on"
      };
      const path = existing ? `/api/works/${numericId(existing.id)}` : "/api/works";
      await performAction(path, payload, action === "draft" ? "草稿已保存" : "作品已提交审核", () => { closeModal(); profileTab = "works"; setRoute("profile"); });
    };
    document.querySelector("#save-draft")?.addEventListener("click", () => saveDraft("draft"));
    document.querySelector("#submit-review")?.addEventListener("click", () => saveDraft("submit"));
  }

  function toggleWorkLike(workId) {
    if (!workById(workId)) return;
    return performAction(`/api/works/${numericId(workId)}/like`, {}, "", () => renderWork(workId));
  }

  function toggleWorkFavorite(workId) {
    if (!workById(workId)) return;
    return performAction(`/api/works/${numericId(workId)}/favorite`, {}, "", () => renderWork(workId));
  }

  async function shareWork(workId) {
    const work = workById(workId);
    if (!work) return;
    const url = `${location.origin}${location.pathname}#/work/${work.id}`;
    try {
      if (navigator.share) await navigator.share({ title: work.title, text: work.excerpt || "", url });
      else await navigator.clipboard.writeText(url);
      showToast(navigator.share ? "分享面板已打开" : "作品链接已复制");
    } catch {
      showToast("浏览器未允许分享");
    }
  }

  function reportWorkDialog(workId) {
    if (!ensureLoggedIn()) return;
    const work = workById(workId);
    if (!work) return;
    const reasons = ["内容侵权", "色情或低俗内容", "暴力或威胁", "违法内容", "垃圾信息", "其他"];
    openModal("举报作品", `<p>举报只提交作品和必要说明。</p><form id="report-work-form"><div class="field"><label>举报原因</label><select class="select" name="reason">${reasons.map((reason) => `<option>${reason}</option>`).join("")}</select></div><div class="field"><label>补充说明</label><textarea class="textarea" name="detail" maxlength="500" placeholder="可补充具体情况"></textarea></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="submit-work-report">提交举报</button></div>');
    document.querySelector("#submit-work-report").addEventListener("click", async () => {
      const data = new FormData(document.querySelector("#report-work-form"));
      await performAction("/api/reports", {
        type: "作品",
        targetId: work.id,
        target: work.title,
        reason: String(data.get("reason") || ""),
        detail: String(data.get("detail") || ""),
        message: ""
      }, "举报已提交", () => closeModal());
    });
  }

  function renderMissing(message) {
    app.innerHTML = `<div class="page"><div class="empty">${escapeHtml(message)}</div></div>`;
  }

  function render() {
    renderHeader();
    if (route === "home") return renderHome();
    if (route === "works") return renderWorks();
    if (route.startsWith("work/")) return renderWork(route.split("/")[1]);
    if (route === "authors") return renderAuthors();
    if (route.startsWith("author/")) return renderAuthor(route.split("/")[1]);
    if (route === "messages") return renderMessages();
    if (route === "monthly") return renderMonthly();
    if (route === "ranking") return renderRanking();
    if (route === "activities") return renderActivities();
    if (route === "profile") return renderProfile();
    if (route === "admin") return renderAdmin();
    return renderHome();
  }

  async function startConversation(authorId) {
    if (!ensureLoggedIn()) return;
    try {
      applyBootstrap(await apiRequest("/api/conversations", { method: "POST", body: { authorId } }));
      const conversation = state.conversations.find((item) => item.userId === authorId && !item.hidden);
      activeConversation = conversation?.id || null;
      setRoute("messages");
    } catch (error) {
      handleApiError(error);
    }
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.matches("[data-message-settings]")) return openMessageSettings();
    if (target.matches("[data-profile-notifications]")) return openNotificationSettings();
    if (target.matches("[data-block-author]")) return performAction(`/api/users/${numericId(target.dataset.blockAuthor)}/block`, {}, "已解除拉黑", () => openPrivacySettings());
    if (target.matches("[data-profile-privacy]")) return openPrivacySettings();
    if (target.matches("[data-profile-password]")) return openChangePassword();
    if (target.matches("[data-profile-edit]")) return openProfileEditor();
    if (target.matches("[data-profile-tab]")) { profileTab = target.dataset.profileTab; return renderProfile(); }
    if (target.matches("[data-logout]")) return logoutAccount();
    if (target.matches("[data-open-settings]")) return openSettings();
    if (target.matches("[data-close-modal], #modal-close")) return closeModal();
    if (target.matches("[data-edit-work]")) return openPublish(target.dataset.editWork);
    if (target.matches("[data-rank-period]")) { rankingPeriod = target.dataset.rankPeriod; return renderRanking(); }
    if (target.matches("[data-rank-board]")) { rankingBoard = target.dataset.rankBoard; return renderRanking(); }
    if (target.matches("[data-rank-author-metric]")) { rankingAuthorMetric = target.dataset.rankAuthorMetric; return renderRanking(); }
    if (target.matches("[data-route]")) return setRoute(target.dataset.route);
    if (target.matches("[data-like-work]")) return toggleWorkLike(target.dataset.likeWork);
    if (target.matches("[data-favorite-work]")) return toggleWorkFavorite(target.dataset.favoriteWork);
    if (target.matches("[data-share-work]")) return shareWork(target.dataset.shareWork);
    if (target.matches("[data-report-work]")) return reportWorkDialog(target.dataset.reportWork);
    if (target.matches("[data-work]")) return setRoute(`work/${target.dataset.work}`);
    if (target.matches("[data-author]")) return setRoute(`author/${target.dataset.author}`);
    if (target.matches("[data-message-author]")) return startConversation(target.dataset.messageAuthor);
    if (target.matches("[data-publish]")) return openPublish();
    if (target.matches("[data-filter]")) { workFilter = target.dataset.filter; return renderWorks(); }
    if (target.matches("[data-follow]")) {
      const authorId = target.dataset.follow;
      return performAction(`/api/authors/${numericId(authorId)}/follow`, {}, "", () => renderAuthor(authorId));
    }
    if (target.matches("[data-theme-choice]")) {
      applyTheme(target.dataset.themeChoice);
      closeModal();
      render();
      return showToast("主题已切换");
    }
    if (target.matches("[data-activity]")) { const activity = byId(target.dataset.activity, state.activities); return openModal(activity.title, `<p>${escapeHtml(activity.desc)}</p><p class="muted">活动时间：${escapeHtml(activity.date)} · 当前状态：${escapeHtml(activity.status)}。报名通知会出现在站内消息中。</p>`); }
  });

  document.querySelector("#publish-button").addEventListener("click", openPublish);
  document.querySelector("#notification-button").addEventListener("click", renderNotifications);
  document.querySelector("#user-button").addEventListener("click", openProfile);
  modalLayer.addEventListener("click", (event) => { if (event.target === modalLayer) closeModal(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !modalLayer.hidden) closeModal(); });
  window.addEventListener("hashchange", () => { route = location.hash.replace(/^#\/?/, "") || "home"; render(); });
  applyTheme(localStorage.getItem(THEME_KEY) || "qingli");
  (async () => {
    try {
      await refreshState(false);
    } catch {
      state = loadState();
      showToast("服务器暂时无法连接，请稍后刷新");
    }
    render();
  })();
})();
