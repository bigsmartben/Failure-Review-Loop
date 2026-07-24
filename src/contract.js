import { readFile } from "node:fs/promises";
import path from "node:path";
import { canonicalJson, sha256 } from "./hash.js";

export const CONTRACT_REVISION = "2026-07-24.contract-first.1";

const CONTRACT_FILES = Object.freeze([
  "docs/contracts/precedence.md",
  "docs/contracts/deduplication.md",
  "docs/contracts/issue-signatures.json",
  "schemas/run.schema.json",
  "schemas/evidence.schema.json",
  "schemas/findings.schema.json",
  "schemas/metrics.schema.json",
  "schemas/trend.schema.json",
  "schemas/proposal.schema.json",
  "prompts/collector.md",
  "prompts/analyst.md",
  "prompts/optimizer.md"
]);

export async function contractBundleHash(rootDir) {
  const entries = [];
  for (const relativePath of CONTRACT_FILES) {
    entries.push({
      path: relativePath,
      content: await readFile(path.join(rootDir, relativePath), "utf8")
    });
  }
  return `sha256:${sha256(canonicalJson(entries))}`;
}

export async function loadIssueSignatureRegistry(rootDir) {
  const content = JSON.parse(await readFile(
    path.join(rootDir, "docs", "contracts", "issue-signatures.json"),
    "utf8"
  ));
  if (content.contract_revision !== CONTRACT_REVISION) {
    throw new Error("ISSUE_SIGNATURE_CONTRACT_REVISION_MISMATCH");
  }
  return new Set(content.signatures.map((item) =>
    `${item.pattern}:${item.issue_signature}`));
}

export { CONTRACT_FILES };
