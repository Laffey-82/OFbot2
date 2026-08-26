// ---------- Toast ----------
function toast(message, type) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.remove("success", "error");
  if (type) el.classList.add(type);
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 3000);
}

// ---------- Safe storage（受限环境 localStorage 可能抛 SecurityError） ----------
const memoryStorage = new Map();
const safeStorage = {
  get(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (err) {
      return memoryStorage.has(key) ? memoryStorage.get(key) : null;
    }
  },
  set(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (err) {
      memoryStorage.set(key, value);
    }
  },
};

// ---------- Safe init（单个模块初始化失败不拖垮整页脚本） ----------
function safeInit(name, fn) {
  try {
    fn();
  } catch (err) {
    console.error("[OFbot2] 模块初始化失败：" + name, err);
  }
}

// ---------- Flash messages from query params ----------
safeInit("flashMessages", function flashMessages() {
  const params = new URLSearchParams(window.location.search);
  let message = null;
  let type = null;
  if (params.has("msg")) { message = params.get("msg"); type = "success"; }
  else if (params.has("error")) {
    const code = params.get("error");
    message = code === "1" || code === "2" ? "操作失败，请检查输入" : code;
    type = "error";
  }
  if (message) {
    setTimeout(() => toast(message, type), 150);
    params.delete("msg");
    params.delete("error");
    const qs = params.toString();
    try {
      history.replaceState(null, "", window.location.pathname + (qs ? "?" + qs : ""));
    } catch (err) {
      // 受限环境（沙箱 iframe / 不透明 origin）可能不允许改写历史记录，忽略即可
    }
  }
});

// ---------- AJAX forms with button loading state ----------
async function submitForm(form) {
  const action = form.getAttribute("action");
  const body = new FormData(form);
  const buttons = form.querySelectorAll("button[type='submit']");
  const originals = [];
  buttons.forEach((button) => {
    originals.push([button, button.innerHTML]);
    button.disabled = true;
    button.innerHTML = "处理中…";
  });
  try {
    const response = await fetch(action, { method: "POST", body });
    if (response.redirected) {
      window.location.href = response.url;
      return;
    }
    if (response.ok) {
      toast("操作成功", "success");
      window.location.reload();
    } else {
      toast("操作失败，请检查输入", "error");
    }
  } catch (err) {
    toast("网络错误，请重试", "error");
  } finally {
    originals.forEach(([button, html]) => {
      button.disabled = false;
      button.innerHTML = html;
    });
  }
}

document.addEventListener("submit", (event) => {
  const form = event.target;
  if (!form.classList.contains("js-ajax")) return;
  event.preventDefault();
  submitForm(form);
});

// ---------- Confirm dialog ----------
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-confirm]");
  if (button && !window.confirm(button.getAttribute("data-confirm"))) {
    event.preventDefault();
    event.stopImmediatePropagation();
  }
});

