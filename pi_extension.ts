// Pi extension for Agent Park: tells the screensaver what a session is doing.
//
// Pi has no command hooks, so this extension turns its agent events into the
// Claude-style hook events agent_hook.py understands and pipes them to
// `python3 agent_hook.py pi`. Install by linking it into the extension folder:
//   ln -s "$PWD/pi_extension.ts" ~/.pi/agent/extensions/agent-park.ts
import { spawn } from "node:child_process"
import { realpathSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

// Resolve the link so the hook is found next to the real file.
const HOOK = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "agent_hook.py")

// One hook at a time, so a quick start -> end never lands out of order.
let queue = Promise.resolve()
function send(hook_event_name: string, ctx?: any) {
  const model = ctx?.model?.id
  queue = queue.then(() => new Promise<void>((done) => {
    try {
      const child = spawn("python3", [HOOK, "pi"], { stdio: ["pipe", "ignore", "ignore"] })
      child.on("error", () => done())
      child.on("close", () => done())
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify(model ? { hook_event_name, model } : { hook_event_name }))
    } catch {
      done()  // a screensaver must never break the agent's turn
    }
  }))
}

export default function (pi: any) {
  pi.on("session_start", async (_event: any, ctx: any) => send("SessionStart", ctx))
  // Once per prompt; agent_end also comes when you press Esc.
  pi.on("agent_start", async (_event: any, ctx: any) => send("UserPromptSubmit", ctx))
  pi.on("agent_end", async (_event: any, ctx: any) => send("Stop", ctx))
  // /model or Ctrl+P: the animal's label follows without changing what it does.
  pi.on("model_select", async (event: any) => send("ModelSelect", { model: event?.model }))
  // /new, /resume and /fork shut a session down and start the next at once.
  pi.on("session_shutdown", async (event: any) => send(event?.reason === "quit" ? "SessionEnd" : "Stop"))
}
