import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { configureProject } from "../src/configure-project.js";

async function fixture() {
  const temp = await mkdtemp(path.join(os.tmpdir(), "failure-configure-test-"));
  const runner = path.join(temp, "runner");
  const target = path.join(temp, "target");
  await mkdir(runner);
  await mkdir(target);
  const configFile = path.join(runner, "failure-review.config.json");
  const config = {
    schema_version: "1.0.0",
    project_bindings: [{
      project_id: "failure-review-loop",
      roots: ["."],
      marker_file: "failure-review.project.json",
      conversation_ids: [],
      improvement_target_ids: []
    }],
    improvement_targets: []
  };
  await writeFile(configFile, JSON.stringify(config), "utf8");
  return { config, configFile, target };
}

test("project registration appends a binding and creates its marker", async () => {
  const { configFile, target } = await fixture();

  const result = await configureProject({
    configFile,
    projectId: "pre-sdd",
    projectRoot: target
  });
  const config = JSON.parse(await readFile(configFile, "utf8"));
  const marker = JSON.parse(
    await readFile(path.join(target, "failure-review.project.json"), "utf8")
  );

  assert.equal(result.bindingChanged, true);
  assert.equal(result.markerCreated, true);
  assert.equal(config.project_bindings[0].project_id, "failure-review-loop");
  assert.equal(config.project_bindings[1].project_id, "pre-sdd");
  assert.deepEqual(config.project_bindings[1].improvement_target_ids, []);
  assert.equal(marker.project_id, "pre-sdd");
});

test("project registration is idempotent", async () => {
  const { configFile, target } = await fixture();
  await configureProject({ configFile, projectId: "pre-sdd", projectRoot: target });

  const result = await configureProject({
    configFile,
    projectId: "pre-sdd",
    projectRoot: target
  });
  const config = JSON.parse(await readFile(configFile, "utf8"));

  assert.equal(result.bindingChanged, false);
  assert.equal(result.markerCreated, false);
  assert.equal(
    config.project_bindings.filter((binding) => binding.project_id === "pre-sdd").length,
    1
  );
});

test("project registration rejects a root owned by another project", async () => {
  const { config, configFile, target } = await fixture();
  config.project_bindings.push({
    project_id: "other-project",
    roots: [target],
    marker_file: "failure-review.project.json",
    conversation_ids: [],
    improvement_target_ids: []
  });
  await writeFile(configFile, JSON.stringify(config), "utf8");

  await assert.rejects(
    configureProject({ configFile, projectId: "pre-sdd", projectRoot: target }),
    /PROJECT_ROOT_CONFLICT/
  );
});

test("project registration rejects a conflicting marker", async () => {
  const { configFile, target } = await fixture();
  await writeFile(
    path.join(target, "failure-review.project.json"),
    JSON.stringify({ schema_version: "1.0.0", project_id: "other-project" }),
    "utf8"
  );

  await assert.rejects(
    configureProject({ configFile, projectId: "pre-sdd", projectRoot: target }),
    /PROJECT_MARKER_CONFLICT/
  );
  const config = JSON.parse(await readFile(configFile, "utf8"));
  assert.equal(config.project_bindings.some((binding) => binding.project_id === "pre-sdd"), false);
});
