// What scripts/browser.sh asks of Playwright's configuration and reports: which projects
// run, in what order and with which spec files, and what each run left failed.
//
//   node scripts/e2e-plan.mjs plan [file ...]          the runs, one line each
//   node scripts/e2e-plan.mjs left <last-run file>     how many tests a run left failed
//   node scripts/e2e-plan.mjs summary <dir> <slug>=<exit code> ...
//
// `plan` prints a line for each run, in the order they are made: its slug, its projects
// (joined by "|"), and the spec files it is given (as "e2e/<name>", joined by spaces; none
// when it is given every file it has), separated by tabs. The projects that depend on no
// other are the ordinary ones, and run together, first. Every other project runs alone,
// after the projects it depends on, and is given its files only when they are among those
// asked for. Named files are file names, as `geography.spec.ts`; none is every file.
//
// `summary` reads the JSON report of each run, `<dir>/<slug>.json`, and prints what each
// run counted, the files that took longest, and one list of every scenario that failed,
// by file and title. It exits 1 if any failed, or if a run ended badly with none failed.
//
// The configuration is read with E2E_WORKERS set, so that it does not ask the host.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const playwright = resolve(web, "node_modules/.bin/playwright");

/** The name of a project as a slug: "the writer alone" is the-writer-alone. */
function slug(name) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

/** The projects of the configuration, each with the projects it depends on. */
async function projects() {
  process.env.E2E_WORKERS ||= "1";
  const config = (await import(pathToFileURL(resolve(web, "playwright.config.ts")).href)).default;
  return config.projects.map((project) => ({
    name: project.name,
    dependencies: project.dependencies ?? [],
  }));
}

/** The spec files of each project, as Playwright lists them. */
function filesOf() {
  const listed = JSON.parse(
    execFileSync(playwright, ["test", "--list", "--reporter=json"], {
      cwd: web,
      encoding: "utf8",
      env: { ...process.env, E2E_WORKERS: process.env.E2E_WORKERS || "1" },
      maxBuffer: 64 * 1024 * 1024,
    }),
  );
  const files = new Map();
  const walk = (suite) => {
    for (const spec of suite.specs ?? []) {
      for (const test of spec.tests) {
        if (!files.has(test.projectName)) files.set(test.projectName, new Set());
        files.get(test.projectName).add(spec.file);
      }
    }
    for (const inner of suite.suites ?? []) walk(inner);
  };
  for (const suite of listed.suites) walk(suite);
  return files;
}

/** The projects in the order they run: each after every project it depends on. */
function ordered(all) {
  const done = new Set();
  const order = [];
  while (order.length < all.length) {
    const next = all.find(
      (project) => !done.has(project.name) && project.dependencies.every((name) => done.has(name)),
    );
    if (next === undefined)
      throw new Error("the projects of playwright.config.ts depend in a ring");
    done.add(next.name);
    order.push(next);
  }
  return order;
}

async function plan(asked) {
  const all = ordered(await projects());
  const files = filesOf();
  const known = new Set([...files.values()].flatMap((set) => [...set]));
  for (const name of asked) {
    if (!known.has(name)) throw new Error(`no project runs ${name}`);
  }
  const chosen = (project) => {
    const own = [...(files.get(project.name) ?? [])].sort();
    return asked.length === 0 ? own : own.filter((file) => asked.includes(file));
  };
  const lines = [];
  const ordinary = all.filter((project) => project.dependencies.length === 0);
  const theirs = [...new Set(ordinary.flatMap(chosen))].sort();
  if (theirs.length > 0) {
    const names = ordinary.filter((project) => chosen(project).length > 0).map((p) => p.name);
    lines.push(["ordinary", names.join("|"), asked.length === 0 ? [] : theirs]);
  }
  for (const project of all.filter((p) => p.dependencies.length > 0)) {
    const own = chosen(project);
    if (own.length > 0) lines.push([slug(project.name), project.name, asked.length ? own : []]);
  }
  for (const [name, names, given] of lines) {
    console.log([name, names, given.map((file) => `e2e/${file}`).join(" ")].join("\t"));
  }
}

function left(file) {
  if (!existsSync(file)) {
    console.log(0);
    return;
  }
  console.log(JSON.parse(readFileSync(file, "utf8")).failedTests?.length ?? 0);
}

/** Each test of a report, with the file and the titles it is under. */
function* tests(suite, titles = []) {
  for (const spec of suite.specs ?? []) {
    for (const test of spec.tests) yield { file: spec.file, title: [...titles, spec.title], test };
  }
  for (const inner of suite.suites ?? []) {
    // A file's own suite is titled with its name, which the line already has.
    yield* tests(inner, inner.title === inner.file ? titles : [...titles, inner.title]);
  }
}

function minutes(milliseconds) {
  return `${(milliseconds / 60_000).toFixed(1)} min`;
}

function summary(dir, runs) {
  const failed = [];
  const lengths = new Map();
  let bad = false;
  for (const run of runs) {
    const [name, code] = run.split("=");
    const report = resolve(dir, `${name}.json`);
    if (!existsSync(report)) {
      console.log(`${name}: no report: Playwright stopped before it ran (exit ${code})`);
      bad = true;
      continue;
    }
    const read = JSON.parse(readFileSync(report, "utf8"));
    const count = { passed: 0, failed: 0, notRun: 0, skipped: 0 };
    for (const suite of read.suites ?? []) {
      for (const { file, title, test } of tests(suite)) {
        const took = test.results.reduce((sum, result) => sum + (result.duration ?? 0), 0);
        lengths.set(file, (lengths.get(file) ?? 0) + took);
        if (test.status === "expected" || test.status === "flaky") count.passed += 1;
        else if (test.status === "unexpected") {
          count.failed += 1;
          failed.push(`${test.projectName} | ${file} | ${title.join(" › ")}`);
        } else if (test.expectedStatus !== "skipped") count.notRun += 1;
        else count.skipped += 1;
      }
    }
    const errors = read.errors ?? [];
    console.log(
      `${name}: ${count.passed} passed, ${count.failed} failed, ${count.notRun} did not run` +
        `${count.skipped ? `, ${count.skipped} skipped` : ""}, in ${minutes(read.stats?.duration ?? 0)}` +
        ` (exit ${code})`,
    );
    for (const error of errors) {
      console.log(`  error: ${(error.message ?? String(error)).split("\n")[0]}`);
    }
    if (errors.length > 0 || (code !== "0" && count.failed === 0)) bad = true;
  }
  const longest = [...lengths].sort((a, b) => b[1] - a[1]).slice(0, 5);
  if (longest.length > 0) {
    console.log(`longest files: ${longest.map(([f, ms]) => `${f} ${minutes(ms)}`).join(", ")}`);
  }
  if (failed.length > 0) {
    console.log(`\n${failed.length} failed (project | file | scenario):`);
    for (const line of failed) console.log(`  ${line}`);
  } else if (!bad) {
    console.log("\nnothing failed");
  }
  return failed.length > 0 || bad ? 1 : 0;
}

const [command, ...rest] = process.argv.slice(2);
if (command === "plan") {
  try {
    await plan(rest);
  } catch (error) {
    console.error(`e2e-plan: ${error.message}`);
    process.exitCode = 2;
  }
} else if (command === "left") left(rest[0]);
else if (command === "summary") process.exitCode = summary(rest[0], rest.slice(1));
else {
  console.error(
    "usage: e2e-plan.mjs plan [file ...] | left <file> | summary <dir> <slug>=<code> ...",
  );
  process.exitCode = 2;
}
