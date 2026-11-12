// Writes src/api/schema.d.ts from ../contract/openapi.json.
//
//   node scripts/gen-types.mjs           write the file
//   node scripts/gen-types.mjs --check   fail if the file is not what would be written
//
// The output has the shape that openapi-typescript writes (`paths` and `components`), so
// that package can take this script's place once it runs on the TypeScript in use. It
// covers the part of JSON Schema that the server's contract uses and stops with an error
// on anything else, so it can never quietly write a wrong type.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const SOURCE = resolve(here, "../../contract/openapi.json");
const TARGET = resolve(here, "../src/api/schema.d.ts");
const REF = "#/components/schemas/";
const METHODS = ["get", "put", "post", "delete", "patch", "head", "options"];

// Keywords that say nothing about the TypeScript type.
const ANNOTATIONS = new Set([
  "title",
  "description",
  "default",
  "format",
  "examples",
  "example",
  "deprecated",
  "readOnly",
  "writeOnly",
  "minLength",
  "maxLength",
  "pattern",
  "minimum",
  "maximum",
  "exclusiveMinimum",
  "exclusiveMaximum",
  "multipleOf",
  "minItems",
  "maxItems",
  "uniqueItems",
]);
const STRUCTURAL = new Set([
  "$ref",
  "type",
  "properties",
  "required",
  "additionalProperties",
  "items",
  "anyOf",
  "oneOf",
  "allOf",
  "enum",
  "const",
]);

function fail(message) {
  throw new Error(`gen-types: ${message}`);
}

function key(name) {
  return /^([A-Za-z_$][A-Za-z0-9_$]*|[1-9][0-9]*)$/.test(name) ? name : JSON.stringify(name);
}

function comment(text, indent) {
  if (!text) return "";
  const safe = String(text).replaceAll("*/", "*\\/").trim();
  const lines = safe.split("\n").map((line) => line.trim());
  if (lines.length === 1) return `${indent}/** ${lines[0]} */\n`;
  return `${indent}/**\n${lines.map((line) => `${indent} * ${line}`.trimEnd()).join("\n")}\n${indent} */\n`;
}

function union(parts) {
  const unique = [...new Set(parts)];
  if (unique.includes("unknown")) return "unknown";
  return unique.join(" | ");
}

function inArray(type) {
  return /[|&]/.test(type) ? `(${type})[]` : `${type}[]`;
}

/** The TypeScript type of one JSON Schema, written at the given indent. */
function typeOf(schema, indent, where) {
  if (schema === true) return "unknown";
  if (schema === false) return "never";
  if (schema === null || typeof schema !== "object" || Array.isArray(schema)) {
    fail(`${where}: a schema must be an object`);
  }
  for (const word of Object.keys(schema)) {
    if (!ANNOTATIONS.has(word) && !STRUCTURAL.has(word)) {
      fail(`${where}: the keyword "${word}" is not handled`);
    }
  }
  if ("$ref" in schema) {
    if (!schema.$ref.startsWith(REF)) fail(`${where}: cannot follow ${schema.$ref}`);
    return `components["schemas"][${JSON.stringify(schema.$ref.slice(REF.length))}]`;
  }
  if ("const" in schema) return JSON.stringify(schema.const);
  if ("enum" in schema) return union(schema.enum.map((value) => JSON.stringify(value)));
  for (const word of ["anyOf", "oneOf"]) {
    if (word in schema) {
      return union(schema[word].map((part, i) => typeOf(part, indent, `${where}.${word}[${i}]`)));
    }
  }
  if ("allOf" in schema) {
    const parts = schema.allOf.map((part, i) => typeOf(part, indent, `${where}.allOf[${i}]`));
    return parts.map((part) => (part.includes(" | ") ? `(${part})` : part)).join(" & ");
  }
  if (Array.isArray(schema.type)) {
    return union(schema.type.map((type) => typeOf({ ...schema, type }, indent, where)));
  }
  switch (schema.type) {
    case "string":
      return "string";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "null":
      return "null";
    case "array":
      return "items" in schema
        ? inArray(typeOf(schema.items, indent, `${where}.items`))
        : "unknown[]";
    case "object":
      return objectType(schema, indent, where);
    case undefined:
      if ("properties" in schema || "additionalProperties" in schema) {
        return objectType(schema, indent, where);
      }
      return "unknown";
    default:
      return fail(`${where}: the type "${schema.type}" is not handled`);
  }
}

function objectType(schema, indent, where) {
  const inner = `${indent}  `;
  const required = new Set(schema.required ?? []);
  const properties = Object.entries(schema.properties ?? {});
  let out = "";
  for (const [name, property] of properties) {
    const described = typeof property === "object" && property ? property.description : "";
    out += comment(described, inner);
    const type = typeOf(property, inner, `${where}.${name}`);
    out += `${inner}${key(name)}${required.has(name) ? "" : "?"}: ${type};\n`;
  }
  const extra = schema.additionalProperties;
  if (extra === false) {
    if (properties.length === 0) return "Record<string, never>";
  } else if (extra !== undefined || properties.length === 0) {
    const type = extra === undefined ? "unknown" : typeOf(extra, inner, `${where}.*`);
    out += `${inner}[key: string]: ${properties.length === 0 ? type : "unknown"};\n`;
  }
  return `{\n${out}${indent}}`;
}

