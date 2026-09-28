(function () {
  "use strict";
  const root = document.getElementById("fangfei-pet");
  if (!root) return;
  const bubble = root.querySelector(".pet-bubble");
  let stateTimer = null;
  let bubbleTimer = null;
  let dragState = null;
  let moved = false;
  const messages = [
    "今天也读一段喜欢的话吧。",
    "把想写的先写下来，不必一次完成。",
    "有新评论时我会提醒你。",
    "慢一点，文字会找到自己的方向。",
    "愿意的话，去认识一位新作者。",
    "休息一会儿，灵感也许就在回来的路上。"
  ];

  const setState = (next, duration) => {
    clearTimeout(stateTimer);
    root.dataset.state = next;
    if (duration) stateTimer = setTimeout(() => { root.dataset.state = "idle"; }, duration);
  };
  const pulse = (next, duration) => setState(next, duration || 800);
  const say = (text) => {
    clearTimeout(bubbleTimer);
    bubble.textContent = text;
    bubble.hidden = false;
    bubbleTimer = setTimeout(() => { bubble.hidden = true; }, 2600);
  };
  const clamp = () => {
    const rect = root.getBoundingClientRect();
    const left = Math.max(8, Math.min(innerWidth - rect.width - 8, rect.left));
    const top = Math.max(8, Math.min(innerHeight - rect.height - 8, rect.top));
    if (root.style.left) root.style.left = left + "px";
    if (root.style.top) root.style.top = top + "px";
  };
  const save = () => {
    const rect = root.getBoundingClientRect();
    try { localStorage.setItem("fangfei_pet_position_v1", JSON.stringify({ left: rect.left, top: rect.top })); } catch (e) {}
  };
  const restore = () => {
    try {
      const value = JSON.parse(localStorage.getItem("fangfei_pet_position_v1") || "null");
      if (!value || !Number.isFinite(value.left) || !Number.isFinite(value.top)) return;
      root.style.left = value.left + "px";
      root.style.top = value.top + "px";
      root.style.right = "auto";
      root.style.bottom = "auto";
      clamp();
    } catch (e) {}
  };

  root.addEventListener("pointerenter", () => { if (!dragState && root.dataset.state === "idle") setState("hover"); });
  root.addEventListener("pointerleave", () => { if (!dragState && root.dataset.state === "hover") setState("idle"); });
  root.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const rect = root.getBoundingClientRect();
    dragState = { id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
    moved = false;
    root.classList.add("is-dragging");
    try { root.setPointerCapture(event.pointerId); } catch (e) {}
  });
  root.addEventListener("pointermove", (event) => {
    if (!dragState || dragState.id !== event.pointerId) return;
    const dx = event.clientX - dragState.x;
    const dy = event.clientY - dragState.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    root.style.left = dragState.left + dx + "px";
    root.style.top = dragState.top + dy + "px";
    root.style.right = "auto";
    root.style.bottom = "auto";
    clamp();
  });
  root.addEventListener("pointerup", (event) => {
    if (!dragState || dragState.id !== event.pointerId) return;
    root.classList.remove("is-dragging");
    try { root.releasePointerCapture(event.pointerId); } catch (e) {}
    if (moved) save();
    else {
      pulse("click", 720);
      say(messages[Math.floor(Math.random() * messages.length)]);
    }
    dragState = null;
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      pulse("click", 720);
      say(messages[Math.floor(Math.random() * messages.length)]);
    }
  });
  root.addEventListener("dblclick", () => { pulse("sleep", 1800); say("让我打个盹。"); });
  window.addEventListener("resize", clamp);
  restore();

  window.FangfeiPet = {
    pulse,
    loading: () => pulse("loading", 1000),
    success: () => pulse("success", 1000),
    error: () => pulse("error", 900),
    notify: () => pulse("notify", 1200),
    music: () => setState("music", 0),
    idle: () => setState("idle", 0),
    happy: () => pulse("success", 1000)
  };
})();
