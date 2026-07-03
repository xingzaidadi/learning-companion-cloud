const statusText = {
  not_started: "未开始",
  in_progress: "进行中",
  paused: "已暂停",
  checking: "检查中",
  completed: "已完成",
  needs_revision: "需订正",
  stuck: "卡住了",
};

const statusClass = {
  completed: "ok",
  needs_revision: "warn",
  stuck: "warn",
  checking: "warn",
  in_progress: "ok",
  paused: "warn",
};

function $(selector) {
  return document.querySelector(selector);
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([key, value]) => {
    if (key === "class") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else node.setAttribute(key, value);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function toast(message) {
  let box = $(".toast");
  if (!box) {
    box = el("div", { class: "toast" });
    document.body.append(box);
  }
  box.textContent = message;
  box.classList.add("show");
  setTimeout(() => box.classList.remove("show"), 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

function taskStatusTag(task) {
  return `<span class="tag ${statusClass[task.status] || ""}">${statusText[task.status] || task.status}</span>`;
}

function priorityTag(task) {
  return `<span class="tag ${task.priority === "P0" ? "p0" : ""}">${task.priority}</span>`;
}

async function postEvent(taskId, eventType, note = "") {
  await api(`/api/daily-tasks/${taskId}/event`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_type: eventType, note }),
  });
}

window.LearningApp = {
  statusText,
  toast,
  api,
  postEvent,
  taskStatusTag,
  priorityTag,
};
