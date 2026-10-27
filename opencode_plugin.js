// OpenCode plugin for Agent Park: tells the screensaver what a session is doing.
//
// OpenCode has no command hooks, so this plugin turns its session events into
// the Claude-style hook events agent_hook.py understands and pipes them to
// `python3 agent_hook.py opencode`. Install by linking it into the plugin folder:
//   ln -s "$PWD/opencode_plugin.js" ~/.config/opencode/plugins/agent-park.js
import { spawn } from "node:child_process"
import { realpathSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

// Resolve the link so the hook is found next to the real file.
const HOOK = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "agent_hook.py")
// What the cat should do -> the hook event agent_hook.py maps to it.
const HOOK_EVENTS = { work: "UserPromptSubmit", wait: "PermissionRequest", idle: "Stop" }

// One hook at a time, so a quick busy -> idle never lands out of order.
let queue = Promise.resolve()
function send(event) {
  queue = queue.then(() => new Promise((done) => {
    try {
      const child = spawn("python3", [HOOK, "opencode"], { stdio: ["pipe", "ignore", "ignore"] })
      child.on("error", done)
      child.on("close", done)
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify(event))
    } catch {
      done()  // a screensaver must never break the agent's turn
    }
  }))
  return queue
}

// The task tool titles a subagent session "<description> (@explore subagent)".
export function subagentType(title) {
  return /@([\w-]+) subagent/.exec(title || "")?.[1] || "subagent"
}

// OpenCode 1.x puts an event's payload in `properties`, 2.x in `data`.
export function createTracker(emit) {
  const status = new Map()  // main session id -> "work" | "wait" | "idle"
  const children = new Map()  // subagent session id -> { parent, type, running }

  // Each session reports on its own: under `opencode serve` one process runs
  // every window, and agent_hook.py files the states per session.
  function update(session, state) {
    if (!session || status.get(session) === state) return
    status.set(session, state)
    emit({ hook_event_name: HOOK_EVENTS[state], session_id: session })
  }

  function child(session, running) {
    const info = children.get(session)
    if (!info || info.running === running) return
    info.running = running
    emit({ hook_event_name: running ? "SubagentStart" : "SubagentStop", session_id: info.parent,
           agent_id: session, agent_type: info.type })
  }

  function busy(session, running) {
    if (children.has(session)) child(session, running)
    else update(session, running ? "work" : "idle")
  }

  // A subagent asking still needs you; its parent's animal shows it.
  const main = (session) => children.get(session)?.parent || session

  return async ({ event }) => {
    const data = event.data || event.properties || {}
    const info = data.info || data  // 1.x wraps sessions in `info`
    const session = data.sessionID || data.form?.sessionID
    switch (event.type) {
      case "session.created":
      case "session.updated": {
        const id = info.id || info.sessionID
        if (info.parentID && !children.has(id)) {
          children.set(id, { parent: info.parentID, type: info.agent || subagentType(info.title), running: false })
        }
        break
      }
      case "session.deleted": {
        const id = info.id || info.sessionID
        child(id, false)
        children.delete(id)
        status.delete(id)
        break
      }
      case "session.execution.started":
        busy(session, true)
        break
      case "session.execution.succeeded":
      case "session.execution.failed":
      case "session.execution.interrupted":
      case "session.idle":
        busy(session, false)
        break
      case "session.status":
        busy(session, data.status?.type !== "idle")
        break
      case "permission.asked":
      case "permission.updated":
      case "question.asked":
      case "form.created":
        update(main(session), "wait")
        break
      case "permission.replied":
      case "question.replied":
      case "question.rejected":
      case "form.replied":
      case "form.cancelled":
        // Even after a "no" the turn goes on until its execution event ends it.
        if (status.get(main(session)) === "wait") update(main(session), "work")
        break
    }
  }
}

export default {
  id: "agent-park",
  // OpenCode 2.x: events arrive as a stream; read it without holding up setup.
  setup: async (context) => {
    const stream = context.event?.subscribe?.()
    if (!stream) return
    const event = createTracker(send);
    (async () => {
      try {
        for await (const item of stream) await event({ event: item })
      } catch {}
    })()
  },
  // OpenCode 1.x: an event hook.
  server: async () => ({
    event: createTracker(send),
    dispose: () => send({ hook_event_name: "SessionEnd" }),
  }),
}
