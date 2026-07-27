import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { readFile, writeFile } from "node:fs/promises";
import { executeRun } from "../src/orchestrator.js";
import { readJson, writeJson } from "../src/io.js";
import {
  ROOT,
  OPTIONS,
  evidenceArtifact,
  evidenceRecord,
  findings,
  instance,
  taskEpisode,
  tempSetup
} from "./helpers.js";

function sourceFromRecords(records) {
  const conversationIds = [...new Set(records.map((record) => record.conversation_id))];
  return {
    schema_version: "1.0.0",
    project_id: "test-project",
    window_start: OPTIONS.windowStart,
    window_end: OPTIONS.windowEnd,
    conversations: conversationIds.map((conversationId) => ({
      conversation_id: conversationId,
      project_id: "test-project",
      binding_method: "explicit_conversation_id",
      has_events_before_window: false,
      has_events_after_window: false,
      records: records
        .filter((record) => record.conversation_id === conversationId)
        .map((record) => ({
          conversation_id: record.conversation_id,
          timestamp: record.timestamp,
          actor: record.actor,
          sequence: record.sequence,
          event_type: record.event_type,
          call_id: record.call_id,
          source_location: record.source_location,
          content_or_reference: record.content_or_reference,
          collection_status: record.collection_status,
          content_hash: record.content_hash
        }))
    }))
  };
}

function scenario(runId, count = 3) {
  const records = Array.from({ length: count }, (_, n) =>
    evidenceRecord(`ev_${n}`, `conv-${n}`, `2026-07-24T0${n + 1}:00:00Z`, `rejected ${n}`, { sequence: 0 }));
  const tasks = records.map((record, n) =>
    taskEpisode(String(n), record.conversation_id, [record.evidence_id], { startSequence: 0 }));
  const instances = tasks.map((task, n) =>
    instance(String(n), task, records[n].timestamp, [records[n].evidence_id]));
  return {
    records,
    evidence: evidenceArtifact(runId, records),
    findings: findings(runId, tasks, instances)
  };
}

function emptySource() {
  return {
    schema_version: "1.0.0",
    project_id: "test-project",
    window_start: OPTIONS.windowStart,
    window_end: OPTIONS.windowEnd,
    conversations: []
  };
}

function emptyRunner() {
  return async ({ stage, outputFile, inputFiles }) => {
    const run = await readJson(inputFiles.run);
    if (stage === "collector") {
      await writeJson(outputFile, evidenceArtifact(run.run_id, []));
    } else if (stage === "analyst") {
      await writeJson(outputFile, findings(run.run_id, []));
    } else {
      throw new Error("Optimizer must be skipped.");
    }
  };
}

function scenarioRunner(setup, {
  noSupportedTarget = false,
  selectTarget = (targets) => targets[0],
  mutateTarget = null
} = {}) {
  return async ({ stage, outputFile, inputFiles }) => {
    const run = await readJson(inputFiles.run);
    const data = scenario(run.run_id);
    if (stage === "collector") return writeJson(outputFile, data.evidence);
    if (stage === "analyst") return writeJson(outputFile, data.findings);

    const cluster = data.findings.issue_clusters[0];
    const target = selectTarget(run.parameters.improvement_targets);
    const proposal = noSupportedTarget ? null : {
      proposal_id: "pr_result",
      issue_cluster_id: cluster.issue_cluster_id,
      instance_count: cluster.instance_count,
      problem_instance_ids: cluster.problem_instance_ids,
      evidence_ids: cluster.evidence_ids,
      root_cause: cluster.root_cause,
      target_id: target.id,
      target_file: target.proposalPath ?? target.path,
      target_location: "Task completion contract",
      minimal_change: "Require evidence-backed acceptance before declaring completion.",
      behavior_before: "Completion is declared before acceptance.",
      behavior_after: "Completion is declared only with acceptance evidence.",
      expected_metric_effects: [
        { metric: "attainment_rate", direction: "increase" },
        { metric: "rework_count", direction: "decrease" }
      ],
      side_effects: [],
      scope_expansion_risk: "low",
      regression_tests: [
        { test_id: "original", kind: "original_failure", given: "Rejected result", when: "Reviewed", then: "Not achieved is recorded" },
        { test_id: "adjacent", kind: "adjacent_case", given: "Accepted result", when: "Reviewed", then: "Achieved is recorded" }
      ]
    };
    await writeJson(outputFile, {
      schema_version: "1.0.0",
      contract_revision: run.parameters.contract_revision,
      contract_bundle_hash: run.parameters.contract_bundle_hash,
      run_id: run.run_id,
      project_id: "test-project",
      improvement_target_ids: run.parameters.improvement_target_ids,
      proposals: proposal ? [proposal] : [],
      dispositions: [{
        issue_cluster_id: cluster.issue_cluster_id,
        status: proposal ? "proposed" : "no_supported_target",
        proposal_ids: proposal ? [proposal.proposal_id] : [],
        reason: proposal ? "Allowed target contains the responsible rule." : "No allowed target contains the responsible rule."
      }]
    });
    if (mutateTarget) await mutateTarget();
  };
}

