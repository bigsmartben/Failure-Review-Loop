import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

export async function readJson(file) {
  return JSON.parse(await readFile(file, "utf8"));
}

export async function writeJson(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await writeFile(temp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await rename(temp, file);
}

export async function writeText(file, value) {
  await mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await writeFile(temp, value, "utf8");
  await rename(temp, file);
}

export function utcNow() {
  return new Date().toISOString();
}

export function resolveFrom(base, value) {
  return path.isAbsolute(value) ? path.normalize(value) : path.resolve(base, value);
}
