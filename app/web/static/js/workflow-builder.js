function initWorkflowBuilder(options) {
  const actions = options.actions || [];
  const recordTypes = options.recordTypes || [];
  const recordSchemas = options.recordSchemas || {};
  const wfSteps = Array.isArray(options.steps) ? options.steps.map((s) => JSON.parse(JSON.stringify(s))) : [];
  const trigger = options.trigger || { type: "message" };
  const initialCondition =
    Array.isArray(options.condition)
      ? options.condition
      : options.condition && Array.isArray(options.condition.conditions)
        ? options.condition.conditions
        : [];
  const initialConditionMode =
    options.condition && options.condition.match
      ? options.condition.match
      : "all";
  const paramRows = [];
  const conditionRows = [];

  const actionSelect = document.getElementById("wf-action");
  const paramRowsEl = document.getElementById("wf-param-rows");
  const stepsList = document.getElementById("wf-steps");
  const jsonArea = document.getElementById("wf-json");
  const triggerJsonInput = document.getElementById("wf-trigger-json");
  const triggerSelect = document.getElementById("wf-trigger");
  const cronRow = document.getElementById("wf-cron-row");
  const cronInput = document.getElementById("wf-cron");
  const conditionRowsEl = document.getElementById("wf-condition-rows");
  const conditionArea = document.getElementById("wf-condition");
  const addConditionBtn = document.getElementById("wf-add-condition");
  const conditionMode = document.getElementById("wf-condition-mode");
  const conditionOps = ["eq", "ne", "contains", "exists", "gt", "lt", "in"];
  const recordHelper = document.getElementById("wf-record-helper");
  const recordTypeSelect = document.getElementById("wf-record-type");
  const loadSchemaBtn = document.getElementById("wf-load-schema");
  const undoBtn = document.getElementById("wf-undo");
  const redoBtn = document.getElementById("wf-redo");
  const undoStack = [];
  const redoStack = [];
  let dragStepIndex = -1;

  function captureState() {
    let condition = null;
    try {
      condition = JSON.parse(conditionArea.value || "null");
    } catch (e) {}
    return {
      steps: JSON.parse(JSON.stringify(wfSteps)),
      trigger: {
        type: triggerSelect ? triggerSelect.value : trigger.type || "message",
        cron: cronInput ? cronInput.value : trigger.cron || "",
      },
      condition,
      params: paramRows.map(({ key, value }) => [key.value, value.value]),
    };
  }

  function updateUndoButtons() {
    if (undoBtn) undoBtn.disabled = undoStack.length === 0;
    if (redoBtn) redoBtn.disabled = redoStack.length === 0;
  }

  function applyState(state) {
    wfSteps.splice(0, wfSteps.length, ...JSON.parse(JSON.stringify(state.steps)));
    if (triggerSelect) {
      triggerSelect.value = state.trigger.type || "message";
      if (cronRow) {
        cronRow.style.display =
          triggerSelect.value === "schedule" ? "" : "none";
      }
      if (cronInput) cronInput.value = state.trigger.cron || "";
    }
    paramRowsEl.innerHTML = "";
    paramRows.length = 0;
    (state.params || []).forEach(([key, value]) => addParamRow(key, value));
    if (!paramRows.length) addParamRow();
    conditionRowsEl.innerHTML = "";
    conditionRows.length = 0;
    const conds =
      state.condition && Array.isArray(state.condition.conditions)
        ? state.condition.conditions
        : Array.isArray(state.condition)
          ? state.condition
          : [];
    conds.forEach((item) => addConditionRow(item));
    if (conditionMode) {
      conditionMode.value =
        (state.condition && state.condition.match) || "all";
    }
    syncCondition();
    renderSteps();
    syncJson();
    updateUndoButtons();
  }

  function pushUndo(state) {
    const snapshot = JSON.stringify(state);
    if (undoStack.length && undoStack[undoStack.length - 1] === snapshot) {
      return;
    }
    undoStack.push(snapshot);
    if (undoStack.length > 50) undoStack.shift();
    redoStack.length = 0;
    updateUndoButtons();
  }

  function undo() {
    if (!undoStack.length) return;
    const current = JSON.stringify(captureState());
    redoStack.push(current);
    applyState(JSON.parse(undoStack.pop()));
  }

  function redo() {
    if (!redoStack.length) return;
    const current = JSON.stringify(captureState());
    undoStack.push(current);
    applyState(JSON.parse(redoStack.pop()));
  }

  if (undoBtn) undoBtn.addEventListener("click", undo);
  if (redoBtn) redoBtn.addEventListener("click", redo);
  document.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") {
      return;
    }
    const el = document.activeElement;
    const tag = el ? el.tagName : "";
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
    event.preventDefault();
    if (event.shiftKey) redo();
    else undo();
  });

  actionSelect.innerHTML = "";
  actions.forEach((action) => {
    const option = document.createElement("option");
    option.value = action;
    option.textContent = action;
    actionSelect.appendChild(option);
  });
  if (!actions.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "（暂无已注册动作）";
    actionSelect.appendChild(option);
  }
  actionSelect.addEventListener("change", updateRecordHelper);
  updateRecordHelper();

  if (triggerSelect) {
    triggerSelect.value = trigger.type || "message";
    if (cronRow) cronRow.style.display = trigger.type === "schedule" ? "" : "none";
    if (cronInput) cronInput.value = trigger.cron || "";
  }

  function addParamRow(key, value) {
    const row = document.createElement("div");
    row.className = "param-row";
    const keyInput = document.createElement("input");
    keyInput.placeholder = "参数名";
    keyInput.value = key || "";
    const valueInput = document.createElement("input");
    valueInput.placeholder = "值";
    valueInput.value = value || "";
    row.appendChild(keyInput);
    row.appendChild(valueInput);
    paramRowsEl.appendChild(row);
    paramRows.push({ key: keyInput, value: valueInput });
  }

  function readParams() {
    const params = {};
    paramRows.forEach(({ key, value }) => {
      if (key.value.trim()) params[key.value.trim()] = value.value;
    });
    return params;
  }

  function setParam(key, value) {
    let row = paramRows.find((item) => item.key.value === key);
    if (!row) {
      addParamRow(key, "");
      row = paramRows[paramRows.length - 1];
    }
    row.value.value = value;
  }

  function updateRecordHelper() {
    if (!recordHelper || !recordTypeSelect) return;
    const show = actionSelect.value === "create_record";
    recordHelper.hidden = !show;
    if (!show) return;
    recordTypeSelect.innerHTML = "";
    recordTypes.forEach((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      recordTypeSelect.appendChild(option);
    });
    if (!recordTypeSelect.value && recordTypeSelect.options.length) {
      recordTypeSelect.value = recordTypeSelect.options[0].value;
    }
  }

  if (loadSchemaBtn) {
    loadSchemaBtn.addEventListener("click", () => {
      const typeName = recordTypeSelect.value;
      if (!typeName) return toast("请先选择记录类型", "error");
      const schema = recordSchemas[typeName] || [];
      const data = {};
      schema.forEach((field) => {
        if (field.type === "boolean") data[field.name] = false;
        else if (field.type === "integer" || field.type === "number") {
          data[field.name] = 0;
        } else {
          data[field.name] = "";
        }
      });
      pushUndo(captureState());
      setParam("record_type", typeName);
      setParam("data", JSON.stringify(data, null, 2));
      toast("已生成数据模板", "success");
    });
  }

  function renderSteps() {
    stepsList.innerHTML = "";
    wfSteps.forEach((step, index) => {
      const li = document.createElement("li");
      li.className = "step-item";
      li.draggable = true;
      li.dataset.index = String(index);
      li.addEventListener("dragstart", (event) => {
        dragStepIndex = index;
        li.classList.add("dragging");
        event.dataTransfer.effectAllowed = "move";
        if (event.dataTransfer.setData) {
          event.dataTransfer.setData("text/plain", String(index));
        }
      });
      li.addEventListener("dragover", (event) => {
        event.preventDefault();
        if (index !== dragStepIndex) li.classList.add("drag-over");
      });
      li.addEventListener("dragleave", () => li.classList.remove("drag-over"));
      li.addEventListener("drop", (event) => {
        event.preventDefault();
        li.classList.remove("drag-over");
        if (dragStepIndex < 0 || dragStepIndex === index) return;
        pushUndo(captureState());
        const moved = wfSteps.splice(dragStepIndex, 1)[0];
        wfSteps.splice(index, 0, moved);
        dragStepIndex = -1;
        renderSteps();
        syncJson();
      });
      li.addEventListener("dragend", () => {
        li.classList.remove("dragging");
        document.querySelectorAll(".step-item.drag-over").forEach((el) => {
          el.classList.remove("drag-over");
        });
        dragStepIndex = -1;
      });
      if ("ontouchstart" in window) {
        let pressTimer = null;
        let startX = 0;
        let startY = 0;
        let touchActive = false;
        let lastTouchTarget = null;
        const cancelTouchPress = () => {
          if (pressTimer) {
            clearTimeout(pressTimer);
            pressTimer = null;
          }
          if (touchActive) {
            touchActive = false;
            li.classList.remove("dragging");
            li.style.touchAction = "";
            document.querySelectorAll(".step-item.drag-over").forEach((el) => {
              el.classList.remove("drag-over");
            });
          }
        };
        li.addEventListener(
          "touchstart",
          (event) => {
            startX = event.touches[0].clientX;
            startY = event.touches[0].clientY;
            pressTimer = setTimeout(() => {
              pressTimer = null;
              touchActive = true;
              dragStepIndex = index;
              li.classList.add("dragging");
              li.style.touchAction = "none";
              toast("长按中，拖动以排序", "success");
            }, 350);
          },
          { passive: true }
        );
        li.addEventListener(
          "touchmove",
          (event) => {
            const dx = event.touches[0].clientX - startX;
            const dy = event.touches[0].clientY - startY;
            if (!touchActive) {
              if (Math.abs(dx) > 12 || Math.abs(dy) > 12) cancelTouchPress();
              return;
            }
            event.preventDefault();
            const point = document.elementFromPoint(
              event.touches[0].clientX,
              event.touches[0].clientY
            );
            const item = point && point.closest
              ? point.closest(".step-item")
              : null;
            document.querySelectorAll(".step-item.drag-over").forEach((el) => {
              el.classList.remove("drag-over");
            });
            if (item && item !== li) item.classList.add("drag-over");
            lastTouchTarget = item;
          },
          { passive: false }
        );
        li.addEventListener("touchend", () => {
          if (pressTimer) {
            clearTimeout(pressTimer);
            pressTimer = null;
          }
          if (touchActive) {
            touchActive = false;
            li.classList.remove("dragging");
            li.style.touchAction = "";
            document.querySelectorAll(".step-item.drag-over").forEach((el) => {
              el.classList.remove("drag-over");
            });
            if (lastTouchTarget && lastTouchTarget !== li) {
              const targetIndex = Number(lastTouchTarget.dataset.index);
              if (
                !Number.isNaN(targetIndex) &&
                targetIndex !== dragStepIndex
              ) {
                pushUndo(captureState());
                const moved = wfSteps.splice(dragStepIndex, 1)[0];
                wfSteps.splice(targetIndex, 0, moved);
                renderSteps();
                syncJson();
              }
            }
            dragStepIndex = -1;
            lastTouchTarget = null;
          }
        });
        li.addEventListener("touchcancel", cancelTouchPress);
      }
      const badge = document.createElement("span");
      badge.className = "badge info";
      badge.textContent = step.action;
      const summary = document.createElement("code");
      summary.textContent = JSON.stringify(step.params || {});
      const controls = document.createElement("span");
      controls.className = "actions";
      const up = document.createElement("button");
      up.type = "button";
      up.className = "small secondary";
      up.textContent = "↑";
      up.disabled = index === 0;
      up.addEventListener("click", () => {
        pushUndo(captureState());
        [wfSteps[index - 1], wfSteps[index]] = [wfSteps[index], wfSteps[index - 1]];
        renderSteps();
        syncJson();
      });
      const down = document.createElement("button");
      down.type = "button";
      down.className = "small secondary";
      down.textContent = "↓";
      down.disabled = index === wfSteps.length - 1;
      down.addEventListener("click", () => {
        pushUndo(captureState());
        [wfSteps[index + 1], wfSteps[index]] = [wfSteps[index], wfSteps[index + 1]];
        renderSteps();
        syncJson();
      });
      const del = document.createElement("button");
      del.type = "button";
      del.className = "small danger";
      del.textContent = "删除";
      del.addEventListener("click", () => {
        pushUndo(captureState());
        wfSteps.splice(index, 1);
        renderSteps();
        syncJson();
      });
      const copy = document.createElement("button");
      copy.type = "button";
      copy.className = "small secondary";
      copy.textContent = "复制";
      copy.title = "复制该步骤到下方";
      copy.addEventListener("click", () => {
        pushUndo(captureState());
        wfSteps.splice(
          index + 1,
          0,
          JSON.parse(JSON.stringify(step))
        );
        renderSteps();
        syncJson();
      });
      controls.append(up, down, del, copy);
      li.append(badge, summary, controls);
      stepsList.appendChild(li);
    });
  }

  function syncJson() {
    jsonArea.value = JSON.stringify(wfSteps, null, 2);
    const triggerType = triggerSelect.value;
    const t = { type: triggerType };
    if (triggerType === "schedule" && cronInput.value.trim()) {
      t.cron = cronInput.value.trim();
    }
    triggerJsonInput.value = JSON.stringify(t);
  }

  function syncCondition() {
    const list = [];
    conditionRows.forEach((row) => {
      if (row.field.value.trim()) {
        list.push({
          field: row.field.value.trim(),
          op: row.op.value,
          value: row.value.value
        });
      }
    });
    conditionArea.value = list.length
      ? JSON.stringify({ match: conditionMode.value, conditions: list })
      : "";
  }

  if (conditionMode) {
    conditionMode.value = initialConditionMode;
    conditionMode.addEventListener("change", () => {
      pushUndo(captureState());
      syncCondition();
    });
  }

  function addConditionRow(item) {
    const row = document.createElement("div");
    row.className = "condition-row";
    const field = document.createElement("input");
    field.placeholder = "字段（支持点号路径）";
    field.value = (item && item.field) || "";
    const op = document.createElement("select");
    conditionOps.forEach((opName) => {
      const option = document.createElement("option");
      option.value = opName;
      option.textContent = opName;
      op.appendChild(option);
    });
    op.value = (item && item.op) || "eq";
    const value = document.createElement("input");
    value.placeholder = "值";
    value.value = item && item.value !== undefined ? item.value : "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "small danger";
    remove.textContent = "删除";
    remove.addEventListener("click", () => {
      pushUndo(captureState());
      conditionRows.splice(conditionRows.indexOf(entry), 1);
      row.remove();
      syncCondition();
    });
    const entry = { field, op, value };
    conditionRows.push(entry);
    row.append(field, op, value, remove);
    conditionRowsEl.appendChild(row);
    [field, op, value].forEach((el) =>
      el.addEventListener("input", () => {
        pushUndo(captureState());
        syncCondition();
      })
    );
  }

  document.getElementById("wf-add-param").addEventListener("click", () => addParamRow());
  if (addConditionBtn) {
    addConditionBtn.addEventListener("click", () => {
      pushUndo(captureState());
      addConditionRow();
    });
  }
  document.getElementById("wf-add-step").addEventListener("click", () => {
    const action = actionSelect.value;
    if (!action) return toast("请选择动作", "error");
    pushUndo(captureState());
    wfSteps.push({ action, params: readParams() });
    paramRowsEl.innerHTML = "";
    paramRows.length = 0;
    addParamRow();
    renderSteps();
    syncJson();
  });
  triggerSelect.addEventListener("change", () => {
    pushUndo(captureState());
    const isSchedule = triggerSelect.value === "schedule";
    cronRow.style.display = isSchedule ? "" : "none";
    syncJson();
  });
  cronInput.addEventListener("input", () => {
    pushUndo(captureState());
    syncJson();
  });
  jsonArea.addEventListener("input", () => {
    try {
      wfSteps.splice(0, wfSteps.length, ...JSON.parse(jsonArea.value));
      renderSteps();
    } catch (e) {}
  });

  if (wfSteps.length) {
    const first = wfSteps[0];
    if (first && first.params) {
      Object.entries(first.params).forEach(([key, value]) => addParamRow(key, String(value)));
    }
  } else {
    addParamRow("text", "hi");
  }
  const conditionItems =
    initialCondition.length
      ? initialCondition
      : (() => {
          try {
            const parsed = JSON.parse(conditionArea.value || "[]");
            return Array.isArray(parsed)
              ? parsed
              : parsed && Array.isArray(parsed.conditions)
                ? parsed.conditions
                : [];
          } catch (e) {
            return [];
          }
        })();
  conditionItems.forEach((item) => addConditionRow(item));
  syncCondition();
  renderSteps();
  syncJson();
}