function parametersType(parameters, indent, where) {
  const inner = `${indent}  `;
  let out = "";
  for (const place of ["query", "path", "header"]) {
    const group = parameters.filter((parameter) => parameter.in === place);
    if (group.length === 0) {
      out += `${inner}${place}?: never;\n`;
      continue;
    }
    const all = group.every((parameter) => !parameter.required);
    out += `${inner}${place}${all ? "?" : ""}: {\n`;
    for (const parameter of group) {
      const type = typeOf(parameter.schema ?? {}, `${inner}  `, `${where}.${parameter.name}`);
      out += comment(parameter.description, `${inner}  `);
      out += `${inner}  ${key(parameter.name)}${parameter.required ? "" : "?"}: ${type};\n`;
    }
    out += `${inner}};\n`;
  }
  const strange = parameters.find((p) => !["query", "path", "header"].includes(p.in));
  if (strange) fail(`${where}: a parameter in "${strange.in}" is not handled`);
  return `{\n${out}${indent}}`;
}

function contentType(content, indent, where) {
  if (!content || Object.keys(content).length === 0) {
    return `{\n${indent}  content?: never;\n${indent}}`;
  }
  let out = `{\n${indent}  content: {\n`;
  for (const [media, body] of Object.entries(content)) {
    const type = typeOf(body.schema ?? {}, `${indent}    `, `${where} ${media}`);
    out += `${indent}    ${JSON.stringify(media)}: ${type};\n`;
  }
  return `${out}${indent}  };\n${indent}}`;
}

function operationType(operation, shared, indent, where) {
  const inner = `${indent}  `;
  for (const item of [...shared, ...(operation.parameters ?? [])]) {
    if ("$ref" in item) fail(`${where}: a referenced parameter is not handled`);
  }
  const parameters = [...shared, ...(operation.parameters ?? [])];
  let out = `${inner}parameters: ${parametersType(parameters, inner, where)};\n`;
  const body = operation.requestBody;
  if (body) {
    if ("$ref" in body) fail(`${where}: a referenced request body is not handled`);
    const type = contentType(body.content, inner, `${where} request`);
    out += `${inner}requestBody${body.required ? "" : "?"}: ${type};\n`;
  } else {
    out += `${inner}requestBody?: never;\n`;
  }
  out += `${inner}responses: {\n`;
  for (const [status, response] of Object.entries(operation.responses ?? {})) {
    if ("$ref" in response) fail(`${where}: a referenced response is not handled`);
    out += comment(response.description, `${inner}  `);
    const type = contentType(response.content, `${inner}  `, `${where} ${status}`);
    out += `${inner}  ${key(status)}: ${type};\n`;
  }
  out += `${inner}};\n`;
  return `{\n${out}${indent}}`;
}

export function generate(document) {
  let paths = "";
  for (const [path, item] of Object.entries(document.paths ?? {})) {
    paths += `  ${JSON.stringify(path)}: {\n`;
    for (const word of Object.keys(item)) {
      if (!METHODS.includes(word) && word !== "parameters") {
        fail(`${path}: "${word}" is not handled`);
      }
    }
    for (const method of METHODS) {
      const operation = item[method];
      if (!operation) continue;
      const where = `${method.toUpperCase()} ${path}`;
      paths += comment(operation.description ?? operation.summary, "    ");
      paths += `    ${method}: ${operationType(operation, item.parameters ?? [], "    ", where)};\n`;
    }
    paths += "  };\n";
  }
  let schemas = "";
  for (const [name, schema] of Object.entries(document.components?.schemas ?? {})) {
    schemas += comment(schema.description, "    ");
    schemas += `    ${key(name)}: ${typeOf(schema, "    ", name)};\n`;
  }
  return [
    "// Generated by scripts/gen-types.mjs from contract/openapi.json.",
    "// Do not edit: change the contract and run `npm run gen`.",
    "",
    "/** Every route: its parameters, its request body and its answers. */",
    `export interface paths {\n${paths}}`,
    "",
    "/** Every record the routes take and return. */",
    `export interface components {\n  schemas: {\n${schemas}  };\n}`,
    "",
  ].join("\n");
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const text = generate(JSON.parse(readFileSync(SOURCE, "utf8")));
  if (process.argv.includes("--check")) {
    let current = "";
    try {
      current = readFileSync(TARGET, "utf8");
    } catch {
      // A missing file is reported as out of date.
    }
    if (current !== text) {
      console.error("src/api/schema.d.ts does not match contract/openapi.json: run `npm run gen`");
      process.exit(1);
    }
  } else {
    writeFileSync(TARGET, text);
    console.log(`wrote ${TARGET}`);
  }
}
