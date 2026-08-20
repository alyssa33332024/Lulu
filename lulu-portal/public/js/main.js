const launchBtn = document.getElementById("launchBtn");
const launchHint = document.getElementById("launchHint");
const accountBtn = document.getElementById("accountBtn");
const accountPop = document.getElementById("accountPop");
const avatarGuest = document.getElementById("avatarGuest");
const avatarLetter = document.getElementById("avatarLetter");
const loginForm = document.getElementById("loginForm");
const loginName = document.getElementById("loginName");
const signedPanel = document.getElementById("signedPanel");
const accountHello = document.getElementById("accountHello");
const logoutBtn = document.getElementById("logoutBtn");

const ACCOUNT_KEY = "lulu.portal.account";

function readAccount() {
  try {
    const raw = localStorage.getItem(ACCOUNT_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    const name = String(data.name || "").trim();
    return name ? { name } : null;
  } catch {
    return null;
  }
}

function writeAccount(account) {
  if (!account) {
    localStorage.removeItem(ACCOUNT_KEY);
    return;
  }
  localStorage.setItem(ACCOUNT_KEY, JSON.stringify(account));
}

function paintAccount() {
  const account = readAccount();
  const open = accountPop && !accountPop.hidden;
  if (account) {
    accountBtn.classList.add("in");
    accountBtn.setAttribute("aria-label", account.name);
    avatarGuest.hidden = true;
    avatarLetter.hidden = false;
    avatarLetter.textContent = account.name.slice(0, 1);
    loginForm.hidden = true;
    signedPanel.hidden = false;
    accountHello.textContent = account.name;
  } else {
    accountBtn.classList.remove("in");
    accountBtn.setAttribute("aria-label", "登录");
    avatarGuest.hidden = false;
    avatarLetter.hidden = true;
    avatarLetter.textContent = "";
    loginForm.hidden = false;
    signedPanel.hidden = true;
  }
  accountBtn.setAttribute("aria-expanded", open ? "true" : "false");
}

function setPop(open) {
  accountPop.hidden = !open;
  accountBtn.setAttribute("aria-expanded", open ? "true" : "false");
  if (open && !readAccount()) {
    loginName.value = "";
    loginName.focus();
  }
}

async function readJson(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("接口返回了非 JSON（请确认打开的是 http://127.0.0.1:3920）");
  }
}

async function fetchStatus() {
  const res = await fetch("/api/status");
  const data = await readJson(res);
  if (!res.ok) throw new Error(data.error || "status failed");
  return data;
}

function paintStatus(data) {
  if (data.running) {
    launchBtn.textContent = "已打开";
    launchBtn.classList.add("running");
    launchHint.textContent = data.brain ? "可以说「露露」唤醒她。" : "";
  } else {
    launchBtn.textContent = "打开桌宠";
    launchBtn.classList.remove("running");
    launchHint.textContent = "";
  }
}

async function refresh() {
  try {
    paintStatus(await fetchStatus());
  } catch {
    paintStatus({ running: false, brain: false });
  }
}

accountBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  setPop(accountPop.hidden);
});

loginForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const name = loginName.value.trim();
  if (!name) return;
  writeAccount({ name });
  paintAccount();
  setPop(false);
});

logoutBtn.addEventListener("click", () => {
  writeAccount(null);
  paintAccount();
  setPop(false);
});

document.addEventListener("click", (e) => {
  if (accountPop.hidden) return;
  if (accountPop.contains(e.target) || accountBtn.contains(e.target)) return;
  setPop(false);
});

paintAccount();

launchBtn.addEventListener("click", async () => {
  launchBtn.disabled = true;
  try {
    const res = await fetch("/api/launch", { method: "POST" });
    const data = await readJson(res);
    if (res.ok && data.ok) {
      await refresh();
      for (let i = 0; i < 12; i += 1) {
        await new Promise((r) => setTimeout(r, 1500));
        await refresh();
        const st = await fetchStatus();
        if (st.running && st.brain) break;
      }
    }
  } catch {
    // 门户只展示未打开 / 已打开，失败时回到未打开
  } finally {
    await refresh();
    launchBtn.disabled = false;
  }
});

/* 轻量花瓣：氛围，不抢主视觉 */
(function petals() {
  const canvas = document.getElementById("petals");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0;
  let h = 0;
  const flakes = [];

  function resize() {
    w = canvas.width = window.innerWidth;
    h = canvas.height = window.innerHeight;
  }

  function spawn() {
    flakes.push({
      x: Math.random() * w,
      y: -20 - Math.random() * h * 0.3,
      r: 3 + Math.random() * 5,
      vy: 0.35 + Math.random() * 0.7,
      vx: -0.25 + Math.random() * 0.5,
      rot: Math.random() * Math.PI,
      vr: (-0.02 + Math.random() * 0.04),
      a: 0.25 + Math.random() * 0.35,
    });
  }

  function draw() {
    ctx.clearRect(0, 0, w, h);
    for (const p of flakes) {
      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = `rgba(242, 145, 169, ${p.a})`;
      ctx.beginPath();
      ctx.ellipse(0, 0, p.r, p.r * 0.55, 0, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
    }
    for (let i = flakes.length - 1; i >= 0; i -= 1) {
      if (flakes[i].y > h + 40) flakes.splice(i, 1);
    }
    if (!reduce && flakes.length < 28 && Math.random() < 0.08) spawn();
    requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener("resize", resize);
  if (!reduce) {
    for (let i = 0; i < 14; i += 1) spawn();
    requestAnimationFrame(draw);
  }
})();

refresh();
setInterval(refresh, 5000);
