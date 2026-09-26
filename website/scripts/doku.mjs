#!/usr/bin/env node
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, extname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { sanitizeDokuApiFile } from "./doku-api-policy.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const websiteDir = resolve(scriptDir, "..");
const repoRoot = resolve(websiteDir, "..");
const buildDir = join(websiteDir, "build");
const dokuBinary = process.platform === "win32"
  ? join(websiteDir, "node_modules", ".bin", "doku.cmd")
  : join(websiteDir, "node_modules", ".bin", "doku");
const remoteImportLimit = Number.parseInt(process.env.DOKU_REMOTE_IMPORT_MAX_BYTES || "1048576", 10);

function run(command, args, cwd = websiteDir) {
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function ensureDoku() {
  if (existsSync(dokuBinary)) {
    return;
  }
  console.log("[doku] @wundercorp/doku is not installed; installing pinned version 0.2.4");
  run("npm", ["install", "--ignore-scripts", "--no-audit", "--no-fund"], websiteDir);
  if (!existsSync(dokuBinary)) {
    throw new Error("@wundercorp/doku installation completed but the doku executable is unavailable");
  }
}

function clean() {
  rmSync(buildDir, { recursive: true, force: true });
  rmSync(join(websiteDir, "docs.json"), { force: true });
  rmSync(join(websiteDir, "doku.docs.json"), { force: true });
  rmSync(join(websiteDir, "llms-full.txt"), { force: true });
}

function generate(output = join(websiteDir, "doku.docs.json")) {
  ensureDoku();
  run(dokuBinary, [
    "gen",
    repoRoot,
    "--output",
    output,
    "--llms-output",
    join(websiteDir, "llms-full.txt"),
    "--title",
    "Loki Agent",
    "--base-url",
    "https://loki.computer",
  ]);
  const sanitized = sanitizeDokuApiFile(output);
  console.log(`[doku] public API policy kept ${sanitized.doku?.api?.endpointCount ?? 0} versioned endpoint(s)`);
}

function copySplashSite() {
  const splashDir = join(websiteDir, "splash");
  if (!existsSync(splashDir)) {
    throw new Error(`Missing Loki splash source: ${splashDir}`);
  }
  cpSync(splashDir, buildDir, { recursive: true });
}

function copyStaticAssets() {
  const staticDir = join(websiteDir, "static");
  if (existsSync(staticDir)) {
    cpSync(staticDir, buildDir, { recursive: true });
  }
  const llmsFull = join(websiteDir, "llms-full.txt");
  if (existsSync(llmsFull)) {
    cpSync(llmsFull, join(buildDir, "llms-full.txt"));
  }
  const generatedLlms = join(staticDir, "llms.txt");
  if (existsSync(generatedLlms)) {
    cpSync(generatedLlms, join(buildDir, "llms.txt"));
  }
  cpSync(join(repoRoot, "scripts", "install.sh"), join(buildDir, "install.sh"));
  cpSync(join(repoRoot, "scripts", "install.ps1"), join(buildDir, "install.ps1"));
}

function build({ localPreview = false } = {}) {
  clean();
  mkdirSync(buildDir, { recursive: true });
  generate(join(buildDir, "doku.docs.json"));
  cpSync(join(buildDir, "doku.docs.json"), join(buildDir, "docs.json"));
  copyStaticAssets();
  copySplashSite();
  writeFileSync(
    join(buildDir, "README.txt"),
    "Loki Agent splash site and documentation payload.\n",
  );
  console.log(`[site] built Loki splash page at ${join(buildDir, "index.html")}`);
  console.log(`[doku] generated ${join(buildDir, "doku.docs.json")}`);
  if (localPreview) {
    console.log("[site] local preview serves the production splash page and never uploads docs");
  }
}

function mimeType(path) {
  return ({
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
  })[extname(path).toLowerCase()] || "application/octet-stream";
}

function serve() {
  build({ localPreview: true });
  const host = process.env.HOST || "127.0.0.1";
  const port = Number.parseInt(process.env.PORT || "3000", 10);
  const root = resolve(buildDir);
  const server = createServer((req, res) => {
    const requestPath = decodeURIComponent((req.url || "/").split("?")[0]);
    let relative;
    if (requestPath === "/") {
      relative = "index.html";
    } else if (requestPath === "/privacy" || requestPath === "/privacy/") {
      relative = "privacy/index.html";
    } else if (requestPath === "/terms" || requestPath === "/terms/") {
      relative = "terms/index.html";
    } else if (requestPath === "/timeline" || requestPath === "/timeline/") {
      relative = "timeline/index.html";
    } else {
      relative = requestPath.replace(/^\/+/, "");
    }
    const candidate = resolve(root, normalize(relative));
    if (candidate !== root && !candidate.startsWith(`${root}/`)) {
      res.writeHead(403, { "content-type": "text/plain; charset=utf-8" });
      res.end("Forbidden\n");
      return;
    }
    if (!existsSync(candidate) || statSync(candidate).isDirectory()) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      res.end("Not found\n");
      return;
    }
    res.writeHead(200, {
      "content-type": mimeType(candidate),
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
    });
    res.end(readFileSync(candidate));
  });
  server.listen(port, host, () => {
    const url = `http://${host}:${port}`;
    console.log(`[site] local splash preview: ${url}`);
    console.log("[doku] no request will be made to doku.sh/api/imports");
    if (process.env.LOKI_DOCS_OPEN === "1") {
      const opener = process.platform === "darwin" ? ["open", [url]] : process.platform === "win32" ? ["cmd", ["/c", "start", "", url]] : ["xdg-open", [url]];
      const child = spawn(opener[0], opener[1], { detached: true, stdio: "ignore" });
      child.unref();
    }
  });
}

function portal(force = false) {
  build();
  const payloadPath = join(buildDir, "doku.docs.json");
  const payloadBytes = statSync(payloadPath).size;
  if (!force && payloadBytes > remoteImportLimit) {
    console.error(`[doku] remote import skipped: ${payloadBytes.toLocaleString()} byte payload exceeds the local safety limit of ${remoteImportLimit.toLocaleString()} bytes.`);
    console.error("[doku] use `npm start` for the zero-upload local preview.");
    console.error("[doku] use `npm run portal:force` only if doku.sh has explicitly raised its import limit.");
    process.exit(2);
  }
  ensureDoku();
  run(dokuBinary, [
    "open",
    payloadPath,
    "--site",
    "https://doku.sh",
  ]);
}

const command = process.argv[2] ?? "serve";
const force = process.argv.includes("--force");

if (command === "clean") {
  clean();
} else if (command === "generate") {
  generate();
} else if (command === "build") {
  build();
} else if (command === "serve") {
  serve();
} else if (command === "portal") {
  portal(force);
} else {
  console.error(`Unknown Doku command: ${command}`);
  process.exit(2);
}
