#!/usr/bin/env node
import { readFile, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const DEFAULT_MARKER_FILE = "failure-review.project.json";
const PROJECT_ID_PATTERN = /^[a-z0-9][a-z0-9_-]{0,62}$/;

function pathKey(value) {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function portablePath(value) {
  return value.replaceAll("\\", "/");
}

export function parseProjectArgs(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    if (!["--project-id", "--project-root", "--config"].includes(name)) {
      throw new Error(`ARGUMENT_UNKNOWN: ${name}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`ARGUMENT_VALUE_REQUIRED: ${name}`);
    }
    values[name.slice(2).replaceAll("-", "_")] = value;
    index += 1;
  }
  if (!values.project_id) {
    throw new Error("PROJECT_ID_REQUIRED: pass --project-id <id>.");
  }
  if (!values.project_root) {
    throw new Error("PROJECT_ROOT_REQUIRED: pass --project-root <path>.");
  }
  return values;
}

export function addProjectBinding(config, {
  configDir,
  projectId,
  projectRoot
}) {
  if (!PROJECT_ID_PATTERN.test(projectId)) {
    throw new Error(
      "PROJECT_ID_INVALID: use 1-63 lowercase letters, digits, underscores, or hyphens."
    );
  }
  if (!Array.isArray(config.project_bindings)) {
    throw new Error("PROJECT_BINDINGS_INVALID: project_bindings must be an array.");
  }

  const resolvedRoot = path.resolve(projectRoot);
  const rootKey = pathKey(resolvedRoot);
  for (const binding of config.project_bindings) {
    if (!Array.isArray(binding.roots)) {
      throw new Error(`PROJECT_BINDING_ROOTS_INVALID: ${binding.project_id ?? "<unknown>"}.`);
    }
    const ownsRoot = binding.roots.some(
      (configuredRoot) => pathKey(path.resolve(configDir, configuredRoot)) === rootKey
    );
    if (ownsRoot && binding.project_id !== projectId) {
      throw new Error(
        `PROJECT_ROOT_CONFLICT: ${resolvedRoot} is already bound to ${binding.project_id}.`
      );
    }
  }

  const existingIndex = config.project_bindings.findIndex(
    (binding) => binding.project_id === projectId
  );
  if (existingIndex >= 0) {
    const existing = config.project_bindings[existingIndex];
    const alreadyBound = existing.roots.some(
      (configuredRoot) => pathKey(path.resolve(configDir, configuredRoot)) === rootKey
    );
    if (alreadyBound) {
      return {
        config,
        binding: existing,
        changed: false,
        resolvedRoot
      };
    }
    const binding = {
      ...existing,
      roots: [...existing.roots, portablePath(resolvedRoot)]
    };
    const bindings = [...config.project_bindings];
    bindings[existingIndex] = binding;
    return {
      config: { ...config, project_bindings: bindings },
      binding,
      changed: true,
      resolvedRoot
    };
  }

  const binding = {
    project_id: projectId,
    roots: [portablePath(resolvedRoot)],
    marker_file: DEFAULT_MARKER_FILE,
    conversation_ids: [],
    improvement_target_ids: []
  };
  return {
    config: {
      ...config,
      project_bindings: [...config.project_bindings, binding]
    },
    binding,
    changed: true,
    resolvedRoot
  };
}

async function readMarker(markerPath) {
  try {
    return JSON.parse(await readFile(markerPath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

export async function configureProject({
  configFile = path.join(rootDir, "failure-review.config.json"),
  projectId,
  projectRoot
}) {
  let rootStat;
  try {
    rootStat = await stat(projectRoot);
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(`PROJECT_ROOT_NOT_FOUND: ${path.resolve(projectRoot)}.`);
    }
    throw error;
  }
  if (!rootStat.isDirectory()) {
    throw new Error(`PROJECT_ROOT_NOT_DIRECTORY: ${path.resolve(projectRoot)}.`);
  }

  let config;
  try {
    config = JSON.parse(await readFile(configFile, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error("CONFIG_NOT_INITIALIZED: run npm run init:product first.");
    }
    throw error;
  }

  const result = addProjectBinding(config, {
    configDir: path.dirname(configFile),
    projectId,
    projectRoot
  });
  const markerFile = result.binding.marker_file ?? DEFAULT_MARKER_FILE;
  const markerPath = path.join(result.resolvedRoot, markerFile);
  const existingMarker = await readMarker(markerPath);
  if (existingMarker && existingMarker.project_id !== projectId) {
    throw new Error(
      `PROJECT_MARKER_CONFLICT: ${markerPath} declares ${existingMarker.project_id ?? "<missing>"}.`
    );
  }

  let markerCreated = false;
  if (!existingMarker) {
    await writeFile(
      markerPath,
      `${JSON.stringify({ schema_version: "1.0.0", project_id: projectId }, null, 2)}\n`,
      { encoding: "utf8", flag: "wx" }
    );
    markerCreated = true;
  }
  if (result.changed) {
    await writeFile(configFile, `${JSON.stringify(result.config, null, 2)}\n`, "utf8");
  }

  return {
    bindingChanged: result.changed,
    markerCreated,
    configFile,
    markerPath,
    projectId,
    projectRoot: result.resolvedRoot
  };
}

async function main() {
  const args = parseProjectArgs(process.argv.slice(2));
  const result = await configureProject({
    configFile: args.config ? path.resolve(args.config) : undefined,
    projectId: args.project_id,
    projectRoot: path.resolve(args.project_root)
  });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

const isMain = process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isMain) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
