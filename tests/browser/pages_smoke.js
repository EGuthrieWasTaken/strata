// Drives a real Chromium through every screen of seeded reviews (scripts/seed_review.py), looking at
// what a script can judge about openspec:web-ui#accessibility: reflow at 320 px and 200 % zoom,
// contrast in light and dark, motion, and working with JavaScript off.
//
//   node pages_smoke.js layout   <pipeline-url> <dual-url>
//   node pages_smoke.js contrast <blank-url> <dual-url> <exports-dir>
//   node pages_smoke.js motion   <blank-url>
//   node pages_smoke.js nojs     <blank-url> <exports-dir>
//   node pages_smoke.js hostile  <dual-url>
//
// Each prints one JSON object whose `failures` is a list of sentences; it exits 1 when that list is not
// empty. Every check runs even after one fails, so one run shows the whole picture.
const { chromium } = require("playwright");
const path = require("path");

const [scenario, ...args] = process.argv.slice(2);

// ---------------------------------------------------------------------------------------- helpers

function watch(page, problems, label) {
  page.on("console", (m) => { if (m.type() === "error") problems.push(label + " console: " + m.text()); });
  page.on("pageerror", (e) => problems.push(label + " pageerror: " + e.message));
}

async function cspWatch(page) {
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      console.error("CSP violation: " + e.violatedDirective + " " + e.blockedURI);
    });
  });
}

async function openSession(browser, url, options = {}) {
  const context = await browser.newContext(options);
  const page = await context.newPage();
  const problems = [];
  await cspWatch(page);
  watch(page, problems, new URL(url).port);
  await page.goto(url); // sets the session cookie
  return { context, page, problems, origin: new URL(url).origin };
}

// In-page: WCAG contrast of two sRGB colours given as computed `rgb(...)` strings.
const CONTRAST_JS = `
  window.__rgb = (c) => { const m = c.match(/rgba?\\(([^)]+)\\)/); const p = m[1].split(",").map((x) => parseFloat(x)); return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; };
  window.__lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  window.__ratio = (a, b) => { const x = window.__lum(a), y = window.__lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  window.__bg = (el) => { for (let e = el; e; e = e.parentElement) { const c = window.__rgb(getComputedStyle(e).backgroundColor); if (c.a > 0) return c.rgb; } return [255, 255, 255]; };
`;

async function contrastOf(page, selector, kind) {
  // Every visible match of `selector`: its text colour (kind "text") or border colour (kind "border")
  // against the background it sits on. Returns the lowest ratio, or null when nothing matches.
  await page.evaluate(CONTRAST_JS);
  return page.evaluate(([sel, k]) => {
    let worst = null;
    for (const el of document.querySelectorAll(sel)) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const s = getComputedStyle(el);
      const fg = window.__rgb(k === "text" ? s.color : s.borderTopColor).rgb;
      // A border sits on the background of the element's parent; text on its own.
      const bg = window.__bg(k === "text" ? el : el.parentElement);
      const ratio = window.__ratio(fg, bg);
      if (worst === null || ratio < worst.ratio) worst = { ratio: Math.round(ratio * 100) / 100, text: (el.textContent || "").trim().slice(0, 40) };
    }
    return worst;
  }, [selector, kind]);
}

async function readLinks(page, origin, index, pattern) {
  await page.goto(origin + index);
  const hrefs = await page.$$eval("a[href]", (as) => as.map((a) => a.getAttribute("href")));
  return hrefs.find((h) => pattern.test(h));
}

// -------------------------------------------------------------------------------------- scenarios

