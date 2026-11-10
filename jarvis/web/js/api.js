// Talks to the JARVIS server. Every request carries the session token the server
// placed in this page, which is how the server knows the call is from its own interface.

const TOKEN = document.querySelector('meta[name="jarvis-token"]')?.content || "";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function detail(response) {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return data.detail.map((item) => item.msg).join("; ");
  } catch {
    /* not JSON */
  }
  return `Request failed (HTTP ${response.status}).`;
}

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = { "X-Jarvis-Token": TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(`/api${path}`, { method, headers, signal, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("Can't reach JARVIS. Is it still running?", 0);
  }
  if (!response.ok) throw new ApiError(await detail(response), response.status);
  return response;
}

export async function api(path, options) {
  const response = await request(path, options);
  if (response.status === 204) return null;
  return (response.headers.get("content-type") || "").includes("json") ? response.json() : response.text();
}

/** Send a chat request and yield the server's events as they arrive. */
export async function* streamChat(body, signal) {
  const response = await request("/chat", { method: "POST", body, signal });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const data = block.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart());
      if (!data.length) continue;
      try {
        yield JSON.parse(data.join("\n"));
      } catch {
        /* ignore a malformed event */
      }
    }
  }
}
