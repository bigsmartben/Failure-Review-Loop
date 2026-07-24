const RULES = [
  [/\bsk-[A-Za-z0-9_-]{16,}\b/g, "[REDACTED_OPENAI_KEY]"],
  [/\bgh[opurs]_[A-Za-z0-9]{20,}\b/g, "[REDACTED_GITHUB_TOKEN]"],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b/gi, "Bearer [REDACTED]"],
  [/(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;"']+/gi, "$1=[REDACTED]"]
];

export function redact(value) {
  if (typeof value === "string") {
    return RULES.reduce((text, [pattern, replacement]) =>
      text.replace(pattern, replacement), value);
  }
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redact(item)]));
  }
  return value;
}