async function layout(browser, urls) {
  const failures = [];
  const report = { pages: 0, widths: [1024, 640, 320] };
  for (const [which, url] of urls.entries()) {
    const { page, problems, origin, context } = await openSession(browser, url);
    const paths = ["/", "/searches", "/searches/new", "/import", "/records", "/history", "/dedup", "/criteria",
      "/criteria/new", "/assign/title-abstract", "/screen/title-abstract", "/screen/full-text",
      "/rescreen/title-abstract", "/adjudicate/title-abstract", "/retrieve", "/studies", "/analysis", "/prisma"];
    // The first review has been extracted, assessed and analysed; the second (two reviewers) has not.
    const [indexes] = [which === 0 ? ["/extract", "/rob"] : []];
    paths.push(...indexes);
    for (const [index, pattern] of [
      ["/records", /^\/records\/rec_/], ["/searches", /^\/searches\/S-/], ["/retrieve", /^\/retrieve\/rpt_/],
      ...(which === 0 ? [["/extract", /^\/extract\/std_/], ["/rob", /^\/rob\/std_/]] : []),
      ["/analysis", /^\/analysis\/[a-z]/],
    ]) {
      const found = await readLinks(page, origin, index, pattern);
      if (found && !/\/plots\//.test(found)) paths.push(found);
    }
    const criterion = await readLinks(page, origin, "/criteria", /^\/criteria\/[A-Z]+-\d+\/edit/);
    if (criterion) paths.push(criterion, criterion.replace("/edit", "/retire"));

    for (const p of paths) {
      for (const width of report.widths) {
        await page.setViewportSize({ width, height: width === 1024 ? 768 : 640 });
        const response = await page.goto(origin + p);
        const tag = `${new URL(url).port}${p} @${width}`;
        if (!response || response.status() >= 400) {
          failures.push(`${tag}: answered ${response ? response.status() : "nothing"}`);
          break;
        }
        if (width === 1024) report.pages += 1;
        const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        if (over > 0) failures.push(`${tag}: the page scrolls sideways by ${over}px`);
        if (width < 1024) {
          const spill = await page.evaluate(() => {
            const vw = document.documentElement.clientWidth;
            const scrollable = (el) => { for (let e = el.parentElement; e; e = e.parentElement) { const o = getComputedStyle(e).overflowX; if (o === "auto" || o === "scroll") return true; } return false; };
            const out = [];
            for (const el of document.body.querySelectorAll("*")) {
              const r = el.getBoundingClientRect();
              if (r.width === 0 || r.height === 0 || r.right <= vw + 1 || scrollable(el)) continue;
              out.push(el.tagName.toLowerCase() + (typeof el.className === "string" && el.className ? "." + el.className.split(" ")[0] : "") + " right=" + Math.round(r.right));
              if (out.length === 3) break;
            }
            return out;
          });
          if (spill.length) failures.push(`${tag}: reaches past the right edge: ${spill.join(", ")}`);
        }
      }
    }
    for (const p of problems) failures.push(p);
    await context.close();
  }
  return { failures, report };
}

async function contrast(browser, [blank, dual, exportsDir]) {
  const failures = [];
  const measured = {};
  const check = (scheme, label, worst, minimum) => {
    measured[`${scheme} ${label}`] = worst ? worst.ratio : "absent";
    if (worst && worst.ratio < minimum) failures.push(`${scheme}: ${label} is ${worst.ratio}:1 (needs ${minimum}:1) "${worst.text}"`);
    if (!worst) failures.push(`${scheme}: nothing matched for ${label}`);
  };
  for (const scheme of ["light", "dark"]) {
    const a = await openSession(browser, blank, { colorScheme: scheme, reducedMotion: "no-preference" });
    await a.page.goto(a.origin + "/searches/new");
    check(scheme, "body text", await contrastOf(a.page, "main p", "text"), 4.5);
    check(scheme, "links", await contrastOf(a.page, "a", "text"), 4.5);
    check(scheme, "drop target border", await contrastOf(a.page, ".dropzone", "border"), 3);
    await a.page.evaluate(() => {
      const zone = document.querySelector("[data-dropzone]");
      const t = new DataTransfer();
      t.items.add(new File(["x"], "x.ris"));
      zone.dispatchEvent(new DragEvent("dragenter", { dataTransfer: t, bubbles: true, cancelable: true }));
    });
    await a.page.waitForTimeout(400); // the border colour transitions; measure where it ends
    check(scheme, "drop target border while dragging", await contrastOf(a.page, ".dropzone.is-dragging", "border"), 3);
    check(scheme, "drop target state text", await contrastOf(a.page, ".dropzone-state", "text"), 4.5);
    await a.page.evaluate(() => document.querySelector("[data-dropzone]").dispatchEvent(new DragEvent("dragleave", { bubbles: true })));

    // A file that cannot be imported at all is refused with a message in an error box.
    await a.page.setInputFiles('input[type="file"]', path.join(exportsDir, "full-text.pdf"));
    await a.page.fill('input[name="database"]', "MEDLINE");
    await a.page.fill('input[name="platform"]', "Ovid");
    await a.page.fill('textarea[name="query"]', "1 exp Learning/");
    await a.page.fill('textarea[name="rationale"]', "Checking how a refused file looks in " + scheme);
    await a.page.click('button[type="submit"]');
    await a.page.waitForLoadState("load");
    const errorText = await a.page.evaluate(() => Array.from(document.querySelectorAll(".error")).map((e) => e.textContent.trim()).join(" | "));
    if (!errorText) failures.push(`${scheme}: a PDF attached as an export was not refused with an error message`);
    check(scheme, "error text", await contrastOf(a.page, ".error", "text"), 4.5);
    check(scheme, "error border", await contrastOf(a.page, ".error", "border"), 3);
    for (const p of a.problems) if (!/status of 422/.test(p)) failures.push(p); // the refusal, on purpose
    await a.context.close();

    const b = await openSession(browser, dual, { colorScheme: scheme });
    await b.page.goto(b.origin + "/searches");
    const flags = await b.page.evaluate(() => Array.from(document.querySelectorAll(".flag")).map((f) => f.textContent.trim()));
    if (!flags.some((f) => /Missing/.test(f)) || !flags.some((f) => /No export yet/.test(f))) {
      failures.push(`${scheme}: /searches does not say in words that a query is missing and an export is not there: ${JSON.stringify(flags)}`);
    }
    check(scheme, "warning flag text", await contrastOf(b.page, ".flag", "text"), 4.5);
    await b.page.goto(b.origin + "/screen/title-abstract");
    for (const kind of ["include", "exclude", "maybe"]) {
      check(scheme, `${kind} button text`, await contrastOf(b.page, `.btn-${kind}`, "text"), 4.5);
    }
    await b.page.goto(b.origin + "/searches");
    check(scheme, "muted text", await contrastOf(b.page, ".muted", "text"), 4.5);
    await b.page.goto(b.origin + "/rescreen/title-abstract");
    check(scheme, "rescreen text", await contrastOf(b.page, "main p", "text"), 4.5);
    for (const p of b.problems) failures.push(p);
    await b.context.close();
  }
  return { failures, report: measured };
}

async function motion(browser, [blank]) {
  const failures = [];
  const report = {};
  for (const preference of ["reduce", "no-preference"]) {
    const s = await openSession(browser, blank, { reducedMotion: preference });
    await s.page.goto(s.origin + "/searches/new");
    const durations = await s.page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll("*")) {
        const c = getComputedStyle(el);
        const t = c.transitionDuration.split(",").map((x) => parseFloat(x));
        const a = c.animationDuration.split(",").map((x) => parseFloat(x));
        if (t.some((x) => x > 0) || a.some((x) => x > 0)) out.push(el.tagName.toLowerCase() + (el.className ? "." + String(el.className).split(" ")[0] : ""));
      }
      return out;
    });
    report[preference] = durations;
    if (preference === "reduce" && durations.length) failures.push(`reduced motion: still animating or transitioning: ${durations.join(", ")}`);
    if (preference === "no-preference" && !durations.includes("div.dropzone") && !durations.some((d) => d.includes("dropzone"))) {
      failures.push("without a preference the drop target no longer transitions, so the reduced-motion check proves nothing: " + JSON.stringify(durations));
    }
    for (const p of s.problems) failures.push(p);
    await s.context.close();
  }
  return { failures, report };
}

