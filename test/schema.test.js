import test from "node:test";
import assert from "node:assert/strict";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { readJson } from "../src/io.js";
import { validateSchema } from "../src/schema.js";
import { ROOT } from "./helpers.js";

test("all valid and invalid schema examples behave as labelled", async () => {
  const dir = path.join(ROOT, "examples");
  const files = (await readdir(dir)).filter((file) => file.endsWith(".json"));
  assert.equal(files.length, 12);
  for (const file of files) {
    const [, kind, expectation] = /^(run|evidence|findings|metrics|trend|proposal)\.(valid|invalid)\./.exec(file);
    const result = await validateSchema(kind, await readJson(path.join(dir, file)), ROOT);
    assert.equal(result.valid, expectation === "valid", `${file}: ${JSON.stringify(result.errors)}`);
  }
});
