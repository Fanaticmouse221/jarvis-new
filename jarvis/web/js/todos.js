import { api } from "./api.js";
import { h, section, toast } from "./util.js";

export async function renderTodos(page) {
  const list = h("div", { class: "rows" });
  const title = h("input", { class: "input", maxlength: 500, placeholder: "What needs doing?", "aria-label": "To-do title" });
  const details = h("input", { class: "input", maxlength: 2000, placeholder: "Optional details", "aria-label": "To-do details" });
  const problem = h("span", { class: "hint" });
  const add = async () => {
    try {
      await api("/todos", { method: "POST", body: { title: title.value, details: details.value } });
      title.value = "";
      details.value = "";
      problem.textContent = "";
      await load();
    } catch (error) {
      problem.textContent = error.message;
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
  function todoRow(todo) {
    const done = todo.status === "completed";
    return h("div", { class: "row" },
      h("div", { class: "row-text" }, h("strong", { text: todo.title, class: done ? "todo-done" : "" }), todo.details && h("span", { text: todo.details })),
      h("button", { class: "btn", type: "button", text: done ? "Reopen" : "Complete", "aria-label": `${done ? "Reopen" : "Complete"} to-do ${todo.id}`, onClick: async () => {
        try { await api(`/todos/${todo.id}`, { method: "PATCH", body: { status: done ? "pending" : "completed" } }); await load(); }
        catch (error) { toast(error.message, "error"); }
      } }),
    );
  }
  page.replaceChildren(
    h("header", { class: "page-head" }, h("h1", { text: "To-dos" }), h("p", { class: "page-subtitle", text: "A durable list JARVIS can manage for you." })),
    section("Add a to-do", "Ask JARVIS in chat, or add one here.", h("div", { class: "form-stack" }, title, details, h("div", { class: "form-actions" }, h("button", { class: "btn primary", type: "button", text: "Add to-do", onClick: add }), problem))),
    section("Your to-dos", "Completed items stay here until you reopen them.", list),
  );
  await load();
}