async function nojs(browser, [blank, exportsDir]) {
  const failures = [];
  const s = await openSession(browser, blank, { javaScriptEnabled: false });
  const { page, origin } = s;
  const shown = [];
  await page.goto(origin + "/searches/new");
  const hint = await page.evaluate(() => { const h = document.querySelector(".dropzone-js-only"); return h ? !h.hidden : null; });
  shown.push({ dropHint: hint });
  if (hint === true) failures.push("without JavaScript the drop hint is shown, though nothing can be dropped");
  await page.setInputFiles('input[type="file"]', path.join(exportsDir, "spacing-medline.ris"));
  await page.fill('input[name="database"]', "MEDLINE");
  await page.fill('input[name="platform"]', "Ovid");
  await page.fill('textarea[name="query"]', "1 exp Learning/");
  await page.fill('textarea[name="rationale"]', "Recording a search with JavaScript switched off");
  await Promise.all([page.waitForURL(/\/import\/review\//), page.click('button[type="submit"]')]);
  if (!(await page.textContent("main")).includes("Nothing has been imported yet")) failures.push("no-JS: the review page does not say nothing is imported");
  await page.fill('textarea[name="rationale"]', "Importing with JavaScript switched off");
  await Promise.all([page.waitForSelector('[data-testid="import-results"]'), page.click("#confirm-form button")]);
  if (!/Imported as/.test(await page.textContent("main"))) failures.push("no-JS: the import did not finish");

  // Screening without a script: click the buttons, the page reloads between records.
  await page.goto(origin + "/screen/title-abstract");
  const before = await page.textContent("main");
  const include = await page.$("button[value=include]");
  if (!include) failures.push("no-JS: the screening page has no Include button");
  else {
    await Promise.all([page.waitForLoadState("load"), include.click()]);
    const after = await page.textContent("main");
    if (after === before) failures.push("no-JS: pressing Include left the same page");
  }
  for (const p of s.problems) failures.push(p);
  await s.context.close();
  return { failures, report: { shown } };
}

async function hostile(browser, [dual]) {
  const failures = [];
  const s = await openSession(browser, dual);
  const { page, origin } = s;
  const report = {};
  await page.goto(origin + "/records");
  const link = await page.$$eval("tr", (rows) => {
    const row = rows.find((r) => /Payload test/.test(r.textContent));
    const a = row && row.querySelector('a[href^="/records/rec_"]');
    return a ? [a.getAttribute("href")] : null;
  });
  if (!link) failures.push("the record with hostile markup is not in the records table");
  for (const p of [link ? link[0] : null, "/screen/title-abstract", "/records"]) {
    if (!p) continue;
    await page.goto(origin + p);
    const state = await page.evaluate(() => ({
      title: document.title,
      scripts: document.querySelectorAll("main script, main img[onerror]").length,
      shown: document.body.innerText.includes("<script>document.title='PWNED'</script>"),
      headings: Array.from(document.querySelectorAll("h1")).length,
    }));
    report[p] = state;
    if (/PWNED/.test(state.title)) failures.push(`${p}: a script in a record ran (the page title is now ${state.title})`);
    if (state.scripts) failures.push(`${p}: markup from a record became ${state.scripts} live element(s)`);
    if (state.headings !== 1) failures.push(`${p}: ${state.headings} <h1> elements; a closing tag in a record may have broken out of the page`);
    if (/\/rec_|screen/.test(p) && !state.shown) failures.push(`${p}: the record's markup is not displayed as text`);
  }
  for (const p of s.problems) failures.push(p);
  await s.context.close();
  return { failures, report };
}

// ------------------------------------------------------------------------------------------- main

(async () => {
  const run = { layout, contrast, motion, nojs, hostile }[scenario];
  if (!run) { console.error("unknown scenario " + scenario); process.exit(2); }
  const browser = await chromium.launch();
  let result;
  try { result = await run(browser, args); }
  finally { await browser.close(); }
  console.log(JSON.stringify(result));
  process.exit(result.failures.length ? 1 : 0);
})().catch((error) => {
  console.error(String(error && error.stack ? error.stack : error));
  process.exit(2);
});