// ---------- Back to top ----------
const backTop = document.createElement("button");
backTop.id = "back-top";
backTop.textContent = "↑";
backTop.title = "返回顶部";
backTop.setAttribute("aria-label", "返回顶部");
document.body.appendChild(backTop);
window.addEventListener("scroll", () => {
  backTop.classList.toggle("show", window.scrollY > 400);
});
backTop.addEventListener("click", () => {
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ---------- Table search filter ----------
function applyTableFilter(input) {
  const table = document.getElementById(input.dataset.tableFilter);
  if (!table) return;
  const query = input.value.trim().toLowerCase();
  const rows = table.querySelectorAll("tbody tr[data-row]");
  let visible = 0;
  rows.forEach((row, index) => {
    const match = row.textContent.toLowerCase().includes(query);
    const pagination =
      (window.__tablePaginations && window.__tablePaginations.get(table)) ||
      null;
    if (query) {
      row.style.display = match ? "" : "none";
    } else if (pagination) {
      row.style.display = index < pagination.shown ? "" : "none";
    } else {
      row.style.display = match ? "" : "none";
    }
    if (match) visible += 1;
  });
  let empty = document.querySelector(`[data-empty-for="${input.dataset.tableFilter}"]`);
  if (empty) empty.classList.toggle("hidden", visible > 0);
  const count = document.querySelector(`[data-count-for="${input.dataset.tableFilter}"]`);
  if (count) count.textContent = `${visible} / ${rows.length}`;

  // 自动显示"无匹配结果"行
  const autoRow = table.querySelector("tr.filter-empty");
  if (query && rows.length > 0 && visible === 0) {
    if (!autoRow) {
      const row = document.createElement("tr");
      row.className = "filter-empty";
      const cell = document.createElement("td");
      const colSpan = table.querySelectorAll("thead th").length || 1;
      cell.colSpan = colSpan;
      cell.className = "empty";
      cell.textContent = "无匹配结果";
      row.appendChild(cell);
      table.querySelector("tbody").appendChild(row);
    }
  } else if (autoRow) {
    autoRow.remove();
  }
}

document.querySelectorAll("[data-table-filter]").forEach((input) => {
  input.addEventListener("input", () => applyTableFilter(input));
});

// ---------- Shared bulk-select helpers ----------
function initSelectAll(selectAllId, checkboxClass) {
  const selectAll = document.getElementById(selectAllId);
  if (!selectAll) return;
  selectAll.addEventListener("change", () => {
    document.querySelectorAll("." + checkboxClass).forEach((checkbox) => {
      checkbox.checked = selectAll.checked;
    });
  });
}

function collectChecked(checkboxClass) {
  return Array.from(
    document.querySelectorAll("." + checkboxClass + ":checked")
  ).map((checkbox) => checkbox.value);
}

// ---------- Shared export-button helper ----------
// fieldMap: { queryParam: elementId }
function initExportButton(buttonId, endpoint, fieldMap) {
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.addEventListener("click", () => {
    const params = new URLSearchParams();
    Object.entries(fieldMap).forEach(([param, elementId]) => {
      const element = document.getElementById(elementId);
      if (!element) return;
      const value = element.value.trim();
      if (value) params.set(param, value);
    });
    window.location.href = endpoint + "?" + params.toString();
  });
}

// ---------- Long table progressive reveal ----------
window.__tablePaginations = window.__tablePaginations || new Map();
document.querySelectorAll("table.js-paginate").forEach((table) => {
  const rows = Array.from(table.querySelectorAll("tbody tr[data-row]"));
  if (rows.length <= 50) return;
  const step = 50;
  const pagination = { rows, step, shown: step };
  window.__tablePaginations.set(table, pagination);
  rows.forEach((row, index) => {
    if (index >= step) row.style.display = "none";
  });
  const applyBoundary = () => {
    const input = table.id
      ? document.querySelector(`[data-table-filter="${table.id}"]`)
      : null;
    if (input && input.value.trim()) {
      applyTableFilter(input);
      return;
    }
    rows.forEach((row, index) => {
      row.style.display = index < pagination.shown ? "" : "none";
    });
  };
  const tfoot = table.createTFoot();
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = table.querySelectorAll("thead th").length || 1;
  td.className = "empty";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "secondary small";
  const updateButton = () => {
    const remaining = rows.length - pagination.shown;
    btn.textContent = remaining > 0 ? `显示更多（剩余 ${remaining} 条）` : "已显示全部";
    btn.disabled = remaining <= 0;
  };
  btn.addEventListener("click", () => {
    pagination.shown = Math.min(rows.length, pagination.shown + step);
    applyBoundary();
    updateButton();
  });
  updateButton();
  td.appendChild(btn);
  tr.appendChild(td);
  tfoot.appendChild(tr);
});

// ---------- Sidebar (mobile) ----------
safeInit("sidebar", () => {
  const sidebar = document.getElementById("sidebar");
  const menuToggle = document.getElementById("menu-toggle");
  const sidebarClose = document.getElementById("sidebar-close");
  let sidebarOverlay = null;
  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove("open");
    document.body.style.overflow = "";
    if (sidebarOverlay) {
      sidebarOverlay.remove();
      sidebarOverlay = null;
    }
  }
  function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.add("open");
    document.body.style.overflow = "hidden";
    if (!sidebarOverlay) {
      sidebarOverlay = document.createElement("div");
      sidebarOverlay.className = "sidebar-overlay";
      document.body.appendChild(sidebarOverlay);
    }
  }
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", openSidebar);
  }
  if (sidebarClose && sidebar) {
    sidebarClose.addEventListener("click", closeSidebar);
  }
  document.addEventListener("click", (event) => {
    if (sidebarOverlay && event.target === sidebarOverlay) closeSidebar();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar && sidebar.classList.contains("open")) {
      closeSidebar();
    }
  });
  if (sidebar) {
    sidebar.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        if (window.innerWidth <= 860) closeSidebar();
      });
    });
  }
});