test("empty window produces metrics and an insufficient trend without optimizer", async () => {
  const setup = await tempSetup();
  const calls = [];
  const runner = emptyRunner();
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile,
    targetSkill: setup.target
  }, {
    sourceLoader: async () => emptySource(),
    agentRunner: async (args) => {
      calls.push(args.stage);
      return runner(args);
    }
  });
  assert.equal(run.status, "COMPLETED_NO_TASKS");
  assert.deepEqual(calls, ["collector", "analyst"]);
  assert.equal(run.stages.metrics.status, "succeeded");
  assert.equal(run.stages.trend.status, "succeeded");
  assert.equal((await readJson(path.join(setup.runsDir, run.run_id, "metrics.json"))).task_counts.total, 0);
  assert.equal((await readJson(path.join(setup.runsDir, run.run_id, "trend.json"))).status, "insufficient_data");
});

test("three matching task episodes launch optimizer and produce a proposal", async () => {
  const setup = await tempSetup();
  const first = scenario("placeholder");
  const calls = [];
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile,
    targetSkill: setup.target
  }, {
    sourceLoader: async () => sourceFromRecords(first.records),
    agentRunner: async (args) => {
      calls.push(args.stage);
      return scenarioRunner(setup)(args);
    }
  });
  assert.equal(run.status, "COMPLETED_WITH_PROPOSAL");
  assert.deepEqual(calls, ["collector", "analyst", "optimizer"]);
  assert.match(await readFile(path.join(setup.runsDir, run.run_id, "report.md"), "utf8"), /目标达成率/);
  assert.match(await readFile(path.join(setup.runsDir, run.run_id, "report.md"), "utf8"), /未修改任何改进载体/);
});

test("eligible findings without targets still produce metrics and findings", async () => {
  const setup = await tempSetup({ useLegacyTargets: false });
  const first = scenario("placeholder");
  const calls = [];
  const runner = scenarioRunner(setup);
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile
  }, {
    sourceLoader: async () => sourceFromRecords(first.records),
    agentRunner: async (args) => {
      calls.push(args.stage);
      if (args.stage === "optimizer") throw new Error("Optimizer must be skipped.");
      return runner(args);
    }
  });
  assert.equal(run.status, "COMPLETED_WITH_FINDINGS");
  assert.deepEqual(calls, ["collector", "analyst"]);
  assert.equal((await readJson(path.join(setup.runsDir, run.run_id, "metrics.json"))).task_counts.total, 3);
});

test("no supported target is a structured findings result, not a failed run", async () => {
  const setup = await tempSetup();
  const first = scenario("placeholder");
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile,
    targetSkill: setup.target
  }, {
    sourceLoader: async () => sourceFromRecords(first.records),
    agentRunner: scenarioRunner(setup, { noSupportedTarget: true })
  });
  assert.equal(run.status, "COMPLETED_WITH_FINDINGS");
  const proposal = await readJson(path.join(setup.runsDir, run.run_id, "proposal.json"));
  assert.deepEqual(proposal.proposals, []);
  assert.equal(proposal.dispositions[0].status, "no_supported_target");
});

