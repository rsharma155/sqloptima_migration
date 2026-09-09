/**
 * Module: scripts/ensure-native-bindings.mjs
 * Purpose: Install platform-native optional deps so apps/ui works on Mac and Windows
 *          (and heals trees synced across OSes, e.g. Mac_bak → Windows).
 * Author: Ravi Sharma
 * Copyright (c) 2026 Ravi Sharma
 * SPDX-License-Identifier: MIT
 *
 * Usage:
 *   node scripts/ensure-native-bindings.mjs           # all desktop OS bindings (default)
 *   node scripts/ensure-native-bindings.mjs --current  # this OS only
 *   node scripts/ensure-native-bindings.mjs --all      # explicit all-desktop
 *   node scripts/ensure-native-bindings.mjs --check    # exit 1 if current OS missing
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI_ROOT = join(__dirname, "..");
const require = createRequire(join(UI_ROOT, "package.json"));

const args = new Set(process.argv.slice(2));
const CHECK_ONLY = args.has("--check");
const CURRENT_ONLY =
  args.has("--current") || process.env.NATIVE_DEPS_CURRENT_ONLY === "1";
const WANT_ALL = !CURRENT_ONLY;

/** @type {Record<string, string>} */
const ROLLDOWN_BY_PLATFORM = {
  "darwin-arm64": "@rolldown/binding-darwin-arm64",
  "darwin-x64": "@rolldown/binding-darwin-x64",
  "win32-arm64": "@rolldown/binding-win32-arm64-msvc",
  "win32-x64": "@rolldown/binding-win32-x64-msvc",
  "linux-arm64": "@rolldown/binding-linux-arm64-gnu",
  "linux-x64": "@rolldown/binding-linux-x64-gnu",
};

/** @type {Record<string, string>} */
const LIGHTNING_BY_PLATFORM = {
  "darwin-arm64": "lightningcss-darwin-arm64",
  "darwin-x64": "lightningcss-darwin-x64",
  "win32-arm64": "lightningcss-win32-arm64-msvc",
  "win32-x64": "lightningcss-win32-x64-msvc",
  "linux-arm64": "lightningcss-linux-arm64-gnu",
  "linux-x64": "lightningcss-linux-x64-gnu",
};

/** @type {Record<string, string>} */
const NEXT_SWC_BY_PLATFORM = {
  "darwin-arm64": "@next/swc-darwin-arm64",
  "darwin-x64": "@next/swc-darwin-x64",
  "win32-arm64": "@next/swc-win32-arm64-msvc",
  "win32-x64": "@next/swc-win32-x64-msvc",
  "linux-arm64": "@next/swc-linux-arm64-gnu",
  "linux-x64": "@next/swc-linux-x64-gnu",
};

const DESKTOP_KEYS = [
  "darwin-arm64",
  "darwin-x64",
  "win32-arm64",
  "win32-x64",
  "linux-x64",
  "linux-arm64",
];

function platformKey(platform = process.platform, arch = process.arch) {
  return `${platform}-${arch}`;
}

function pkgInstalled(name) {
  try {
    require.resolve(`${name}/package.json`);
    return true;
  } catch {
    const scoped = name.startsWith("@")
      ? join(UI_ROOT, "node_modules", ...name.split("/"))
      : join(UI_ROOT, "node_modules", name);
    return existsSync(join(scoped, "package.json"));
  }
}

function readOptionalVersion(parentPkg, depName) {
  try {
    const pkgPath = require.resolve(`${parentPkg}/package.json`);
    const json = JSON.parse(readFileSync(pkgPath, "utf8"));
    return (
      json.optionalDependencies?.[depName] ||
      json.dependencies?.[depName] ||
      json.version ||
      null
    );
  } catch {
    return null;
  }
}

function versionFor(depName) {
  if (depName.startsWith("@rolldown/binding-")) {
    return readOptionalVersion("rolldown", depName) || "1.0.3";
  }
  if (depName.startsWith("lightningcss-")) {
    return readOptionalVersion("lightningcss", depName) || "1.32.0";
  }
  if (depName.startsWith("@next/swc-")) {
    return readOptionalVersion("next", depName) || require("next/package.json").version;
  }
  return null;
}

function listInstalledNativeBindings() {
  const root = join(UI_ROOT, "node_modules");
  const found = [];
  const rolldownDir = join(root, "@rolldown");
  if (existsSync(rolldownDir)) {
    for (const name of readdirSync(rolldownDir)) {
      if (name.startsWith("binding-")) found.push(`@rolldown/${name}`);
    }
  }
  for (const name of existsSync(root) ? readdirSync(root) : []) {
    if (name.startsWith("lightningcss-") && name !== "lightningcss") {
      found.push(name);
    }
  }
  return found;
}

