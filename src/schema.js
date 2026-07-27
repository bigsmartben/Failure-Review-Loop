import path from "node:path";
import { readFile } from "node:fs/promises";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validators = new Map();

export async function loadValidator(schemaName, rootDir) {
  const key = `${rootDir}:${schemaName}`;
  if (validators.has(key)) return validators.get(key);
  const file = path.join(rootDir, "schemas", `${schemaName}.schema.json`);
  const schema = JSON.parse(await readFile(file, "utf8"));
  const validator = ajv.compile(schema);
  validators.set(key, validator);
  return validator;
}

export async function validateSchema(schemaName, data, rootDir) {
  const validator = await loadValidator(schemaName, rootDir);
  const valid = validator(data);
  return {
    valid,
    errors: valid ? [] : validator.errors.map((error) => ({
      code: "SCHEMA_VALIDATION_FAILED",
      path: error.instancePath || "/",
      message: error.message,
      keyword: error.keyword
    }))
  };
}
