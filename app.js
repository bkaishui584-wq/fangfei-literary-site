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
  const seed = {
    currentUser: { id: "me", name: "我" },
    followed: [],
    blocked: [],
    notifications: [
      { id: "n1", text: "林间月回复了你的评论", at: "10分钟前", read: false },
      { id: "n2", text: "你的作品进入本月优秀作品候选", at: "昨天", read: false },
      { id: "n3", text: "芳菲秋日共读会开始报名", at: "9月25日", read: true }
    ],
    works: [
      { id: "w1", title: "潮汐来过的房间", author: "星河", category: "小说", likes: 328, views: 1820, excerpt: "雨停以后，我在旧书桌的抽屉里找到一枚贝壳。它替我说出了那个夏天没有说出口的话。", body: ["雨是在傍晚停的。窗台留下一条淡淡的水线，像有人刚刚从这里离开。", "我翻开那本借来的旧书，页边有陌生人的铅笔字：如果海也会遗忘，那么潮汐为什么还要回来？", "很多年后我才明白，有些房间一直没有空着。我们离开以后，仍有一部分生活在那里，反复开门、点灯，等待一个不会准时的答案。"], comments: [{ id: "c1", who: "林间月", text: "结尾很轻，却停留了很久。", at: "今天 14:20" }] },
      { id: "w2", title: "北纬三十度的雪", author: "白纸", category: "诗歌", likes: 271, views: 1430, excerpt: "雪落在没有名字的车站 / 我把它读成一封迟到的信", body: ["雪落在没有名字的车站", "我把它读成一封迟到的信", "那些被风吹散的字", "沿着铁轨重新聚拢", "而故乡，只在信封背面", "写下短短一行。"], comments: [] },
      { id: "w3", title: "纸鸢误入云层", author: "春山", category: "散文", likes: 246, views: 1188, excerpt: "小时候以为风筝线断了，就是自由。长大后才懂得，有些牵挂正是飞行的一部分。", body: ["春风把广场吹得很高，纸鸢一只接一只飞过屋顶。", "我忽然想起小时候那只断线的燕子。它没有坠落，只是变成了一点越来越小的黑色，最后融进云里。", "原来自由并不等于没有方向。真正的远行，是知道有一根看不见的线，始终系在愿意等你的人手中。"], comments: [] },
      { id: "w4", title: "第七号观测员", author: "墨桥", category: "科幻", likes: 219, views: 1064, excerpt: "在人类离开地球的第两百年，第七号观测员收到了一份来自旧时代的晚餐邀请。", body: ["第七号观测员的工作，是每天向空无一人的地球发送一次问候。", "第三千六百五十次发送后，他收到一封回信。信里只有一张桌子的坐标，和一句：晚饭七点，不要迟到。", "他穿过长满蕨类的城市，在高架桥下找到那张桌子。桌面放着两副碗筷，汤仍然温热。"], comments: [] },
      { id: "w5", title: "雨天不寄信", author: "青禾", category: "随笔", likes: 189, views: 936, excerpt: "有些话适合在晴天写完，因为雨天总会让人误会那是挽留。", body: ["雨天的邮局很安静，窗玻璃上浮着密密的水珠。", "我把写好的信放回包里，买了一张没有目的地的车票。", "后来信没有寄出。我也没有后悔。人总要学会把一部分告别，交给天气。"], comments: [] },
      { id: "w6", title: "幕间十分钟", author: "南枝", category: "剧本", likes: 164, views: 772, excerpt: "演员退场，灯光暗下。真正的故事，在幕间十分钟里悄悄发生。", body: ["舞台监督：还有九分钟。", "女演员：刚才那句台词，我不是说给观众听的。", "男演员：我知道。", "女演员：那你为什么没有回答？", "灯光师在控制台后按下按钮。下一幕开始前，整个剧场只剩一盏顶灯。"], comments: [] }
    ],
    authors: [
      { id: "a1", name: "星河", bio: "写海边、旧房间和未完成的重逢。", works: 12, awards: 3 },
      { id: "a2", name: "林间月", bio: "诗歌与短篇小说作者，相信细节会替情绪说话。", works: 9, awards: 2 },
      { id: "a3", name: "白纸", bio: "在通勤和深夜之间写诗。", works: 18, awards: 1 },
      { id: "a4", name: "春山", bio: "散文写作者，关心人与地方的关系。", works: 7, awards: 2 },
      { id: "a5", name: "墨桥", bio: "科幻作者，偶尔把宇宙写得像一顿晚饭。", works: 11, awards: 4 },
      { id: "a6", name: "青禾", bio: "写日常、天气，以及那些没能寄出的信。", works: 6, awards: 0 }
    ],
    activities: [
      { id: "e1", date: "10.12", title: "芳菲秋日共读会", desc: "共读短篇小说集《夜晚的潜水艇》，招募 20 位领读人。", status: "报名中" },
      { id: "e2", date: "10.26", title: "一小时写作实验室", desc: "围绕“失去”完成一次不修改的自由写作。", status: "即将开始" },
      { id: "e3", date: "11.03", title: "城市漫游与散文现场", desc: "带上纸笔，在旧街完成一段可被阅读的散步。", status: "策划中" },
      { id: "e4", date: "11.18", title: "冬季作品改稿会", desc: "每位作者提交一篇作品，交换一次认真阅读。", status: "报名中" }
    ],
    announcements: [],
    monthlyPicks: ["w1", "w2", "w3"],
    conversations: [
      { id: "cv1", userId: "a1", hidden: false, unread: 2, messages: [
        { id: "m1", mine: false, text: "你好！你的《潮汐来过的房间》写得很好。", at: Date.now() - 3600000, replyTo: null, recalled: false },
        { id: "m2", mine: true, text: "谢谢你认真读完。你也喜欢这种类型的作品吗？", at: Date.now() - 3500000, replyTo: "m1", recalled: false },
        { id: "m3", mine: false, text: "喜欢。尤其喜欢结尾那种没有说透的感觉。", at: Date.now() - 300000, replyTo: null, recalled: false },
        { id: "m4", mine: false, text: "下次改稿会，可以请你来聊聊吗？", at: Date.now() - 240000, replyTo: null, recalled: false }
      ] },
      { id: "cv2", userId: "a2", hidden: false, unread: 1, messages: [
        { id: "m5", mine: false, text: "谢谢你的建议，我把第二节重写了。", at: Date.now() - 26 * 3600000, replyTo: null, recalled: false }
      ] },
      { id: "cv3", userId: "a3", hidden: false, unread: 0, messages: [
        { id: "m6", mine: false, text: "下周的诗歌共读，你来吗？", at: Date.now() - 58 * 3600000, replyTo: null, recalled: false }
      ] }
    ]
  };

  const loadState = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      return saved && saved.works ? saved : structuredClone(seed);
    } catch {
      return structuredClone(seed);
    }
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
  const authorById = (id) => byId(id, state.authors) || { name: id, bio: "", works: 0, awards: 0 };
  const workById = (id) => byId(id, state.works);

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

  function openThemeChooser() {
    const current = document.documentElement.dataset.theme || "qingli";
    openModal("选择主题", `<p>六套主题沿用原站视觉资源，切换后背景与音乐列表会同步变化。</p><div class="theme-options">${Object.entries(THEMES).map(([id, theme]) => `<button class="theme-option ${id === current ? "is-selected" : ""}" type="button" data-theme-choice="${id}"><img src="${theme.image}" alt=""><span><strong>${escapeHtml(theme.name)}</strong><small>${escapeHtml(theme.description)}</small></span></button>`).join("")}</div>`);
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
    const unread = state.conversations.filter((conversation) => !conversation.hidden).reduce((sum, conversation) => sum + conversation.unread, 0);
    const unreadElement = document.querySelector("#nav-unread");
    unreadElement.textContent = unread;
    unreadElement.hidden = unread === 0;
    const unreadNotifications = state.notifications.filter((item) => !item.read).length;
    const notificationCount = document.querySelector("#notification-count");
    notificationCount.textContent = unreadNotifications;
    notificationCount.hidden = unreadNotifications === 0;
  }

  function workCard(work) {
    return `<article class="work-card">
      <span class="work-category">${escapeHtml(work.category)}</span>
      <h3 class="work-card-title">${escapeHtml(work.title)}</h3>
      <p class="work-excerpt">${escapeHtml(work.excerpt)}</p>
      <div class="work-meta"><button class="link-button" type="button" data-work="${work.id}">${escapeHtml(work.author)}</button><span>${work.likes} 喜欢 · ${work.views} 阅读</span></div>
    </article>`;
  }

  function renderHome() {
    const picks = state.works.slice(0, 3);
    const announcement = publishedAnnouncement();
    app.innerHTML = `<div class="page">
      ${announcement ? `<div class="announcement-strip"><strong>公告</strong><span>${escapeHtml(announcement.title)}：${escapeHtml(announcement.content)}</span></div>` : ""}
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">芳菲文学社 · 秋日卷</p>
          <h1>让文字被读完，<span>让作者彼此看见。</span></h1>
          <p class="hero-lead">这里收集小说、诗歌、散文与远方的来信。你可以发表作品，也可以从一段认真阅读开始，找到同路的人。</p>
          <div class="hero-actions"><button class="button button-primary" type="button" data-route="works">开始阅读</button><button class="button" type="button" data-publish>投稿作品</button></div>
        </div>
        <aside class="hero-poem"><blockquote>“雪落在没有名字的车站<br>我把它读成一封迟到的信”</blockquote><cite>白纸《北纬三十度的雪》</cite></aside>
      </section>
      <section class="section"><div class="section-head"><h2 class="section-title">本期推荐</h2><button class="section-link" type="button" data-route="works">查看全部作品</button></div><div class="work-grid">${picks.map(workCard).join("")}</div></section>
      <section class="section"><div class="section-head"><h2 class="section-title">本月优秀作品</h2><button class="section-link" type="button" data-route="monthly">查看评选</button></div><div class="monthly-ribbon">${state.monthlyPicks.map((id, index) => { const work = workById(id); return work ? `<article><span>${String(index + 1).padStart(2, "0")}</span><button class="link-button" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><small>${escapeHtml(work.author)}</small></article>` : ""; }).join("")}</div></section>
      <section class="section"><div class="section-head"><h2 class="section-title">最近活跃的作者</h2><button class="section-link" type="button" data-route="authors">发现更多作者</button></div><div class="author-grid">${state.authors.slice(0, 3).map(authorCard).join("")}</div></section>
      <section class="section"><div class="section-head"><h2 class="section-title">正在发生</h2></div><div class="activity-grid">${state.activities.slice(0, 2).map(activityCard).join("")}</div></section>
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
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="works">← 返回作品列表</button><div class="article-layout">
      <article class="article-body"><span class="work-category">${escapeHtml(work.category)}</span><h1>${escapeHtml(work.title)}</h1><p class="muted">作者：<button class="link-button" type="button" data-author="${authorIdByName(work.author)}">${escapeHtml(work.author)}</button> · ${work.views} 阅读</p>${work.body.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("")}</article>
      <aside class="article-aside"><h2 class="section-title">评论区</h2><div id="comment-list">${work.comments.length ? work.comments.map(commentItem).join("") : '<p class="muted">还没有评论。写下第一句回应吧。</p>'}</div><form id="comment-form"><div class="field"><textarea class="textarea" name="comment" maxlength="500" required placeholder="留下真诚、具体的阅读感受"></textarea></div><button class="button button-primary" type="submit">发表评论</button></form></aside>
    </div></div>`;
    document.querySelector("#comment-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = new FormData(event.currentTarget).get("comment").trim();
      if (!text) return;
      work.comments.push({ id: `c${Date.now()}`, who: state.currentUser.name, text, at: "刚刚" });
      save(); renderWork(id); showToast("评论已发表");
    });
  }

  function commentItem(comment) {
    return `<div class="comment"><div class="comment-head"><strong>${escapeHtml(comment.who)}</strong><time>${escapeHtml(comment.at)}</time></div><p>${escapeHtml(comment.text)}</p></div>`;
  }

  function authorCard(author) {
    return `<article class="author-card"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><h3>${escapeHtml(author.name)}</h3><p>${escapeHtml(author.bio)}</p><div class="author-meta"><span>${author.works} 篇作品</span><span>${author.awards} 次获奖</span></div><div class="form-row"><button class="button button-small" type="button" data-author="${author.id}">查看主页</button><button class="button button-small button-primary" type="button" data-message-author="${author.id}">私信</button></div></article>`;
  }

  function renderAuthors() {
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">作者会客厅</p><h1 class="page-title">作者</h1></div><p class="page-note">从作者主页进入作品，也可以发起一封只属于你们两个人的私信。</p></header><div class="author-grid" style="margin-top:28px">${state.authors.map(authorCard).join("")}</div></div>`;
  }

  function renderAuthor(id) {
    const author = state.authors.find((item) => item.id === id);
    if (!author) return renderMissing("这位作者暂时无法找到");
    const works = state.works.filter((work) => work.author === author.name);
    const followed = state.followed.includes(author.id);
    app.innerHTML = `<div class="page"><button class="link-button" type="button" data-route="authors">← 返回作者列表</button><header class="page-head" style="margin-top:28px"><div><span class="avatar" style="width:72px;height:72px;border-radius:50%;font-size:28px">${escapeHtml(author.name.slice(0,1))}</span><h1 class="page-title" style="font-size:44px;margin-top:14px">${escapeHtml(author.name)}</h1><p class="page-note">${escapeHtml(author.bio)}</p></div><div class="form-row"><button class="button" type="button" data-follow="${author.id}">${followed ? "已关注" : "关注"}</button><button class="button button-primary" type="button" data-message-author="${author.id}">私信作者</button></div></header><section class="section"><div class="section-head"><h2 class="section-title">作品 ${author.works}</h2><span class="muted">获奖 ${author.awards}</span></div>${works.length ? `<div class="work-grid">${works.map(workCard).join("")}</div>` : '<div class="empty">这位作者还没有在演示数据中发布作品。</div>'}</section></div>`;
  }

  function renderMessages() {
    const visible = state.conversations.filter((conversation) => !conversation.hidden);
    const current = visible.find((conversation) => conversation.id === activeConversation) || visible[0];
    if (current) activeConversation = current.id;
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">只对彼此可见</p><h1 class="page-title">私信</h1></div><p class="page-note">支持回复、撤回、拉黑、举报和未读状态。删除会话只会从你的列表隐藏，不会删除服务器消息。</p></header>
      <div class="messages-layout" style="margin-top:28px">
        <aside class="conversation-list"><div class="conversation-list-head"><label class="search-box"><input id="conversation-search" type="search" placeholder="搜索会话"></label></div><div id="conversation-items">${visible.map(conversationItem).join("") || '<div class="empty">暂无会话</div>'}</div></aside>
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
    const author = authorById(conversation.userId);
    const last = conversation.messages.filter((message) => !message.recalled).at(-1);
    return `<button class="conversation-item ${conversation.id === activeConversation ? "is-active" : ""}" type="button" data-conversation="${conversation.id}" data-name="${escapeHtml(author.name)}"><span class="avatar">${escapeHtml(author.name.slice(0, 1))}</span><span><strong>${escapeHtml(author.name)}</strong><small>${last ? escapeHtml(last.text) : "暂无消息"}</small></span><time>${conversation.unread ? `${conversation.unread} 未读` : "已读"}</time></button>`;
  }

  function chatPanel(conversation) {
    const author = authorById(conversation.userId);
    return `<header class="chat-head"><strong>${escapeHtml(author.name)}</strong><div class="form-row" style="margin:0"><button class="button button-small" type="button" data-block="${conversation.id}">${state.blocked.includes(author.id) ? "解除拉黑" : "拉黑"}</button><button class="button button-small" type="button" data-report-conversation="${conversation.id}">举报</button><button class="button button-small" type="button" data-delete-conversation="${conversation.id}">删除会话</button></div></header>
      <div class="chat-body" id="chat-body">${conversation.messages.map((message) => messageItem(conversation, message)).join("") || '<div class="empty">还没有消息，先说一句你好。</div>'}</div>
      <form class="chat-form" id="chat-form">${replyTo ? `<div class="reply-preview"><span>回复：${escapeHtml(findMessage(conversation, replyTo)?.text || "")}</span><button type="button" data-cancel-reply>取消</button></div>` : ""}<div class="form-row" style="margin:0"><input class="input" name="message" maxlength="1000" autocomplete="off" placeholder="${state.blocked.includes(author.id) ? "已拉黑该用户" : "输入消息……"}" ${state.blocked.includes(author.id) ? "disabled" : ""}><button class="button button-primary" type="submit" ${state.blocked.includes(author.id) ? "disabled" : ""}>发送</button></div></form>`;
  }

  function findMessage(conversation, id) {
    return conversation.messages.find((message) => message.id === id);
  }

  function canRecall(message) {
    return message.mine && !message.recalled && Date.now() - message.at <= 2 * 60 * 1000;
  }

  function messageItem(conversation, message) {
    const replied = message.replyTo ? findMessage(conversation, message.replyTo) : null;
    const content = message.recalled ? "这条消息已撤回" : escapeHtml(message.text);
    return `<div class="message ${message.mine ? "is-me" : ""}"><div class="message-bubble">${replied ? `<blockquote>${escapeHtml(replied.text)}</blockquote>` : ""}${content}</div><div class="message-meta"><span>${new Date(message.at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>${!message.recalled ? `<button type="button" data-reply="${message.id}">回复</button>` : ""}${!message.recalled ? `<button type="button" data-report-message="${message.id}">举报</button>` : ""}${canRecall(message) ? `<button type="button" data-recall="${message.id}">撤回</button>` : ""}</div></div>`;
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
    document.querySelectorAll("[data-recall]").forEach((button) => button.addEventListener("click", () => {
      const message = findMessage(conversation, button.dataset.recall);
      if (!canRecall(message)) return showToast("超过可撤回时间");
      message.recalled = true; save(); renderMessages(); showToast("消息已撤回");
    }));
    document.querySelectorAll("[data-report-message]").forEach((button) => button.addEventListener("click", () => reportDialog("举报消息", conversation, button.dataset.reportMessage)));
    document.querySelector(`[data-report-conversation="${conversation.id}"]`)?.addEventListener("click", () => reportDialog("举报用户", conversation, null));
    document.querySelector(`[data-block="${conversation.id}"]`)?.addEventListener("click", () => {
      const author = authorById(conversation.userId);
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

  function reportDialog(title, conversation, messageId) {
    const reasons = ["骚扰或辱骂", "色情或低俗内容", "暴力或威胁", "违法内容", "垃圾信息", "其他"];
    openModal(title, `<p>举报后只向管理员提交被举报消息和必要上下文，不会扫描全部私信。</p><form id="report-form"><div class="field"><label>举报原因</label><select class="select" name="reason">${reasons.map((reason) => `<option>${reason}</option>`).join("")}</select></div>${messageId ? `<div class="field"><label>补充说明</label><textarea class="textarea" name="detail" maxlength="500" placeholder="可补充具体情况"></textarea></div>` : ""}</form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-danger" type="button" id="submit-report">提交举报</button></div>');
    document.querySelector("#submit-report").addEventListener("click", () => {
      state.notifications.unshift({ id: `n${Date.now()}`, text: `举报已提交，管理员将结合必要上下文处理`, at: "刚刚", read: false });
      save(); closeModal(); renderHeader(); showToast("举报已提交");
    });
  }

  function renderMonthly() {
    const picks = state.monthlyPicks.map(workById).filter(Boolean);
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">编辑推荐与读者选择</p><h1 class="page-title">月度优秀作品</h1></div><p class="page-note">每月由编辑提名，并结合阅读、评论与读者投票产生。</p></header>
      <div class="monthly-stage">${picks.map((work, index) => `<article class="monthly-card"><span class="monthly-rank">${String(index + 1).padStart(2, "0")}</span><div><span class="work-category">${escapeHtml(work.category)}</span><h2>${escapeHtml(work.title)}</h2><p>${escapeHtml(work.excerpt)}</p><small>${escapeHtml(work.author)} · ${work.likes} 次喜欢</small><button class="link-button" type="button" data-work="${work.id}">阅读作品</button></div></article>`).join("")}</div>
    </div>`;
  }

  function renderRanking() {
    const ranked = [...state.works].sort((a, b) => b.likes - a.likes);
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">读者选择</p><h1 class="page-title">排行榜</h1></div><p class="page-note">按喜欢与阅读趋势排序，每周一更新。</p></header><ol class="rank-list" style="margin-top:28px">${ranked.map((work, index) => `<li class="rank-item"><span class="rank-number">${String(index + 1).padStart(2, "0")}</span><button class="link-button rank-title" type="button" data-work="${work.id}">${escapeHtml(work.title)}</button><span class="muted">${escapeHtml(work.author)} · ${work.likes} 喜欢</span></li>`).join("")}</ol></div>`;
  }

  function activityCard(activity) {
    return `<article class="activity-card"><div class="activity-date">${escapeHtml(activity.date)}<br><small>${escapeHtml(activity.status)}</small></div><div><h3>${escapeHtml(activity.title)}</h3><p class="muted">${escapeHtml(activity.desc)}</p><button class="button button-small" type="button" data-activity="${activity.id}">查看活动</button></div></article>`;
  }

  function renderActivities() {
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">把写作带到现场</p><h1 class="page-title">文学活动</h1></div><p class="page-note">共读、写作实验室、城市漫游和改稿会。</p></header><div class="activity-grid" style="margin-top:28px">${state.activities.map(activityCard).join("")}</div></div>`;
  }

  function renderAdmin() {
    const tabs = ["概览", "作品审核", "评论管理", "私信举报", "用户管理", "月度评选", "文学活动", "公告", "Agent 审核", "安全日志"];
    app.innerHTML = `<div class="page"><header class="page-head"><div><p class="eyebrow">运营控制台</p><h1 class="page-title">管理后台</h1></div><p class="page-note">正式版必须由服务端校验管理员权限。当前预览版使用模拟审核数据。</p></header><nav class="admin-tabs">${tabs.map((tab) => `<button class="${adminTab === tab ? "is-active" : ""}" type="button" data-admin-tab="${tab}">${tab}</button>`).join("")}</nav><section id="admin-content">${adminContent()}</section></div>`;
    document.querySelectorAll("[data-admin-tab]").forEach((button) => button.addEventListener("click", () => { adminTab = button.dataset.adminTab; renderAdmin(); }));
    bindAdminActions();
  }

  function bindAdminActions() {
    document.querySelector("#admin-ann-create")?.addEventListener("click", () => {
      const title = document.querySelector("#admin-ann-title").value.trim();
      const content = document.querySelector("#admin-ann-content").value.trim();
      if (!title || !content) return showToast("请填写公告标题和内容");
      state.announcements.unshift({ id: `ann${Date.now()}`, title, content, status: "published", at: "刚刚" });
      save(); renderAdmin(); showToast("公告已发布");
    });
    document.querySelectorAll("[data-ann-toggle]").forEach((button) => button.addEventListener("click", () => {
      const item = state.announcements.find((announcement) => announcement.id === button.dataset.annToggle);
      if (!item) return;
      item.status = item.status === "published" ? "archived" : "published";
      save(); renderAdmin(); showToast(item.status === "published" ? "公告已发布" : "公告已撤回");
    }));
  }

  function adminContent() {
    if (adminTab === "概览") return `<div class="admin-grid"><div class="metric"><strong>${state.works.length}</strong><span>作品总数</span></div><div class="metric"><strong>2</strong><span>待人工审核</span></div><div class="metric"><strong>1</strong><span>私信举报</span></div></div><ul class="admin-list"><li class="admin-row"><span>《潮汐来过的房间》</span><span class="muted">Agent 建议：允许 · LOW</span></li><li class="admin-row"><span>一条争议评论</span><span class="muted">待人工确认 · MEDIUM</span></li></ul>`;
    if (adminTab === "公告") return `<div class="admin-announcement"><div class="field"><label>公告标题</label><input class="input" id="admin-ann-title" maxlength="80" placeholder="例如：十月共读会开始报名"></div><div class="field"><label>公告内容</label><textarea class="textarea" id="admin-ann-content" maxlength="1000" placeholder="填写需要告知全体用户的简短内容"></textarea></div><button class="button button-primary" type="button" id="admin-ann-create">发布公告</button></div><ul class="admin-list">${state.announcements.length ? state.announcements.map((item) => `<li class="admin-row"><span><strong>${escapeHtml(item.title)}</strong><em class="admin-note">${escapeHtml(item.status === "published" ? "已发布" : "已归档")} · ${escapeHtml(item.content)}</em></span><button class="button button-small ${item.status === "published" ? "button-quiet" : "button-primary"}" type="button" data-ann-toggle="${item.id}">${item.status === "published" ? "撤回" : "发布"}</button></li>`).join("") : '<li class="empty">暂无公告</li>'}</ul>`;
    if (adminTab === "月度评选") return `<div class="panel" style="padding:24px"><h2 class="section-title">本月提名</h2><p class="muted">当前提名作品已同步到首页和“月度优秀作品”页面。</p><ul class="admin-list">${state.monthlyPicks.map((id) => { const work = workById(id); return work ? `<li class="admin-row"><span>${escapeHtml(work.title)}</span><span class="muted">${escapeHtml(work.author)}</span></li>` : ""; }).join("")}</ul></div>`;
    if (adminTab === "Agent 审核") return `<div class="panel" style="padding:24px"><h2 class="section-title">审核状态</h2><p>当前 Agent 为 PASSIVE。普通私信不会主动扫描；只有举报、公开作品和评论进入审核队列。</p><p class="muted">模型只输出结构化分析，最终动作由确定性 PolicyEngine 和管理员确认。</p></div>`;
    if (adminTab === "安全日志") return `<ul class="admin-list"><li class="admin-row"><span>审核任务创建</span><span class="muted">刚刚</span></li><li class="admin-row"><span>管理者处理举报</span><span class="muted">保留处理结果，不修改原始消息</span></li></ul>`;
    return `<div class="panel" style="padding:24px"><h2 class="section-title">${escapeHtml(adminTab)}</h2><p class="muted">这里已保留管理入口。正式版本接入服务端权限、审计和审核 API 后启用。</p></div>`;
  }

  function renderNotifications() {
    openModal("通知", state.notifications.length ? `<ul class="admin-list">${state.notifications.map((item) => `<li class="admin-row"><span>${escapeHtml(item.text)}</span><time class="muted">${escapeHtml(item.at)}</time></li>`).join("")}</ul>` : "<p>暂无通知。</p>");
    state.notifications.forEach((item) => { item.read = true; }); save(); renderHeader();
  }

  function openPublish() {
    openModal("投稿作品", `<form id="publish-form"><div class="field"><label>作品标题</label><input class="input" name="title" maxlength="80" required></div><div class="field"><label>体裁</label><select class="select" name="category">${categories.slice(1).map((category) => `<option>${category}</option>`).join("")}</select></div><div class="field"><label>作者</label><input class="input" name="author" maxlength="40" value="${escapeHtml(state.currentUser.name)}" required></div><div class="field"><label>正文</label><textarea class="textarea" name="body" maxlength="10000" required placeholder="在这里写下作品正文"></textarea></div></form>`, '<div class="modal-actions"><button class="button" type="button" data-close-modal>取消</button><button class="button button-primary" type="button" id="submit-publish">提交审核</button></div>');
    document.querySelector("#submit-publish").addEventListener("click", () => {
      const form = document.querySelector("#publish-form");
      if (!form.reportValidity()) return;
      const data = new FormData(form);
      const body = String(data.get("body")).split(/\n+/).map((line) => line.trim()).filter(Boolean);
      state.works.unshift({ id: `w${Date.now()}`, title: String(data.get("title")), author: String(data.get("author")), category: String(data.get("category")), likes: 0, views: 0, excerpt: body[0].slice(0, 90), body, comments: [] });
      state.notifications.unshift({ id: `n${Date.now()}`, text: "作品已提交审核，等待管理员处理", at: "刚刚", read: false });
      save(); closeModal(); renderHeader(); setRoute("works"); showToast("作品已提交，等待审核");
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

  function authorIdByName(name) {
    return state.authors.find((author) => author.name === name)?.id || "";
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
    if (target.matches("#theme-button")) return openThemeChooser();
    if (target.matches("[data-close-modal], #modal-close")) return closeModal();
    if (target.matches("[data-route]")) return setRoute(target.dataset.route);
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
    if (target.matches("[data-activity]")) return openModal("活动详情", `<h2 id="modal-title">${escapeHtml(byId(target.dataset.activity, state.activities).title)}</h2><p>${escapeHtml(byId(target.dataset.activity, state.activities).desc)}</p><p class="muted">报名与签到将在正式版本接入。</p>`);
  });

  document.querySelector("#publish-button").addEventListener("click", openPublish);
  document.querySelector("#theme-button").addEventListener("click", openThemeChooser);
  document.querySelector("#notification-button").addEventListener("click", renderNotifications);
  document.querySelector("#user-button").addEventListener("click", () => openModal("个人设置", "<p>当前为独立预览版，使用浏览器本地数据保存你的投稿、评论、私信和拉黑设置。</p><p class='muted'>正式版本将接入账号、服务端权限与审核记录。</p>"));
  modalLayer.addEventListener("click", (event) => { if (event.target === modalLayer) closeModal(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !modalLayer.hidden) closeModal(); });
  window.addEventListener("hashchange", () => { route = location.hash.replace(/^#\/?/, "") || "home"; render(); });
  applyTheme(localStorage.getItem(THEME_KEY) || "qingli");
  render();
})();