test("project binding limits which configured target files are exposed", async () => {
  const setup = await tempSetup({ useLegacyTargets: false });
  const config = await readJson(setup.configFile);
  config.improvement_targets = [
    { id: "project-skill", type: "skill", path: setup.target },
    { id: "project-agents", type: "agents", path: setup.agents }
  ];
  config.project_bindings[0].improvement_target_ids = ["project-agents"];
  config.project_bindings.push({
    project_id: "other-project",
    roots: [],
    conversation_ids: [],
    improvement_target_ids: ["project-skill"]
  });
  await writeJson(setup.configFile, config);
  const first = scenario("placeholder");
  const seenInputs = [];
  const runner = scenarioRunner(setup);
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile
  }, {
    sourceLoader: async () => sourceFromRecords(first.records),
    agentRunner: async (args) => {
      if (args.stage === "optimizer") seenInputs.push(...Object.keys(args.inputFiles));
      return runner(args);
    }
  });
  assert.deepEqual(run.parameters.improvement_target_ids, ["project-agents"]);
  assert(seenInputs.some((name) => name.includes("project-agents")));
  assert(!seenInputs.some((name) => name.includes("project-skill")));
});

test("proposal target file must exactly match the allowed target", async () => {
  const setup = await tempSetup({ useLegacyTargets: false });
  const config = await readJson(setup.configFile);
  config.improvement_targets = [
    { id: "project-skill", type: "skill", path: setup.target },
    { id: "project-agents", type: "agents", path: setup.agents }
  ];
  config.project_bindings[0].improvement_target_ids = ["project-agents"];
  await writeJson(setup.configFile, config);
  const first = scenario("placeholder");
  const runner = scenarioRunner(setup, {
    selectTarget: (targets) => ({ ...targets[0], proposalPath: setup.target })
  });
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile
  }, { sourceLoader: async () => sourceFromRecords(first.records), agentRunner: runner });
  assert.equal(run.status, "FAILED_PROPOSAL_VALIDATION");
  assert.match(run.failure.message, /TARGET_FILE_MISMATCH/);
});

test("optimizer mutation of any configured target fails the run", async () => {
  const setup = await tempSetup({ useLegacyTargets: false });
  const config = await readJson(setup.configFile);
  config.improvement_targets = [
    { id: "project-skill", type: "skill", path: setup.target },
    { id: "project-agents", type: "agents", path: setup.agents }
  ];
  config.project_bindings[0].improvement_target_ids = ["project-skill", "project-agents"];
  await writeJson(setup.configFile, config);
  const first = scenario("placeholder");
  const runner = scenarioRunner(setup, {
    mutateTarget: async () => writeFile(setup.agents, "# Mutated instructions\n", "utf8")
  });
  const run = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile
  }, { sourceLoader: async () => sourceFromRecords(first.records), agentRunner: runner });
  assert.equal(run.status, "FAILED_OPTIMIZATION");
  assert.match(run.failure.message, /IMPROVEMENT_TARGET_MUTATED/);
});

for (const failureStage of ["collector", "analyst", "optimizer"]) {
  test(`${failureStage} failure prevents downstream agent execution`, async () => {
    const setup = await tempSetup();
    const data = scenario("placeholder");
    const calls = [];
    const base = scenarioRunner(setup);
    const run = await executeRun({
      ...OPTIONS,
      rootDir: ROOT,
      configFile: setup.configFile,
      targetSkill: setup.target
    }, {
      sourceLoader: async () => failureStage === "collector" ? emptySource() : sourceFromRecords(data.records),
      agentRunner: async (args) => {
        calls.push(args.stage);
        if (args.stage === failureStage) throw new Error(`${failureStage} exploded`);
        return base(args);
      }
    });
    assert.equal(
      run.status,
      `FAILED_${failureStage === "collector" ? "COLLECTION" : failureStage === "analyst" ? "ANALYSIS" : "OPTIMIZATION"}`
    );
    assert.equal(calls.at(-1), failureStage);
  });
}

test("failed run retries with the same run id and archives the previous attempt", async () => {
  const setup = await tempSetup();
  const first = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile,
    targetSkill: setup.target
  }, {
    sourceLoader: async () => emptySource(),
    agentRunner: async () => { throw new Error("first failure"); }
  });
  assert.equal(first.status, "FAILED_COLLECTION");
  const second = await executeRun({
    ...OPTIONS,
    rootDir: ROOT,
    configFile: setup.configFile,
    targetSkill: setup.target,
    runId: first.run_id
  }, { sourceLoader: async () => emptySource(), agentRunner: emptyRunner() });
  assert.equal(second.status, "COMPLETED_NO_TASKS");
  assert.equal(second.attempt, 2);
  const archived = await readJson(path.join(setup.runsDir, first.run_id, "attempts", "1", "run.json"));
  assert.equal(archived.status, "FAILED_COLLECTION");
});