// ---------- Theme ----------
safeInit("theme", () => {
  // 图表页通过 __ofbot2RedrawCallbacks 注册重绘函数，切换主题后自动刷新 canvas 颜色
  window.__ofbot2Redraw =
    window.__ofbot2Redraw || window.__ofbot2RedrawCallbacks || [];
  function requestRedraw() {
    (window.__ofbot2Redraw || []).forEach((fn) => {
      try {
        fn();
      } catch (err) {
        console.error("[OFbot2] 主题重绘失败", err);
      }
    });
  }
  function applyTheme(isDark) {
    if (isDark) {
      document.documentElement.setAttribute("data-theme", "dark");
    } else {
      // 亮色主题不保留任何 data-theme 标记
      document.documentElement.removeAttribute("data-theme");
    }
    const toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.textContent = isDark ? "暗色" : "亮色";
      toggle.title = isDark ? "当前暗色，点击切换亮色" : "当前亮色，点击切换暗色";
    }
  }
  const themeToggle = document.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme");
      const nextIsDark = current !== "dark";
      applyTheme(nextIsDark);
      requestRedraw();
      safeStorage.set("theme", nextIsDark ? "dark" : "light");
      toast(nextIsDark ? "已切换到暗色主题" : "已切换到亮色主题");
    });
  }
  const savedTheme = safeStorage.get("theme");
  if (savedTheme) {
    applyTheme(savedTheme === "dark");
  } else if (
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches
  ) {
    applyTheme(true);
  } else {
    applyTheme(false);
  }
});

// ---------- Adapter status polling ----------
safeInit("adapterStatus", () => {
  async function refreshStatus() {
    const el = document.querySelector("[data-adapter-status]");
    if (!el) return;
    try {
      const response = await fetch("/api/v1/status");
      const data = await response.json();
      const adapters = data.adapters || {};
      const names = Object.keys(adapters);
      el.innerHTML = names.length
        ? names.map((name) =>
            `<span class="badge ${adapters[name] === "connected" ? "success" : "warning"}">${name}: ${adapters[name]}</span>`
          ).join(" ")
        : '<span class="muted">未配置适配器</span>';
    } catch (err) {
      el.textContent = "无法连接";
    }
  }
  setInterval(refreshStatus, 10000);
  refreshStatus();
});

// ---------- Copy to clipboard ----------
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-copy]");
  if (!target) return;
  const text = target.getAttribute("data-copy");
  navigator.clipboard?.writeText(text).then(
    () => toast("已复制", "success"),
    () => toast("复制失败", "error")
  );
});

// ---------- Keyboard shortcuts ----------
document.addEventListener("keydown", (event) => {
  const el = document.activeElement;
  const tag = el ? el.tagName : "";
  const typing =
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    (el && el.isContentEditable);
  if (event.key === "/" && !typing) {
    event.preventDefault();
    const input = document.querySelector("[data-table-filter]");
    if (input) input.focus();
  } else if (
    (event.key === "t" || event.key === "T") &&
    !typing &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  ) {
    const toggle = document.getElementById("theme-toggle");
    if (toggle) toggle.click();
  } else if (event.key === "Escape" && el && el.matches("[data-table-filter]")) {
    el.value = "";
    applyTableFilter(el);
    el.blur();
  }
});
