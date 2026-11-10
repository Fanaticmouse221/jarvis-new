import { api } from "./api.js";
import { h, section, toast } from "./util.js";

export async function renderTodos(page) {
  const list = h("div", { class: "rows" });
  const plans = h("div", { class: "rows" });
  const title = h("input", { class: "input", maxlength: 500, placeholder: "What needs doing?", "aria-label": "To-do title" });
  const details = h("input", { class: "input", maxlength: 2000, placeholder: "Optional details", "aria-label": "To-do details" });
  const due = h("input", { class: "input", type: "datetime-local", "aria-label": "To-do due date" });
  const problem = h("span", { class: "hint" });
  const add = async () => {
    try {
      await api("/todos", { method: "POST", body: { title: title.value, details: details.value, due_at: due.value ? new Date(due.value).toISOString() : null } });
      title.value = "";
      details.value = "";
      due.value = "";
      problem.textContent = "";
      await load();
    } catch (error) {
      problem.textContent = error.message;
    }
  };
  const planTitle = h("input", { class: "input", maxlength: 500, placeholder: "Plan title", "aria-label": "Plan title" });
  const planSteps = h("textarea", { class: "input", rows: 4, maxlength: 25000, placeholder: "One step per line", "aria-label": "Plan steps" });
  const planProblem = h("span", { class: "hint" });
  const addPlan = async () => {
    try {
      const steps = planSteps.value.split(/\r?\n/).map((step) => step.trim()).filter(Boolean);
      await api("/plans", { method: "POST", body: { title: planTitle.value, steps } });
      planTitle.value = "";
      planSteps.value = "";
      planProblem.textContent = "";
      await loadPlans();
    } catch (error) {
      planProblem.textContent = error.message;
    }
  };
  async function load() {
    try {
      const [pending, completed] = await Promise.all([api("/todos?status=pending"), api("/todos?status=completed")]);
      list.replaceChildren(
        ...pending.map(todoRow),
        ...(completed.length ? [h("h2", { class: "group-heading", text: "Completed" }), ...completed.map(todoRow)] : []),
      );
      if (!pending.length && !completed.length) list.append(h("p", { class: "hint", text: "No to-dos yet." }));
    } catch (error) {
      list.replaceChildren(h("p", { class: "error-box", text: error.message }));
    }
  }
  async function loadPlans() {
    try {
      const items = await api("/plans?status=all");
      plans.replaceChildren(...items.map(planRow));
      if (!items.length) plans.append(h("p", { class: "hint", text: "No plans yet." }));
    } catch (error) {
      plans.replaceChildren(h("p", { class: "error-box", text: error.message }));
    }
  }
  function todoRow(todo) {
    const done = todo.status === "completed";
    return h("div", { class: "row" },
      h("div", { class: "row-text" }, h("strong", { text: todo.title, class: done ? "todo-done" : "" }),
        todo.due_at && h("span", { text: `Due ${new Date(todo.due_at).toLocaleString()}`, class: new Date(todo.due_at) < new Date() && !done ? "error-text" : "" }),
        todo.details && h("span", { text: todo.details })),
      h("button", { class: "btn", type: "button", text: done ? "Reopen" : "Complete", "aria-label": `${done ? "Reopen" : "Complete"} to-do ${todo.id}`, onClick: async () => {
        try { await api(`/todos/${todo.id}`, { method: "PATCH", body: { status: done ? "pending" : "completed" } }); await load(); }
        catch (error) { toast(error.message, "error"); }
      } }),
    );
  }
  function planRow(plan) {
    const stepRows = plan.steps.map((step) => {
      const done = step.status === "completed";
      return h("div", { class: "row" },
        h("span", { text: `${done ? "✓" : "○"} ${step.position}. ${step.title}`, class: done ? "todo-done" : "" }),
        h("button", {
          class: "btn", type: "button", text: done ? "Reopen" : "Complete",
          "aria-label": `${done ? "Reopen" : "Complete"} plan step ${step.position}`,
          onClick: async () => {
            try {
              await api(`/plans/${plan.id}/steps/${step.position}`, { method: "PATCH", body: { status: done ? "pending" : "completed" } });
              await loadPlans();
            } catch (error) { toast(error.message, "error"); }
          },
        }),
      );
    });
    const planAction = plan.status === "cancelled"
      ? h("button", {
        class: "btn", type: "button", text: "Reopen", "aria-label": `Reopen plan ${plan.id}`,
        onClick: async () => {
          try { await api(`/plans/${plan.id}`, { method: "PATCH", body: { status: "active" } }); await loadPlans(); }
          catch (error) { toast(error.message, "error"); }
        },
      })
      : plan.status === "active"
        ? h("button", {
          class: "btn", type: "button", text: "Cancel", "aria-label": `Cancel plan ${plan.id}`,
          onClick: async () => {
            try { await api(`/plans/${plan.id}`, { method: "PATCH", body: { status: "cancelled" } }); await loadPlans(); }
            catch (error) { toast(error.message, "error"); }
          },
        })
        : null;
    return h("div", { class: "row plan-row" },
      h("div", { class: "row-text" },
        h("strong", { text: plan.title, class: plan.status === "completed" ? "todo-done" : "" }),
        h("span", { text: `${plan.status[0].toUpperCase()}${plan.status.slice(1)} plan` }),
        ...stepRows,
      ),
      planAction,
    );
  }
  page.replaceChildren(
    h("header", { class: "page-head" }, h("h1", { text: "To-dos" }), h("p", { class: "page-subtitle", text: "A durable list JARVIS can manage for you." })),
    section("Add a to-do", "Ask JARVIS in chat, or add one here.", h("div", { class: "form-stack" }, title, details, due, h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "button", text: "Add to-do", onClick: add }), problem))),
    section("Your to-dos", "Completed items stay here until you reopen them.", list),
    section("Plans", "Break larger work into steps that survive restarts.", h("div", { class: "form-stack" },
      planTitle, planSteps,
      h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "button", text: "Create plan", onClick: addPlan }), planProblem),
      plans,
    )),
  );
  await load();
  await loadPlans();
}
