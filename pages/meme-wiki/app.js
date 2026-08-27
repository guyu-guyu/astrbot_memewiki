const bridge = window.AstrBotPluginPage;
const tableBody = document.getElementById("entry-table-body");
const emptyState = document.getElementById("empty-state");
const entryCount = document.getElementById("entry-count");
const status = document.getElementById("status");
const refreshButton = document.getElementById("refresh-button");

let entries = [];

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("is-error", isError);
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value || "-";
  }
  return new Intl.DateTimeFormat(bridge.getLocale(), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function createCell(value, className = "") {
  const cell = document.createElement("td");
  cell.textContent = value || "-";
  if (className) {
    cell.className = className;
  }
  return cell;
}

function renderEntries() {
  tableBody.replaceChildren();
  entryCount.textContent = `${entries.length} 条词条`;
  emptyState.hidden = entries.length !== 0;

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.append(
      createCell(entry.term, "term-cell"),
      createCell(entry.meaning, "meaning-cell"),
      createCell(entry.source),
      createCell(`${Math.round(Number(entry.confidence || 0) * 100)}%`),
      createCell(formatDate(entry.updated_at), "date-cell"),
    );

    const actionCell = document.createElement("td");
    actionCell.className = "action-column";
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "delete-button";
    deleteButton.textContent = "删除";
    deleteButton.setAttribute("aria-label", `删除 ${entry.term}`);
    deleteButton.addEventListener("click", () => deleteEntry(entry.term, deleteButton));
    actionCell.append(deleteButton);
    row.append(actionCell);
    tableBody.append(row);
  }
}

async function loadEntries() {
  refreshButton.disabled = true;
  setStatus("正在加载词条...");
  try {
    const result = await bridge.apiGet("dashboard/memes");
    entries = Array.isArray(result.entries) ? result.entries : [];
    renderEntries();
    setStatus("");
  } catch (error) {
    setStatus(error.message || "加载词条失败", true);
  } finally {
    refreshButton.disabled = false;
  }
}

async function deleteEntry(term, button) {
  if (!window.confirm(`确定删除“${term}”吗？`)) {
    return;
  }
  button.disabled = true;
  setStatus(`正在删除“${term}”...`);
  try {
    await bridge.apiPost("dashboard/memes/delete", { term });
    entries = entries.filter((entry) => entry.term !== term);
    renderEntries();
    setStatus(`已删除“${term}”`);
  } catch (error) {
    button.disabled = false;
    setStatus(error.message || "删除词条失败", true);
  }
}

refreshButton.addEventListener("click", loadEntries);
await bridge.ready();
await loadEntries();
