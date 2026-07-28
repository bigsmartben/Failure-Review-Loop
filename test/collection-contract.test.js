import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { readJson } from "../src/io.js";
import { validateArtifact } from "../src/validation.js";
import { ROOT } from "./helpers.js";

const sourceFile = path.join(
  ROOT,
  "examples",
  "source-records.valid.regression-data.json"
);
const evidenceFile = path.join(
  ROOT,
  "examples",
  "evidence.valid.regression-data.json"
);

function runFor(evidence) {
  return {
    run_id: evidence.run_id,
    parameters: {
      project_id: evidence.project_id,
      window_start: evidence.window_start,
      window_end: evidence.window_end,
      contract_revision: evidence.contract_revision,
      contract_bundle_hash: evidence.contract_bundle_hash
    }
  };
}

async function sourceFixture() {
  return structuredClone(await readJson(sourceFile));
}

test("collected regression data satisfies source and evidence contracts", async () => {
  const source = await sourceFixture();
  const evidence = await readJson(evidenceFile);
  const sourceResult = await validateArtifact("source-records", source, {}, ROOT);
  assert.equal(sourceResult.valid, true, JSON.stringify(sourceResult.errors));

  const evidenceResult = await validateArtifact(
    "evidence",
    evidence,
    { run: runFor(evidence), source },
    ROOT
  );
  assert.equal(evidenceResult.valid, true, JSON.stringify(evidenceResult.errors));
});

test("source contract rejects missing content", async () => {
  const source = await sourceFixture();
  delete source.conversations[0].records[0].content_or_reference;
  const result = await validateArtifact("source-records", source, {}, ROOT);
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "SCHEMA_VALIDATION_FAILED"));
});

test("source contract rejects duplicate sequence", async () => {
  const source = await sourceFixture();
  source.conversations[0].records[1].sequence = 0;
  const result = await validateArtifact("source-records", source, {}, ROOT);
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "SOURCE_RECORDS_SEQUENCE_INVALID"));
});

test("source contract rejects a tool result without an earlier call", async () => {
  const source = await sourceFixture();
  source.conversations[0].records.splice(2, 1);
  source.collection_summary.records_in_window -= 1;
  const result = await validateArtifact("source-records", source, {}, ROOT);
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "SOURCE_RECORDS_TOOL_CALL_MISSING"));
});

test("source contract rejects content hash drift", async () => {
  const source = await sourceFixture();
  source.conversations[0].records[0].content_or_reference = "篡改后的输入";
  const result = await validateArtifact("source-records", source, {}, ROOT);
  assert.equal(result.valid, false);
  assert(result.errors.some((error) =>
    error.code === "SOURCE_RECORDS_CONTENT_HASH_MISMATCH"));
});

test("evidence must preserve source records in their original order", async () => {
  const source = await sourceFixture();
  const evidence = await readJson(evidenceFile);
  [evidence.records[0], evidence.records[1]] = [evidence.records[1], evidence.records[0]];
  const result = await validateArtifact(
    "evidence",
    evidence,
    { run: runFor(evidence), source },
    ROOT
  );
  assert.equal(result.valid, false);
  assert(result.errors.some((error) => error.code === "EVIDENCE_SOURCE_MISMATCH"));
});