function targetsToInstall() {
  const key = platformKey();
  const keys = new Set([key]);
  if (WANT_ALL) {
    for (const k of DESKTOP_KEYS) keys.add(k);
  }

  /** @type {string[]} */
  const specs = [];
  for (const k of keys) {
    for (const map of [ROLLDOWN_BY_PLATFORM, LIGHTNING_BY_PLATFORM, NEXT_SWC_BY_PLATFORM]) {
      const name = map[k];
      if (!name) continue;
      if (pkgInstalled(name)) continue;
      const ver = versionFor(name);
      specs.push(ver ? `${name}@${ver}` : name);
    }
  }
  return specs;
}

function npmInstall(specs) {
  if (specs.length === 0) return 0;
  console.log(`[ensure-native-bindings] installing ${specs.length} package(s) for cross-OS support:`);
  for (const s of specs) console.log(`  - ${s}`);

  // Install one package at a time so npm does not prune the rest of node_modules.
  // npm.cmd is a batch file — Node requires shell:true on Windows to run it.
  const isWin = process.platform === "win32";
  const npmCmd = isWin ? "npm.cmd" : "npm";
  for (const spec of specs) {
    const result = spawnSync(
      npmCmd,
      ["install", "--no-save", "--no-package-lock", "--force", "--ignore-scripts", spec],
      {
        cwd: UI_ROOT,
        stdio: "inherit",
        shell: isWin,
        env: {
          ...process.env,
          npm_config_audit: "false",
          npm_config_fund: "false",
          npm_config_ignore_scripts: "true",
        },
      },
    );
    if (result.error) {
      console.error("[ensure-native-bindings]", result.error.message);
      return 1;
    }
    if ((result.status ?? 1) !== 0) {
      return result.status ?? 1;
    }
  }
  return 0;
}

function currentMissing() {
  const key = platformKey();
  const required = [
    ROLLDOWN_BY_PLATFORM[key],
    LIGHTNING_BY_PLATFORM[key],
    NEXT_SWC_BY_PLATFORM[key],
  ].filter(Boolean);
  return required.filter((name) => !pkgInstalled(name));
}

function main() {
  if (!existsSync(join(UI_ROOT, "node_modules"))) {
    console.error("[ensure-native-bindings] node_modules missing — run npm ci / npm install first");
    process.exit(1);
  }

  const missingNow = currentMissing();
  if (CHECK_ONLY) {
    if (missingNow.length) {
      console.error(
        `[ensure-native-bindings] missing for ${platformKey()}: ${missingNow.join(", ")}`,
      );
      console.error("Run: npm run deps:native:all");
      process.exit(1);
    }
    console.log(`[ensure-native-bindings] ok (${platformKey()})`);
    return;
  }

  // Nested npm install during an active lifecycle often deadlocks; defer with a clear hint.
  if (process.env.npm_lifecycle_event === "postinstall" && WANT_ALL) {
    const specs = targetsToInstall();
    if (specs.length === 0) {
      console.log(
        `[ensure-native-bindings] ok — ${listInstalledNativeBindings().length} binding(s) present`,
      );
      return;
    }
    // Still try; if nesting fails, print recovery command (do not fail npm ci).
    const code = npmInstall(specs);
    if (code !== 0) {
      console.warn(
        "[ensure-native-bindings] deferred: run `npm run deps:native:all` after install completes",
      );
      // Current-OS packages from npm ci are enough to not break the install.
      if (currentMissing().length === 0) {
        process.exit(0);
      }
      process.exit(0);
    }
    console.log(`[ensure-native-bindings] ready for ${platformKey()} (+ peer OS bindings)`);
    return;
  }

  const specs = targetsToInstall();
  if (specs.length === 0) {
    console.log(
      `[ensure-native-bindings] ok — native bindings present (${platformKey()}; ${listInstalledNativeBindings().length} total)`,
    );
    return;
  }

  const code = npmInstall(specs);
  if (code !== 0) {
    console.error("[ensure-native-bindings] npm install failed");
    process.exit(code);
  }

  const still = currentMissing();
  if (still.length) {
    console.error(`[ensure-native-bindings] still missing: ${still.join(", ")}`);
    process.exit(1);
  }
  console.log(`[ensure-native-bindings] ready for ${platformKey()}`);
}

main();
