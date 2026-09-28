(() => {
  "use strict";

  const STORAGE_KEY = "fangfei-literary-demo-v1";
  const categories = ["全部", "小说", "诗歌", "散文", "随笔", "剧本", "科幻", "其他"];
  const THEMES = {
    starry: { name: "星穹·探索", image: "images/styles/starry.jpg", description: "星空、远方与未完成的句子。" },
    deepsea: { name: "深海·幻境", image: "images/styles/deepsea.jpg", description: "安静下潜，听见文字里的回声。" },
    sky: { name: "晴空·幻想", image: "images/styles/sky.jpg", description: "明亮轻盈，适合写下新的开始。" },
    flower: { name: "花羽·梦境", image: "images/styles/flower.png", description: "花瓣、羽毛和柔软的叙事。" },
    dragon: { name: "星龙·秘境", image: "images/styles/dragon.jpg", description: "史诗、奇想与辽阔的想象。" },
    qingli: { name: "青璃·映界", image: "images/styles/qingli.webp", description: "清透青绿与柔和暖光交织。" }
  };
  const THEME_KEY = "fangfei_theme_v1";
  const DATA_VERSION = 3;
  const EMPTY_STATE = {
    schemaVersion: DATA_VERSION,
    currentUser: { id: "me", name: "我", role: "reader" },
    followed: [],
    blocked: [],
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
    conversations: []
  };
  const LEGACY_SEED_IDS = {
    works: new Set(["w1", "w2", "w3", "w4", "w5", "w6"]),
    authors: new Set(["a1", "a2", "a3", "a4", "a5", "a6"]),
    activities: new Set(["e1", "e2", "e3", "e4"]),
    conversations: new Set(["cv1", "cv2", "cv3"]),
    notifications: new Set(["n1", "n2", "n3"]),
    auditLogs: new Set(["l1"])
  };

  const loadState = () => {
    let loaded = structuredClone(EMPTY_STATE);
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (saved && typeof saved === "object") loaded = Object.assign(loaded, saved);
    } catch {}

    if (Number(loaded.schemaVersion || 0) < DATA_VERSION) {
      loaded.works = (loaded.works || []).filter((item) => !LEGACY_SEED_IDS.works.has(item.id));
      loaded.authors = (loaded.authors || []).filter((item) => !LEGACY_SEED_IDS.authors.has(item.id));
      loaded.activities = (loaded.activities || []).filter((item) => !LEGACY_SEED_IDS.activities.has(item.id));
      loaded.conversations = (loaded.conversations || []).filter((item) => !LEGACY_SEED_IDS.conversations.has(item.id));
      loaded.notifications = (loaded.notifications || []).filter((item) => !LEGACY_SEED_IDS.notifications.has(item.id));
      loaded.auditLogs = (loaded.auditLogs || []).filter((item) => !LEGACY_SEED_IDS.auditLogs.has(item.id));
    }

    loaded.currentUser = Object.assign({ id: "me", name: "我", role: "reader" }, loaded.currentUser || {});
    loaded.followed = Array.isArray(loaded.followed) ? loaded.followed : [];
    loaded.blocked = Array.isArray(loaded.blocked) ? loaded.blocked : [];
    loaded.likedWorks = Array.isArray(loaded.likedWorks) ? loaded.likedWorks : [];
    loaded.favoritedWorks = Array.isArray(loaded.favoritedWorks) ? loaded.favoritedWorks : [];
    loaded.notifications = Array.isArray(loaded.notifications) ? loaded.notifications : [];
    loaded.works = Array.isArray(loaded.works) ? loaded.works : [];
    loaded.authors = Array.isArray(loaded.authors) ? loaded.authors : [];
    loaded.activities = Array.isArray(loaded.activities) ? loaded.activities : [];
    loaded.announcements = Array.isArray(loaded.announcements) ? loaded.announcements : [];
    loaded.reports = Array.isArray(loaded.reports) ? loaded.reports : [];
    loaded.auditLogs = Array.isArray(loaded.auditLogs) ? loaded.auditLogs : [];
    loaded.messageSettings = Object.assign({ allowStrangers: true, recallMinutes: 2, notifications: true }, loaded.messageSettings || {});
    loaded.monthlyPicks = Array.isArray(loaded.monthlyPicks) ? loaded.monthlyPicks.filter((id) => loaded.works.some((work) => work.id === id)) : [];
    loaded.conversations = Array.isArray(loaded.conversations) ? loaded.conversations : [];
    loaded.schemaVersion = DATA_VERSION;
    return loaded;
  };

  let state = loadState();
  let route = location.hash.replace(/^#\/?/, "") || "home";
  let workFilter = "全部";
  let searchTerm = "";
  let activeConversation = state.conversations[0]?.id || null;
  let replyTo = null;
  let adminTab = "概览";

  const app = document.querySelector("#app");
  const modalLayer = document.querySelector("#modal-layer");
  const modalContent = document.querySelector("#modal-content");
  const toast = document.querySelector("#toast");
  const save = () => localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const byId = (id, list) => list.find((item) => item.id === id);
  const workById = (id) => byId(id, state.works);
  const isAdmin = () => state.currentUser?.role === "admin";
  const worksByAuthor = (name) => state.works.filter((work) => work.author === name);
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

  function recordAudit(text) {
    state.auditLogs.unshift({ id: `l${Date.now()}`, text, at: "刚刚" });
    state.auditLogs = state.auditLogs.slice(0, 30);
  }

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

  function openProfile() {
    openModal("我的", `<div class="profile-summary"><span class="avatar">${escapeHtml(state.currentUser.name.slice(0, 1))}</span><div><strong>${escapeHtml(state.currentUser.name)}</strong><small>${isAdmin() ? "管理员" : "读者"}</small></div></div><div class="profile-links"><button class="button" type="button" data-open-settings>设置</button><button class="button" type="button" data-route="messages">我的私信</button><button class="button button-primary" type="button" data-publish>投稿作品</button></div>`);
  }

  function openSettings() {
    const current = document.documentElement.dataset.theme || "qingli";
    openModal("设置", `<section><h3 class="section-title">主题</h3><p class="muted">当前主题：${escapeHtml((THEMES[current] || THEMES.qingli).name)}</p><div class="theme-options">${Object.entries(THEMES).map(([id, theme]) => `<button class="theme-option ${id === current ? "is-selected" : ""}" type="button" data-theme-choice="${id}"><img src="${theme.image}" alt=""><span><strong>${escapeHtml(theme.name)}</strong><small>${escapeHtml(theme.description)}</small></span></button>`).join("")}</div></section><div class="modal-actions"><button class="button" type="button" data-close-modal>关闭</button></div>`);
  }

  function publishedAnnouncement() {
    return state.announcements.find((item) => item.status === "published") || null;
  }

  function openModal(title, html, actions = "") {
    modalContent.innerHTML = `<h2 id="modal-title">${escapeHtml(title)}</h2>${html}${actions}`;
    modalLayer.hidden = false;
    document.body.style.overflow = "hidden";
    modalContent.querySelector("[autofocus]")?.focus();
  }

  function closeModal() {
    modalLayer.hidden = true;
    modalContent.innerHTML = "";
    document.body.style.overflow = "";
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
    if (userButton) userButton.innerHTML = "<span>我</span> 我的";
    const unread = state.conversations.filter((conversation) => !conversation.hidden).reduce((sum, conversation) => sum + conversation.unread, 0);
    const unreadElement = document.querySelector("#nav-unread");
    unreadElement.textContent = unread;
    unreadElement.hidden = unread === 0;
    const unreadNotifications = state.messageSettings.notifications ? state.notifications.filter((item) => !item.read).length : 0;
    const notificationCount = document.querySelector("#notification-count");
    notificationCount.textContent = unreadNotifications;
    notificationCount.hidden = false;
    notificationCount.dataset.zero = String(unreadNotifications === 0);
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
      <div class="work-card-top"><span class="work-category">${escapeHtml(work.category || "未分类")}</span>${featured ? '<span class="work-flag">本月优秀</span>' : ""}</div>
      <button class="work-card-title work-title-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button>
      <p class="work-excerpt">${escapeHtml(work.excerpt || (work.body || []).join("").slice(0, 110))}</p>
      ${tags.length ? `<div class="tag-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
      <div class="work-meta"><button class="link-button" type="button" data-author="${authorIdByName(work.author)}">${escapeHtml(work.author || "匿名作者")}</button>${published ? `<span>${escapeHtml(published)}</span>` : ""}</div>
      <div class="work-stats"><span>${views} 阅读</span><span>${likes} 点赞</span><span>${favorites} 收藏</span><span>${comments} 评论</span></div>
      <div class="work-card-foot"><span>约 ${readingMinutes(work)} 分钟</span><button class="link-button" type="button" data-work="${work.id}">阅读全文</button></div>
    </article>`;
  }

  function renderHome() {
    const latest = [...state.works].sort((a, b) => Number(b.createdAt || b.publishedAt || 0) - Number(a.createdAt || a.publishedAt || 0));
    const monthly = state.monthlyPicks.map(workById).filter(Boolean);
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
    const works = state.works.filter((work) => (workFilter === "全部" || work.category === workFilter) && (!term || `${work.title}${work.author}${work.excerpt}`.toLowerCase().includes(term)));
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
    const author = authorById(authorIdByName(work.author));
    const tags = workTags(work);
    const published = formatDate(work.createdAt || work.publishedAt);
    const liked = state.likedWorks.includes(work.id);
    const favorited = state.favoritedWorks.includes(work.id);
    const comments = Array.isArray(work.comments) ? work.comments : [];
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="works">← 返回作品列表</button><div class="article-layout reading-layout">
      <article class="article-body reading-article">
        <header class="reading-head"><span class="work-category">${escapeHtml(work.category || "未分类")}</span><h1>${escapeHtml(work.title)}</h1><div class="reading-meta">${author ? `<button class="link-button" type="button" data-author="${author.id}">${escapeHtml(work.author || "匿名作者")}</button>` : `<span>${escapeHtml(work.author || "匿名作者")}</span>`}${published ? `<time>${escapeHtml(published)}</time>` : ""}<span>${Number(work.views) || 0} 阅读</span><span>约 ${readingMinutes(work)} 分钟</span></div>${tags.length ? `<div class="tag-row">${tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}<div class="reading-actions"><button class="button button-small ${liked ? "is-active" : ""}" type="button" data-like-work="${work.id}">${liked ? "已点赞" : "点赞"} ${Number(work.likes) || 0}</button><button class="button button-small ${favorited ? "is-active" : ""}" type="button" data-favorite-work="${work.id}">${favorited ? "已收藏" : "收藏"} ${Number(work.favorites) || 0}</button><button class="button button-small" type="button" data-share-work="${work.id}">分享</button><button class="button button-small" type="button" data-report-work="${work.id}">举报</button>${author ? `<button class="button button-small" type="button" data-message-author="${author.id}">私信作者</button>` : ""}</div></header>
        <div class="reading-content">${(work.body || []).map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}</div>
      </article>
      <aside class="article-aside"><section class="author-brief">${author ? `<span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><h2>${escapeHtml(author.name)}</h2>${author.bio ? `<p>${escapeHtml(author.bio)}</p>` : ""}<button class="link-button" type="button" data-author="${author.id}">查看作者主页</button>` : '<p class="muted">作者信息暂无。</p>'}</section><section class="comment-section"><h2 class="section-title">评论 <span class="muted">${comments.length}</span></h2><div id="comment-list">${comments.length ? comments.map(commentItem).join("") : '<p class="muted">还没有评论。</p>'}</div><form id="comment-form"><div class="field"><textarea class="textarea" name="comment" maxlength="500" required placeholder="写下具体、真诚的阅读感受"></textarea></div><button class="button button-primary" type="submit">发表评论</button></form></section></aside>
    </div></div>`;
    document.querySelector("#comment-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = new FormData(event.currentTarget).get("comment").trim();
      if (!text) return;
      work.comments = Array.isArray(work.comments) ? work.comments : [];
      work.comments.push({ id: `c${Date.now()}`, who: state.currentUser.name, text, at: Date.now() });
      save(); renderWork(id); showToast("评论已发表");
    });
  }

  function commentItem(comment) {
    const at = typeof comment.at === "number" ? formatRelativeTime(comment.at) : String(comment.at || "");
    return `<div class="comment"><div class="comment-head"><strong>${escapeHtml(comment.who)}</strong><time>${escapeHtml(at)}</time></div><p>${escapeHtml(comment.text)}</p></div>`;
  }

  function authorCard(author) {
    const works = worksByAuthor(author.name);
    const likes = works.reduce((sum, work) => sum + (Number(work.likes) || 0), 0);
    return `<article class="author-card"><div class="author-card-head"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><div><h3>${escapeHtml(author.name)}</h3>${author.awards ? `<span class="author-level">${author.awards} 次获奖</span>` : ""}</div></div>${author.bio ? `<p>${escapeHtml(author.bio)}</p>` : ""}<div class="author-stats"><span><strong>${works.length}</strong> 篇作品</span><span><strong>${likes}</strong> 次点赞</span></div>${works[0] ? `<small class="author-latest">作品《${escapeHtml(works[0].title)}》</small>` : ""}<div class="form-row"><button class="button button-small" type="button" data-author="${author.id}">查看主页</button><button class="button button-small button-primary" type="button" data-message-author="${author.id}">私信</button></div></article>`;
  }

  function renderAuthors() {
    const authors = allAuthors().filter((author) => worksByAuthor(author.name).length);
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">作者会客厅</p><h1 class="page-title">作者</h1></div><p class="page-note">作者信息来自公开作品与站内公开资料。</p></header>${authors.length ? `<div class="author-grid" style="margin-top:28px">${authors.map(authorCard).join("")}</div>` : '<div class="empty compact-empty">暂无可展示的作者。</div>'}</div>`;
  }

  function renderAuthor(id) {
    const author = authorById(id);
    if (!author) return renderMissing("这位作者暂时无法找到");
    const works = worksByAuthor(author.name);
    const monthly = works.filter((work) => state.monthlyPicks.includes(work.id));
    const likes = works.reduce((sum, work) => sum + (Number(work.likes) || 0), 0);
    const words = works.reduce((sum, work) => sum + wordCount(work), 0);
    const followed = state.followed.includes(author.id);
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="authors">← 返回作者列表</button>
      <header class="author-profile"><div class="author-profile-main"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><div><p class="eyebrow">作者主页</p><h1 class="page-title">${escapeHtml(author.name)}</h1>${author.bio ? `<p class="page-note">${escapeHtml(author.bio)}</p>` : ""}</div></div><div class="author-profile-actions"><button class="button" type="button" data-follow="${author.id}">${followed ? "已关注" : "关注作者"}</button><button class="button button-primary" type="button" data-message-author="${author.id}">私信作者</button></div></header>
      <section class="author-dashboard"><article><strong>${works.length}</strong><span>作品数量</span></article><article><strong>${monthly.length}</strong><span>月度优秀</span></article><article><strong>${likes}</strong><span>获得点赞</span></article><article><strong>${words}</strong><span>总字数</span></article></section>
      ${author.awards ? `<section class="section"><div class="section-head"><h2 class="section-title">获奖记录</h2></div><p>${escapeHtml(String(author.awards))} 次获奖。</p></section>` : ""}
      <section class="section"><div class="section-head"><div><p class="eyebrow">作品集</p><h2 class="section-title">公开作品</h2></div></div>${works.length ? `<div class="work-grid">${works.map(workCard).join("")}</div>` : '<div class="empty compact-empty">这位作者还没有公开作品。</div>'}</section>
    </div>`;
  }

  function renderMessages() {
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
    document.querySelectorAll("[data-conversation]").forEach((button) => button.addEventListener("click", () => {
      activeConversation = button.dataset.conversation;
      const target = state.conversations.find((item) => item.id === activeConversation);
      if (target) target.unread = 0;
      replyTo = null; save(); renderMessages();
    }));
    document.querySelector("#chat-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = new FormData(event.currentTarget).get("message").trim();
      if (!text) return;
      conversation.messages.push({ id: `m${Date.now()}`, mine: true, text, at: Date.now(), replyTo, recalled: false });
      replyTo = null; save(); renderMessages();
      requestAnimationFrame(() => { const body = document.querySelector("#chat-body"); if (body) body.scrollTop = body.scrollHeight; });
    });
    document.querySelector("[data-cancel-reply]")?.addEventListener("click", () => { replyTo = null; renderMessages(); });
    document.querySelectorAll("[data-reply]").forEach((button) => button.addEventListener("click", () => { replyTo = button.dataset.reply; renderMessages(); }));
    document.querySelectorAll("[data-copy-message]").forEach((button) => button.addEventListener("click", async () => {
      const message = findMessage(conversation, button.dataset.copyMessage);
      if (!message) return;
      try { await navigator.clipboard.writeText(message.text); showToast("消息已复制"); }
      catch { showToast("浏览器未允许复制"); }
    }));
    document.querySelectorAll("[data-recall]").forEach((button) => button.addEventListener("click", () => {
      const message = findMessage(conversation, button.dataset.recall);
      if (!canRecall(message)) return showToast("超过可撤回时间");
      message.recalled = true; save(); renderMessages(); showToast("消息已撤回");
    }));
    document.querySelectorAll("[data-report-message]").forEach((button) => button.addEventListener("click", () => reportDialog("举报消息", conversation, button.dataset.reportMessage)));
    document.querySelector(`[data-report-conversation="${conversation.id}"]`)?.addEventListener("click", () => reportDialog("举报用户", conversation, null));
    document.querySelector(`[data-block="${conversation.id}"]`)?.addEventListener("click", () => {
      const author = authorById(conversation.userId) || { id: conversation.userId, name: "未知用户" };
      const index = state.blocked.indexOf(author.id);
      if (index >= 0) state.blocked.splice(index, 1); else state.blocked.push(author.id);
      save(); renderMessages(); showToast(index >= 0 ? "已解除拉黑" : "已拉黑该用户");
    });
    document.querySelector(`[data-delete-conversation="${conversation.id}"]`)?.addEventListener("click", () => {
      openModal("删除会话", "<p>会话只会从你的私信列表隐藏。服务器消息、对方记录和审核记录都会保留。</p>", '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="confirm-delete-conversation">确认删除</button></div>');
      document.querySelector("#confirm-delete-conversation").addEventListener("click", () => { conversation.hidden = true; activeConversation = null; save(); closeModal(); renderMessages(); showToast("会话已删除"); });
    });
    requestAnimationFrame(() => { const body = document.querySelector("#chat-body"); if (body) body.scrollTop = body.scrollHeight; });
  }

  function openMessageSettings() {
    const settings = state.messageSettings;
    openModal("私信设置", `<form id="message-settings-form"><label class="setting-row"><span><strong>接收陌生人消息</strong><small>关闭后，未关注的作者仍可查看你的主页。</small></span><input type="checkbox" name="allowStrangers" ${settings.allowStrangers ? "checked" : ""}></label><label class="setting-row"><span><strong>消息提醒</strong><small>新消息会在顶部通知区域显示未读数量。</small></span><input type="checkbox" name="notifications" ${settings.notifications ? "checked" : ""}></label><div class="field"><label for="recall-minutes">消息可撤回时间</label><select class="select" id="recall-minutes" name="recallMinutes">${[2, 5, 10].map((minutes) => `<option value="${minutes}" ${Number(settings.recallMinutes) === minutes ? "selected" : ""}>${minutes} 分钟</option>`).join("")}</select></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="save-message-settings">保存设置</button></div>');
    document.querySelector("#save-message-settings").addEventListener("click", () => {
      const form = document.querySelector("#message-settings-form");
      const data = new FormData(form);
      state.messageSettings = { allowStrangers: Boolean(data.get("allowStrangers")), notifications: Boolean(data.get("notifications")), recallMinutes: Number(data.get("recallMinutes")) };
      save(); closeModal(); renderMessages(); showToast("私信设置已保存");
    });
  }

  function reportDialog(title, conversation, messageId) {
    const reasons = ["骚扰或辱骂", "色情或低俗内容", "暴力或威胁", "违法内容", "垃圾信息", "其他"];
    openModal(title, `<p>举报后只向管理员提交被举报消息和必要上下文，不会扫描全部私信。</p><form id="report-form"><div class="field"><label>举报原因</label><select class="select" name="reason">${reasons.map((reason) => `<option>${reason}</option>`).join("")}</select></div>${messageId ? `<div class="field"><label>补充说明</label><textarea class="textarea" name="detail" maxlength="500" placeholder="可补充具体情况"></textarea></div>` : ""}</form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="submit-report">提交举报</button></div>');
    document.querySelector("#submit-report").addEventListener("click", () => {
      const data = new FormData(document.querySelector("#report-form"));
      const message = messageId ? findMessage(conversation, messageId) : null;
      state.reports.unshift({ id: `r${Date.now()}`, target: (authorById(conversation.userId) || { name: "未知用户" }).name, reason: String(data.get("reason")), detail: String(data.get("detail") || ""), message: message?.text || "", at: "刚刚", status: "待处理" });
      state.notifications.unshift({ id: `n${Date.now()}`, text: "举报已提交，编辑部将结合必要上下文处理", at: "刚刚", read: false });
      recordAudit(`收到一条针对 ${(authorById(conversation.userId) || { name: "未知用户" }).name} 的举报`);
      save(); closeModal(); renderHeader(); showToast("举报已提交");
    });
  }

  function renderMonthly() {
    const picks = state.monthlyPicks.map(workById).filter(Boolean);
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">编辑推荐与读者选择</p><h1 class="page-title">月度优秀作品</h1><p class="page-note">仅展示已公布的月度优秀作品。</p></div></header>${picks.length ? `<div class="monthly-stage">${picks.map((work, index) => `<article class="monthly-card"><span class="monthly-rank">${String(index + 1).padStart(2, "0")}</span><div><span class="work-category">${escapeHtml(work.category || "未分类")}</span><h2>${escapeHtml(work.title)}</h2><p>${escapeHtml(work.excerpt || (work.body || []).join("").slice(0, 110))}</p><small>${escapeHtml(work.author)} · ${Number(work.likes) || 0} 点赞 · ${Number(work.views) || 0} 阅读</small><button class="button button-small button-primary" type="button" data-work="${work.id}">阅读作品</button></div></article>`).join("")}</div>` : '<div class="empty compact-empty">本月暂无优秀作品。</div>'}</div>`;
  }

  function renderRanking() {
    const ranked = [...state.works].sort((a, b) => (Number(b.likes) || 0) - (Number(a.likes) || 0) || (Number(b.views) || 0) - (Number(a.views) || 0));
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">读者选择</p><h1 class="page-title">排行榜</h1><p class="page-note">按站内真实点赞和阅读数据排序。</p></div></header>${ranked.length ? `<div class="rank-podium">${ranked.slice(0, 3).map((work, index) => `<article class="rank-podium-card rank-${index + 1}"><span>${index + 1}</span><button class="link-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><small>${escapeHtml(work.author)}</small><strong>${Number(work.likes) || 0} 点赞</strong></article>`).join("")}</div><ol class="rank-list">${ranked.slice(3).map((work, index) => `<li class="rank-item"><span class="rank-number">${String(index + 4).padStart(2, "0")}</span><button class="link-button rank-title" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><span class="muted">${escapeHtml(work.author)} · ${Number(work.likes) || 0} 点赞 · ${Number(work.views) || 0} 阅读</span></li>`).join("")}</ol>` : '<div class="empty compact-empty">暂无排行数据。</div>'}</div>`;
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
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">运营控制台</p><h1 class="page-title">管理后台</h1><p class="page-note">维护公开内容、举报记录、月度评选和文学社公告。</p></div></header><nav class="admin-tabs">${tabs.map((tab) => `<button class="${adminTab === tab ? "is-active" : ""}" type="button" data-admin-tab="${tab}">${tab}</button>`).join("")}</nav><section id="admin-content">${adminContent()}</section></div>`;
    document.querySelectorAll("[data-admin-tab]").forEach((button) => button.addEventListener("click", () => { adminTab = button.dataset.adminTab; renderAdmin(); }));
    bindAdminActions();
  }

  function bindAdminActions() {
    document.querySelector("#admin-ann-create")?.addEventListener("click", () => {
      const title = document.querySelector("#admin-ann-title").value.trim();
      const content = document.querySelector("#admin-ann-content").value.trim();
      if (!title || !content) return showToast("请填写公告标题和内容");
      state.announcements.unshift({ id: `ann${Date.now()}`, title, content, status: "published", at: "刚刚" });
      recordAudit(`发布公告《${title}》`);
      save(); renderAdmin(); showToast("公告已发布");
    });
    document.querySelectorAll("[data-ann-toggle]").forEach((button) => button.addEventListener("click", () => {
      const item = state.announcements.find((announcement) => announcement.id === button.dataset.annToggle);
      if (!item) return;
      item.status = item.status === "published" ? "archived" : "published";
      recordAudit(`${item.status === "published" ? "发布" : "撤回"}公告《${item.title}》`);
      save(); renderAdmin(); showToast(item.status === "published" ? "公告已发布" : "公告已撤回");
    }));
  }

  function adminContent() {
    const comments = state.works.flatMap((work) => work.comments.map((comment) => ({ ...comment, workTitle: work.title })));
    if (adminTab === "概览") return `<div class="admin-grid"><div class="metric"><strong>${state.works.length}</strong><span>公开作品</span></div><div class="metric"><strong>${comments.length}</strong><span>读者评论</span></div><div class="metric"><strong>${state.reports.length}</strong><span>私信举报</span></div><div class="metric"><strong>${state.activities.length}</strong><span>文学活动</span></div></div><ul class="admin-list"><li class="admin-row"><span><strong>内容审核队列</strong><small class="admin-note">公开作品与评论进入常规审核，私信只在举报后检查必要上下文。</small></span><span class="muted">${state.works.length + comments.length} 项</span></li><li class="admin-row"><span><strong>Agent 状态</strong><small class="admin-note">PASSIVE · 等待人工授权</small></span><span class="muted">只辅助，不决策</span></li><li class="admin-row"><span><strong>最近一次操作</strong><small class="admin-note">${escapeHtml(state.auditLogs[0]?.text || "暂无操作记录")}</small></span><span class="muted">${escapeHtml(state.auditLogs[0]?.at || "")}</span></li></ul>`;
    if (adminTab === "作品审核") return `<div class="panel admin-panel"><h2 class="section-title">公开作品</h2><p class="muted">作品发布后进入公开阅读区，举报或争议内容可转入人工复核。</p><ul class="admin-list">${state.works.map((work) => `<li class="admin-row"><span><strong>${escapeHtml(work.title)}</strong><small class="admin-note">${escapeHtml(work.author)} · ${escapeHtml(work.category)} · ${work.views} 阅读</small></span><span class="status-pill">已公开</span></li>`).join("")}</ul></div>`;
    if (adminTab === "评论管理") return `<div class="panel admin-panel"><h2 class="section-title">读者评论</h2><ul class="admin-list">${comments.length ? comments.map((comment) => `<li class="admin-row"><span><strong>${escapeHtml(comment.who)}</strong><small class="admin-note">${escapeHtml(comment.text)} · 评论《${escapeHtml(comment.workTitle)}》</small></span><span class="muted">${escapeHtml(comment.at)}</span></li>`).join("") : '<li class="empty">当前没有读者评论。</li>'}</ul></div>`;
    if (adminTab === "私信举报") return `<div class="panel admin-panel"><h2 class="section-title">私信举报</h2><p class="muted">只处理被举报消息和必要上下文，不扫描普通私信。</p><ul class="admin-list">${state.reports.length ? state.reports.map((report) => `<li class="admin-row"><span><strong>${escapeHtml(report.target)} · ${escapeHtml(report.reason)}</strong><small class="admin-note">${escapeHtml(report.detail || report.message || "未补充说明")}</small></span><span class="status-pill">${escapeHtml(report.status)}</span></li>`).join("") : '<li class="empty">当前没有待处理举报。</li>'}</ul></div>`;
    if (adminTab === "用户管理") return `<div class="panel admin-panel"><h2 class="section-title">用户与作者</h2><ul class="admin-list"><li class="admin-row"><span><strong>${escapeHtml(state.currentUser.name)}</strong><small class="admin-note">当前登录用户</small></span><span class="status-pill">${isAdmin() ? "管理员" : "读者"}</span></li>${allAuthors().map((author) => `<li class="admin-row"><span><strong>${escapeHtml(author.name)}</strong><small class="admin-note">${escapeHtml(author.bio)}</small></span><span class="muted">${worksByAuthor(author.name).length} 篇作品</span></li>`).join("")}</ul></div>`;
    if (adminTab === "月度评选") return `<div class="panel admin-panel"><h2 class="section-title">九月提名</h2><p class="muted">提名作品同步显示在首页与月度优秀作品页。</p><ul class="admin-list">${state.monthlyPicks.map((id, index) => { const work = workById(id); return work ? `<li class="admin-row"><span><strong>${String(index + 1).padStart(2, "0")} · ${escapeHtml(work.title)}</strong><small class="admin-note">${escapeHtml(work.excerpt || "")}</small></span><span class="muted">${escapeHtml(work.author)}</span></li>` : ""; }).join("") || '<li class="empty">暂无提名。</li>'}</ul></div>`;
    if (adminTab === "文学活动") return `<div class="panel admin-panel"><h2 class="section-title">活动清单</h2><ul class="admin-list">${state.activities.map((activity) => `<li class="admin-row"><span><strong>${escapeHtml(activity.title)}</strong><small class="admin-note">${escapeHtml(activity.desc)}</small></span><span class="status-pill">${escapeHtml(activity.status)}</span></li>`).join("")}</ul></div>`;
    if (adminTab === "公告") return `<div class="admin-announcement"><div class="field"><label>公告标题</label><input class="input" id="admin-ann-title" maxlength="80" placeholder="例如：十月共读会开始报名"></div><div class="field"><label>公告内容</label><textarea class="textarea" id="admin-ann-content" maxlength="1000" placeholder="填写需要告知全体用户的简短内容"></textarea></div><button class="button button-primary" type="button" id="admin-ann-create">发布公告</button></div><ul class="admin-list">${state.announcements.length ? state.announcements.map((item) => `<li class="admin-row"><span><strong>${escapeHtml(item.title)}</strong><small class="admin-note">${escapeHtml(item.status === "published" ? "已发布" : "已归档")} · ${escapeHtml(item.content)}</small></span><button class="button button-small ${item.status === "published" ? "button-quiet" : "button-primary"}" type="button" data-ann-toggle="${item.id}">${item.status === "published" ? "撤回" : "发布"}</button></li>`).join("") : '<li class="empty">暂无公告。</li>'}</ul>`;
    if (adminTab === "Agent 审核") return `<div class="panel admin-panel"><div class="section-head"><h2 class="section-title">Agent 审核</h2><span class="status-pill">PASSIVE</span></div><div class="admin-grid"><div class="metric"><strong>${state.works.length + comments.length}</strong><span>公开内容队列</span></div><div class="metric"><strong>${state.reports.length}</strong><span>举报上下文</span></div><div class="metric"><strong>0</strong><span>自动处置</span></div></div><ul class="admin-list"><li class="admin-row"><span>风险分级<small class="admin-note">LOW · MEDIUM · HIGH · CRITICAL</small></span><span class="muted">等待审核</span></li><li class="admin-row"><span>最终动作<small class="admin-note">模型只输出结构化分析，管理员确认 ALLOW、REVIEW 或 BLOCK。</small></span><span class="muted">人工确认</span></li><li class="admin-row"><span>隐私边界<small class="admin-note">普通私信不扫描，只有举报消息和必要上下文进入审核。</small></span><span class="muted">已启用</span></li></ul></div>`;
    if (adminTab === "安全日志") return `<div class="panel admin-panel"><h2 class="section-title">操作与审核日志</h2><ul class="admin-list">${state.auditLogs.length ? state.auditLogs.map((item) => `<li class="admin-row"><span>${escapeHtml(item.text)}</span><time class="muted">${escapeHtml(item.at)}</time></li>`).join("") : '<li class="empty">暂无操作记录。</li>'}</ul></div>`;
    return `<div class="panel admin-panel"><h2 class="section-title">${escapeHtml(adminTab)}</h2><p class="muted">当前分类没有待处理记录。</p></div>`;
  }

  function renderNotifications() {
    openModal("通知", state.notifications.length ? `<ul class="admin-list">${state.notifications.map((item) => `<li class="admin-row"><span>${escapeHtml(item.text)}</span><time class="muted">${escapeHtml(item.at)}</time></li>`).join("")}</ul>` : "<p>暂无通知。</p>");
    state.notifications.forEach((item) => { item.read = true; }); save(); renderHeader();
  }

  function openPublish() {
    openModal("投稿作品", `<form id="publish-form"><div class="field"><label>作品标题</label><input class="input" name="title" maxlength="80" required></div><div class="field"><label>体裁</label><select class="select" name="category">${categories.slice(1).map((category) => `<option>${category}</option>`).join("")}</select></div><div class="field"><label>标签</label><input class="input" name="tags" maxlength="120" placeholder="多个标签用逗号分隔，可选"></div><div class="field"><label>作者</label><input class="input" name="author" maxlength="40" value="${escapeHtml(state.currentUser.name)}" required></div><div class="field"><label>正文</label><textarea class="textarea" name="body" maxlength="10000" required placeholder="在这里写下作品正文"></textarea></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="submit-publish">提交审核</button></div>');
    document.querySelector("#submit-publish").addEventListener("click", () => {
      const form = document.querySelector("#publish-form");
      if (!form.reportValidity()) return;
      const data = new FormData(form);
      const body = String(data.get("body")).split(/\n+/).map((line) => line.trim()).filter(Boolean);
      const title = String(data.get("title")).trim();
      const tags = String(data.get("tags") || "").split(/[,，]/).map((tag) => tag.trim()).filter(Boolean);
      state.works.unshift({ id: `w${Date.now()}`, title, author: String(data.get("author")).trim(), category: String(data.get("category")), tags, likes: 0, views: 0, favorites: 0, excerpt: body[0].slice(0, 90), body, comments: [], createdAt: Date.now(), createdBy: state.currentUser.id });
      state.notifications.unshift({ id: `n${Date.now()}`, text: "作品已提交审核，等待管理员处理", at: "刚刚", read: false });
      recordAudit(`投稿作品《${title}》进入审核队列`);
      save(); closeModal(); renderHeader(); setRoute("works"); showToast("作品已提交，等待审核");
    });
  }

  function toggleWorkLike(workId) {
    const work = workById(workId);
    if (!work) return;
    const liked = state.likedWorks.includes(workId);
    state.likedWorks = liked ? state.likedWorks.filter((id) => id !== workId) : [...state.likedWorks, workId];
    work.likes = Math.max(0, (Number(work.likes) || 0) + (liked ? -1 : 1));
    save(); renderWork(workId);
  }

  function toggleWorkFavorite(workId) {
    const work = workById(workId);
    if (!work) return;
    const favorited = state.favoritedWorks.includes(workId);
    state.favoritedWorks = favorited ? state.favoritedWorks.filter((id) => id !== workId) : [...state.favoritedWorks, workId];
    work.favorites = Math.max(0, (Number(work.favorites) || 0) + (favorited ? -1 : 1));
    save(); renderWork(workId);
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
    const work = workById(workId);
    if (!work) return;
    const reasons = ["内容侵权", "色情或低俗内容", "暴力或威胁", "违法内容", "垃圾信息", "其他"];
    openModal("举报作品", `<p>举报只提交作品和必要说明。</p><form id="report-work-form"><div class="field"><label>举报原因</label><select class="select" name="reason">${reasons.map((reason) => `<option>${reason}</option>`).join("")}</select></div><div class="field"><label>补充说明</label><textarea class="textarea" name="detail" maxlength="500" placeholder="可补充具体情况"></textarea></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="submit-work-report">提交举报</button></div>');
    document.querySelector("#submit-work-report").addEventListener("click", () => {
      const data = new FormData(document.querySelector("#report-work-form"));
      state.reports.unshift({ id: `r${Date.now()}`, type: "作品", target: work.title, reason: String(data.get("reason")), detail: String(data.get("detail") || ""), at: "刚刚", status: "待处理" });
      recordAudit(`收到针对作品《${work.title}》的举报`);
      save(); closeModal(); showToast("举报已提交");
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
    if (route === "admin") return renderAdmin();
    return renderHome();
  }

  function startConversation(authorId) {
    let conversation = state.conversations.find((item) => item.userId === authorId);
    if (!conversation) {
      conversation = { id: `cv${Date.now()}`, userId: authorId, hidden: false, unread: 0, messages: [] };
      state.conversations.unshift(conversation);
    }
    conversation.hidden = false;
    activeConversation = conversation.id;
    save(); setRoute("messages");
  }

  document.addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    if (target.matches("[data-message-settings]")) return openMessageSettings();
    if (target.matches("[data-open-settings]")) return openSettings();
    if (target.matches("[data-close-modal], #modal-close")) return closeModal();
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
      const index = state.followed.indexOf(authorId);
      if (index >= 0) state.followed.splice(index, 1); else state.followed.push(authorId);
      save(); return renderAuthor(authorId);
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
  render();
})();
