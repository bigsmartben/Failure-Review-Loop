import { cp, mkdir, readFile, rm, stat } from "node:fs/promises";
import { randomBytes } from "node:crypto";
import path from "node:path";
import { collectSourcePacket } from "./source.js";
import { runCodexStage } from "./agent-runner.js";
import { readJson, resolveFrom, utcNow, writeJson } from "./io.js";
import { validateArtifact } from "./validation.js";
import { writeReport } from "./report.js";
import { sha256, targetSetHash } from "./hash.js";
import { buildMetrics } from "./metrics.js";
import { buildTrend, collectBaselineMetrics } from "./trend.js";
import { CONTRACT_REVISION, contractBundleHash } from "./contract.js";

const STAGE_FILES = {
  collector: ["evidence", "evidence.json"],
  analyst: ["findings", "findings.json"],
  optimizer: ["proposal", "proposal.json"]
};

const IMPROVEMENT_TARGET_TYPES = new Set(["skill", "agents", "prompt", "script", "template"]);

function slug(value) {
  return value.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "").slice(0, 63);
}

function pathKey(value) {
  const resolved = path.resolve(value);
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

function normalizeImprovementTargets(config, configDir, projectId, selectedTargetSkill) {
  const hasNewTargets = Object.hasOwn(config, "improvement_targets");
  const configured = hasNewTargets
    ? config.improvement_targets
    : (config.target_skill_allowlist ?? []).map((targetPath) => {
        const resolved = resolveFrom(configDir, targetPath);
        return {
          id: `legacy-skill-${sha256(pathKey(resolved)).slice(0, 12)}`,
          type: "skill",
          path: resolved
        };
      });
  if (!Array.isArray(configured)) {
    throw new Error("IMPROVEMENT_TARGETS_INVALID: improvement_targets must be an array.");
  }

  const ids = new Set();
  const paths = new Set();
  const targets = configured.map((target, index) => {
    if (!target || typeof target !== "object" || Array.isArray(target)) {
      throw new Error(`IMPROVEMENT_TARGET_INVALID: improvement_targets[${index}] must be an object.`);
    }
    if (typeof target.id !== "string" || !/^[a-z0-9][a-z0-9_-]{0,62}$/.test(target.id)) {
      throw new Error(`IMPROVEMENT_TARGET_INVALID: improvement_targets[${index}].id is invalid.`);
    }
    if (!IMPROVEMENT_TARGET_TYPES.has(target.type)) {
      throw new Error(`IMPROVEMENT_TARGET_INVALID: improvement_targets[${index}].type is invalid.`);
    }
    if (typeof target.path !== "string" || !target.path.trim()) {
      throw new Error(`IMPROVEMENT_TARGET_INVALID: improvement_targets[${index}].path is required.`);
    }
    const normalized = { id: target.id, type: target.type, path: resolveFrom(configDir, target.path) };
    const normalizedPath = pathKey(normalized.path);
    if (ids.has(normalized.id)) {
      throw new Error(`IMPROVEMENT_TARGET_DUPLICATE_ID: ${normalized.id}`);
    }
    if (paths.has(normalizedPath)) {
      throw new Error(`IMPROVEMENT_TARGET_DUPLICATE_PATH: ${normalized.path}`);
    }
    ids.add(normalized.id);
    paths.add(normalizedPath);
    return normalized;
  });

  const binding = config.project_bindings.find((item) => item.project_id === projectId);
  if (!binding) throw new Error(`No project binding for ${projectId}.`);
  let projectTargets = targets;
  if (binding.improvement_target_ids !== undefined) {
    if (!Array.isArray(binding.improvement_target_ids)) {
      throw new Error("PROJECT_IMPROVEMENT_TARGETS_INVALID: improvement_target_ids must be an array.");
    }
    if (new Set(binding.improvement_target_ids).size !== binding.improvement_target_ids.length) {
      throw new Error("PROJECT_IMPROVEMENT_TARGETS_INVALID: improvement_target_ids must be unique.");
    }
    const requested = new Set(binding.improvement_target_ids);
    const unknown = [...requested].filter((id) => !ids.has(id));
    if (unknown.length) {
      throw new Error(`PROJECT_IMPROVEMENT_TARGET_UNKNOWN: ${unknown.join(", ")}`);
    }
    projectTargets = targets.filter((target) => requested.has(target.id));
  } else if (config.project_bindings.length > 1 && targets.length > 0) {
    throw new Error("PROJECT_IMPROVEMENT_TARGETS_REQUIRED: multi-project configs must bind improvement_target_ids per project.");
  }

  if (!selectedTargetSkill) return projectTargets;
  const selectedPath = pathKey(selectedTargetSkill);
  const selected = projectTargets.find((target) =>
    target.type === "skill" && pathKey(target.path) === selectedPath);
  if (!selected) {
    throw new Error("TARGET_SKILL_NOT_ALLOWED: target skill is not an allowed skill improvement target.");
  }
  return [selected];
}

async function validateImprovementTargets(targets) {
  for (const target of targets) {
    let targetStat;
    try {
      targetStat = await stat(target.path);
    } catch (error) {
      if (error.code === "ENOENT") {
        throw new Error(`IMPROVEMENT_TARGET_INVALID: ${target.id} does not exist.`);
      }
      throw error;
    }
    if (!targetStat.isFile()) {
      throw new Error(`IMPROVEMENT_TARGET_INVALID: ${target.id} must reference a file.`);
    }
  }
}

async function snapshotImprovementTargets(targets) {
  const snapshots = new Map();
  for (const target of targets) {
    snapshots.set(target.id, sha256(await readFile(target.path)));
  }
  return snapshots;
}

function improvementTargetManifest(runId, targets, snapshots) {
  const manifestTargets = targets.map((target) => ({
    ...target,
    content_hash: `sha256:${snapshots.get(target.id)}`
  }));
  return {
    schema_version: "1.0.0",
    run_id: runId,
    target_set_hash: targetSetHash(manifestTargets),
    targets: manifestTargets
  };
}

async function assertTargetsUnchanged(targets, snapshots) {
  for (const target of targets) {
    const after = sha256(await readFile(target.path));
    if (after !== snapshots.get(target.id)) {
      throw new Error(`IMPROVEMENT_TARGET_MUTATED: Optimizer changed ${target.id}.`);
    }
  }
}

export function createRunId(projectId, now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `${stamp}_${slug(projectId)}_${randomBytes(3).toString("hex")}`;
}

function emptyStage() {
  return { status: "pending", started_at: null, completed_at: null, artifact: null };
}

function newRun(runId, parameters) {
  const now = utcNow();
  return {
    schema_version: "1.0.0",
    run_id: runId,
    attempt: 1,
    status: "PENDING",
    parameters,
    created_at: now,
    updated_at: now,
    stages: {
      collector: emptyStage(),
      analyst: emptyStage(),
      metrics: emptyStage(),
      trend: emptyStage(),
      optimizer: emptyStage()
    },
    failure: null
  };
}

async function saveRun(file, run) {
  run.updated_at = utcNow();
  await writeJson(file, run);
}

async function archivePreviousAttempt(runDir, attempt) {
  const archive = path.join(runDir, "attempts", String(attempt));
  await mkdir(archive, { recursive: true });
  for (const name of ["run.json", "source-records.json", "evidence.json", "findings.json", "metrics.json", "trend.json", "improvement-targets.json", "optimizer-evidence.json", "proposal.json", "report.md"]) {
    try { await cp(path.join(runDir, name), path.join(archive, name)); } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

async function acquireLock(runsDir, projectId, runId) {
  const lock = path.join(runsDir, ".locks", `${slug(projectId)}.lock`);
  try {
    await mkdir(lock, { recursive: false });
  } catch (error) {
    if (error.code === "ENOENT") {
      await mkdir(path.dirname(lock), { recursive: true });
      await mkdir(lock);
    } else if (error.code === "EEXIST") {
      throw new Error(`OVERLAPPING_RUN: project ${projectId} already has an active lock.`);
    } else throw error;
  }
  await writeJson(path.join(lock, "owner.json"), { run_id: runId, acquired_at: utcNow() });
  return async () => rm(lock, { recursive: true });
}

function sameParameters(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

async function fail(runFile, reportFile, run, status, stage, code, error) {
  run.status = status;
  run.failure = { code, message: error.message, stage };
  if (stage !== "orchestrator") {
    run.stages[stage].status = "failed";
    run.stages[stage].completed_at = utcNow();
  }
  await saveRun(runFile, run);
  await writeReport(reportFile, run);
}

async function stageStart(runFile, run, stage, status) {
  run.status = status;
  run.stages[stage] = { status: "running", started_at: utcNow(), completed_at: null, artifact: null };
  await saveRun(runFile, run);
}

async function stageSuccess(runFile, run, stage, artifact) {
  run.stages[stage] = { ...run.stages[stage], status: "succeeded", completed_at: utcNow(), artifact };
  await saveRun(runFile, run);
}

export async function executeRun(options, dependencies = {}) {
  const rootDir = options.rootDir;
  const configFile = resolveFrom(rootDir, options.configFile);
  const configDir = path.dirname(configFile);
  const config = await readJson(configFile);
  const runsDir = resolveFrom(configDir, config.runs_dir);
  const lockedContractBundleHash = await contractBundleHash(rootDir);
  const improvementTargets = normalizeImprovementTargets(
    config,
    configDir,
    options.projectId,
    options.targetSkill ? path.resolve(options.targetSkill) : null
  );
  await validateImprovementTargets(improvementTargets);
  let targetSnapshots = await snapshotImprovementTargets(improvementTargets);
  const initialTargetManifest = improvementTargetManifest("pending", improvementTargets, targetSnapshots);
  const parameters = {
    project_id: options.projectId,
    window_start: new Date(options.windowStart).toISOString(),
    window_end: new Date(options.windowEnd).toISOString(),
    timezone: options.timezone,
    contract_revision: CONTRACT_REVISION,
    contract_bundle_hash: lockedContractBundleHash,
    improvement_target_ids: improvementTargets.map((target) => target.id),
    improvement_targets: improvementTargets,
    target_set_hash: initialTargetManifest.target_set_hash
  };
  const runId = options.runId ?? createRunId(options.projectId);
  const runDir = path.join(runsDir, runId);
  const runFile = path.join(runDir, "run.json");
  const reportFile = path.join(runDir, "report.md");
  await mkdir(runDir, { recursive: true });
  let run;
  try {
    run = await readJson(runFile);
    if (!options.runId) throw new Error(`RUN_ID_COLLISION: ${runId}`);
    if (!run.status.startsWith("FAILED_")) throw new Error("RETRY_NOT_ALLOWED: only failed runs can be retried.");
    if (!sameParameters(run.parameters, parameters)) throw new Error("RETRY_PARAMETER_MISMATCH: retries must keep the locked scope.");
    await archivePreviousAttempt(runDir, run.attempt);
    run.attempt += 1;
    run.status = "PENDING";
    run.failure = null;
    run.stages = {
      collector: emptyStage(),
      analyst: emptyStage(),
      metrics: emptyStage(),
      trend: emptyStage(),
      optimizer: emptyStage()
    };
  } catch (error) {
    if (error instanceof SyntaxError) throw error;
    if (error.code === "ENOENT") run = newRun(runId, parameters);
    else if (!run) run = newRun(runId, parameters);
    else throw error;
  }
  const runValidation = await validateArtifact("run", run, {}, rootDir);
  if (!runValidation.valid) {
    throw new Error(`RUN_CONTRACT_VALIDATION_FAILED: ${JSON.stringify(runValidation.errors)}`);
  }
  await saveRun(runFile, run);
  await writeJson(
    path.join(runDir, "improvement-targets.json"),
    improvementTargetManifest(run.run_id, improvementTargets, targetSnapshots)
  );
  const release = await acquireLock(runsDir, options.projectId, runId);
  const sourceLoader = dependencies.sourceLoader ?? collectSourcePacket;
  const agentRunner = dependencies.agentRunner ?? runCodexStage;

  try {
    let source;
    try {
      await stageStart(runFile, run, "collector", "COLLECTING");
      source = await sourceLoader({
        config, configDir, projectId: options.projectId,
        windowStart: parameters.window_start, windowEnd: parameters.window_end
      });
      await writeJson(path.join(runDir, "source-records.json"), source);
      const [kind, filename] = STAGE_FILES.collector;
      const artifactFile = path.join(runDir, filename);
      await agentRunner({
        stage: "collector", model: config.models.collector.model,
        reasoningEffort: config.models.collector.reasoning_effort,
        promptFile: path.join(rootDir, "prompts", "collector.md"),
        schemaFile: path.join(rootDir, "schemas", `${kind}.schema.json`),
        inputFiles: { run: runFile, source_records: path.join(runDir, "source-records.json") },
        outputFile: artifactFile,
        logFile: path.join(runDir, "logs", `collector.attempt-${run.attempt}.log`), rootDir
      });
      run.status = "VALIDATING_EVIDENCE";
      await saveRun(runFile, run);
      const evidence = await readJson(artifactFile);
      const result = await validateArtifact("evidence", evidence, { run, source }, rootDir);
      if (!result.valid) throw new Error(JSON.stringify(result.errors));
      await stageSuccess(runFile, run, "collector", filename);
    } catch (error) {
      const validation = run.status === "VALIDATING_EVIDENCE";
      await fail(runFile, reportFile, run, validation ? "FAILED_EVIDENCE_VALIDATION" : "FAILED_COLLECTION", "collector", validation ? "EVIDENCE_VALIDATION_FAILED" : "COLLECTION_FAILED", error);
      return run;
    }

    let findings;
    try {
      await stageStart(runFile, run, "analyst", "ANALYZING");
      const [kind, filename] = STAGE_FILES.analyst;
      const artifactFile = path.join(runDir, filename);
      await agentRunner({
        stage: "analyst", model: config.models.analyst.model,
        reasoningEffort: config.models.analyst.reasoning_effort,
        promptFile: path.join(rootDir, "prompts", "analyst.md"),
        schemaFile: path.join(rootDir, "schemas", `${kind}.schema.json`),
        inputFiles: {
          run: runFile,
          evidence: path.join(runDir, "evidence.json"),
          deduplication_contract: path.join(rootDir, "docs", "contracts", "deduplication.md"),
          contract_precedence: path.join(rootDir, "docs", "contracts", "precedence.md"),
          issue_signatures: path.join(rootDir, "docs", "contracts", "issue-signatures.json")
        },
        outputFile: artifactFile,
        logFile: path.join(runDir, "logs", `analyst.attempt-${run.attempt}.log`), rootDir
      });
      run.status = "VALIDATING_FINDINGS";
      await saveRun(runFile, run);
      findings = await readJson(artifactFile);
      const evidence = await readJson(path.join(runDir, "evidence.json"));
      const result = await validateArtifact("findings", findings, { run, evidence }, rootDir);
      if (!result.valid) throw new Error(JSON.stringify(result.errors));
      await stageSuccess(runFile, run, "analyst", filename);
    } catch (error) {
      const validation = run.status === "VALIDATING_FINDINGS";
      await fail(runFile, reportFile, run, validation ? "FAILED_FINDINGS_VALIDATION" : "FAILED_ANALYSIS", "analyst", validation ? "FINDINGS_VALIDATION_FAILED" : "ANALYSIS_FAILED", error);
      return run;
    }

    let metrics;
    try {
      await stageStart(runFile, run, "metrics", "COMPUTING_METRICS");
      metrics = buildMetrics({ run, findings, generatedAt: utcNow() });
      const result = await validateArtifact("metrics", metrics, { run, findings }, rootDir);
      if (!result.valid) throw new Error(JSON.stringify(result.errors));
      await writeJson(path.join(runDir, "metrics.json"), metrics);
      await stageSuccess(runFile, run, "metrics", "metrics.json");
    } catch (error) {
      await fail(runFile, reportFile, run, "FAILED_METRICS", "metrics", "METRICS_FAILED", error);
      return run;
    }

    let trend;
    try {
      await stageStart(runFile, run, "trend", "COMPUTING_TREND");
      const baselineMetrics = await collectBaselineMetrics({
        runsDir,
        currentRunId: run.run_id,
        projectId: run.parameters.project_id,
        improvementTargetIds: run.parameters.improvement_target_ids,
        contractRevision: run.parameters.contract_revision,
        contractBundleHash: run.parameters.contract_bundle_hash,
        before: metrics.generated_at,
        rootDir
      });
      trend = buildTrend({ run, metrics, baselineMetrics, generatedAt: utcNow() });
      const result = await validateArtifact("trend", trend, { run, metrics, baselineMetrics }, rootDir);
      if (!result.valid) throw new Error(JSON.stringify(result.errors));
      await writeJson(path.join(runDir, "trend.json"), trend);
      await stageSuccess(runFile, run, "trend", "trend.json");
    } catch (error) {
      await fail(runFile, reportFile, run, "FAILED_TREND", "trend", "TREND_FAILED", error);
      return run;
    }

    run.status = "CHECKING_THRESHOLD";
    await saveRun(runFile, run);
    if (findings.optimizer_eligible_cluster_ids.length === 0) {
      run.status = findings.task_episodes.length === 0 ? "COMPLETED_NO_TASKS" : "COMPLETED_WITH_METRICS";
      run.stages.optimizer.status = "skipped";
      await saveRun(runFile, run);
      await writeReport(reportFile, run, { findings, metrics, trend });
      return run;
    }
    if (improvementTargets.length === 0) {
      run.status = "COMPLETED_WITH_FINDINGS";
      run.stages.optimizer.status = "skipped";
      await saveRun(runFile, run);
      await writeReport(reportFile, run, { findings, metrics, trend });
      return run;
    }

    try {
      await stageStart(runFile, run, "optimizer", "OPTIMIZING");
      const [kind, filename] = STAGE_FILES.optimizer;
      const artifactFile = path.join(runDir, filename);
      const fullEvidence = await readJson(path.join(runDir, "evidence.json"));
      const eligible = new Set(findings.optimizer_eligible_cluster_ids);
      const necessaryIds = new Set(findings.issue_clusters
        .filter((cluster) => eligible.has(cluster.issue_cluster_id))
        .flatMap((cluster) => cluster.evidence_ids));
      const optimizerEvidenceFile = path.join(runDir, "optimizer-evidence.json");
      await writeJson(optimizerEvidenceFile, {
        ...fullEvidence,
        records: fullEvidence.records.filter((record) => necessaryIds.has(record.evidence_id))
      });
      targetSnapshots = await snapshotImprovementTargets(improvementTargets);
      const currentManifest = improvementTargetManifest(run.run_id, improvementTargets, targetSnapshots);
      if (currentManifest.target_set_hash !== run.parameters.target_set_hash) {
        throw new Error("IMPROVEMENT_TARGET_CHANGED: target content changed after the run scope was locked.");
      }
      await writeJson(path.join(runDir, "improvement-targets.json"), currentManifest);
      const optimizerInputs = {
        run: runFile,
        evidence: optimizerEvidenceFile,
        findings: path.join(runDir, "findings.json"),
        improvement_targets: path.join(runDir, "improvement-targets.json")
      };
      for (const [index, target] of improvementTargets.entries()) {
        optimizerInputs[`target_${index}_${target.id}`] = target.path;
      }
      await agentRunner({
        stage: "optimizer", model: config.models.optimizer.model,
        reasoningEffort: config.models.optimizer.reasoning_effort,
        promptFile: path.join(rootDir, "prompts", "optimizer.md"),
        schemaFile: path.join(rootDir, "schemas", `${kind}.schema.json`),
        inputFiles: optimizerInputs,
        outputFile: artifactFile,
        logFile: path.join(runDir, "logs", `optimizer.attempt-${run.attempt}.log`), rootDir
      });
      await assertTargetsUnchanged(improvementTargets, targetSnapshots);
      run.status = "VALIDATING_PROPOSAL";
      await saveRun(runFile, run);
      const proposal = await readJson(artifactFile);
      const evidence = await readJson(path.join(runDir, "evidence.json"));
      const result = await validateArtifact("proposal", proposal, { run, evidence, findings }, rootDir);
      if (!result.valid) throw new Error(JSON.stringify(result.errors));
      await stageSuccess(runFile, run, "optimizer", filename);
      run.status = proposal.proposals.length > 0
        ? "COMPLETED_WITH_PROPOSAL"
        : "COMPLETED_WITH_FINDINGS";
      await saveRun(runFile, run);
      await writeReport(reportFile, run, { findings, metrics, trend, proposal });
      return run;
    } catch (error) {
      const validation = run.status === "VALIDATING_PROPOSAL";
      await fail(runFile, reportFile, run, validation ? "FAILED_PROPOSAL_VALIDATION" : "FAILED_OPTIMIZATION", "optimizer", validation ? "PROPOSAL_VALIDATION_FAILED" : "OPTIMIZATION_FAILED", error);
      return run;
    }
  } finally {
    await release();
  }
}
