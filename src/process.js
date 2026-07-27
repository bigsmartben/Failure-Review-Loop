import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

function codexNodeEntrypoint() {
  for (const dir of (process.env.PATH ?? "").split(path.delimiter)) {
    if (!dir) continue;
    const shim = path.join(dir, "codex.cmd");
    if (!existsSync(shim)) continue;
    const candidates = [
      path.resolve(dir, "..", "@openai", "codex", "bin", "codex.js"),
      path.join(dir, "node_modules", "@openai", "codex", "bin", "codex.js")
    ];
    const entrypoint = candidates.find(existsSync);
    if (entrypoint) return entrypoint;
  }
  return null;
}

export function spawnCommand(command, args, options = {}) {
  if (process.platform === "win32" && command === "codex") {
    const entrypoint = codexNodeEntrypoint();
    if (entrypoint) return spawn(process.execPath, [entrypoint, ...args], { ...options, shell: false });
  }
  return spawn(command, args, { ...options, shell: false });
}

export async function captureCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawnCommand(command, args, { ...options, stdio: ["ignore", "pipe", "pipe"] });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", reject);
    child.on("close", (code) => {
      const result = {
        code,
        stdout: Buffer.concat(stdout).toString("utf8"),
        stderr: Buffer.concat(stderr).toString("utf8")
      };
      if (code === 0) resolve(result);
      else reject(Object.assign(new Error(`${command} exited with ${code}: ${result.stderr}`), result));
    });
  });
}
