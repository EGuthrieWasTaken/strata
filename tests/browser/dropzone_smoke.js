// Drives a real Chromium through the search-and-import flow against a running `strata serve`.
// Usage: node dropzone_smoke.js <tokenised-url>   Prints one JSON object; exits non-zero on failure.
const { chromium } = require("playwright");

const startUrl = process.argv[2];
const origin = new URL(startUrl).origin;
const RIS_ONE = "TY  - JOUR\nTI  - First paper\nPY  - 2020\nDO  - 10.1000/aaa\nER  - \n";
const RIS_TWO = "TY  - JOUR\nTI  - Second paper\nPY  - 2021\nDO  - 10.1000/bbb\nER  - \n";

function check(condition, message) {
  if (!condition) throw new Error(message);
}

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  const problems = [];
  page.on("console", (m) => { if (m.type() === "error") problems.push("console: " + m.text()); });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  await page.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) => {
      console.error("CSP violation: " + e.violatedDirective + " " + e.blockedURI);
    });
  });
  const report = {};

  await page.goto(startUrl); // sets the session cookie

  // A form that already existed before searches did, posted by the browser itself. Under the old
  // `Referrer-Policy: no-referrer` Chromium sent "Origin: null" and the server answered 400.
  await page.goto(origin + "/"); // not /dedup, which is where the post redirects to
  const token = new URL(startUrl).searchParams.get("token");
  await page.evaluate((t) => {
    document.body.insertAdjacentHTML(
      "beforeend",
      '<form id="old" method="post" action="/dedup/run"><input name="csrf_token" value="' + t +
        '"><input name="rationale" value="a real rationale for this check"></form>'
    );
  }, token);
  const [oldResponse] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === "POST"),
    page.evaluate(() => document.getElementById("old").submit()),
  ]);
  report.existingFormStatus = oldResponse.status();
  report.existingFormOrigin = oldResponse.request().headers()["origin"];
  check(oldResponse.status() !== 400, "an existing form is refused with 400 (Origin: " + report.existingFormOrigin + ")");
  await page.waitForLoadState("load"); // the redirect back to /dedup has to land before moving on
  await page.waitForURL(origin + "/dedup");
  await page.goto(origin + "/searches/new");

  // Keyboard only: Tab from the top reaches the file chooser, and focus is visible there.
  await page.focus('input[name="database"]');
  let reached = false;
  for (let i = 0; i < 25 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached = await page.evaluate(() => document.activeElement && document.activeElement.type === "file");
  }
  check(reached, "the file chooser cannot be reached with the keyboard");
  report.keyboardReachesChooser = true;
  const outline = await page.evaluate(() => {
    const s = getComputedStyle(document.activeElement);
    return { style: s.outlineStyle, width: s.outlineWidth };
  });
  check(outline.style !== "none" && outline.width !== "0px", "no visible focus on the file chooser");

  // Dropping two files hands them to the real input, lists them and announces them.
  await page.evaluate(([a, b]) => {
    const zone = document.querySelector("[data-dropzone]");
    const transfer = new DataTransfer();
    transfer.items.add(new File([a], "one.ris", { type: "application/x-research-info-systems" }));
    transfer.items.add(new File([b], "two.ris", { type: "application/x-research-info-systems" }));
    zone.dispatchEvent(new DragEvent("dragenter", { dataTransfer: transfer, bubbles: true, cancelable: true }));
    window.__duringDrag = zone.className + "|" + zone.querySelector("[data-dropzone-state]").textContent;
    zone.dispatchEvent(new DragEvent("drop", { dataTransfer: transfer, bubbles: true, cancelable: true }));
  }, [RIS_ONE, RIS_TWO]);
  const dropped = await page.evaluate(() => ({
    count: document.querySelector('input[type="file"]').files.length,
    names: Array.from(document.querySelectorAll("[data-dropzone-list] li")).map((li) => li.textContent),
    announced: document.getElementById("announcer").textContent,
    state: document.querySelector("[data-dropzone-state]").textContent,
    duringDrag: window.__duringDrag,
    hintShown: !document.querySelector(".dropzone-js-only").hidden,
  }));
  check(dropped.count === 2, "the dropped files did not reach the input: " + JSON.stringify(dropped));
  check(dropped.names.length === 2 && dropped.names[0].startsWith("one.ris"), "files not listed");
  check(/2 files chosen: one\.ris, two\.ris/.test(dropped.announced), "not announced: " + dropped.announced);
  check(dropped.duringDrag.includes("is-dragging") && /Drop to attach/.test(dropped.duringDrag), "no drag state in text");
  check(dropped.hintShown, "the drop hint was not revealed");
  report.dropped = dropped;

  // Text that is not a file is ignored, and says so.
  await page.evaluate(() => {
    const zone = document.querySelector("[data-dropzone]");
    const transfer = new DataTransfer();
    transfer.setData("text/plain", "just some words");
    zone.dispatchEvent(new DragEvent("drop", { dataTransfer: transfer, bubbles: true, cancelable: true }));
  });
  const afterText = await page.evaluate(() => ({
    count: document.querySelector('input[type="file"]').files.length,
    state: document.querySelector("[data-dropzone-state]").textContent,
  }));
  check(afterText.count === 2, "dropping text removed the chosen files");
  check(/Only files can be dropped here/.test(afterText.state), "no message for a non-file drop");
  report.textDrop = afterText;

  // The usual form, posted by the browser itself.
  await page.fill('input[name="database"]', "MEDLINE");
  await page.fill('input[name="platform"]', "Ovid");
  await page.fill('textarea[name="query"]', "1 exp Learning/");
  await page.fill('textarea[name="rationale"]', "Recording the search from a real browser test");
  await Promise.all([page.waitForURL(/\/import\/review\//), page.click('button[type="submit"]')]);
  const review = await page.textContent("main");
  check(review.includes("one.ris") && review.includes("two.ris"), "the review does not list both files");
  check(review.includes("Nothing has been imported yet"), "the review does not say nothing is imported");
  report.reviewedFiles = ["one.ris", "two.ris"];

  // At a phone's width nothing spills sideways, here and on the form.
  await page.setViewportSize({ width: 320, height: 640 });
  report.reviewOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(report.reviewOverflow <= 0, "the review page scrolls sideways at 320px");
  await page.setViewportSize({ width: 1024, height: 768 });

  await page.fill('textarea[name="rationale"]', "Importing both files from the browser test");
  await Promise.all([page.waitForSelector('[data-testid="import-results"]'), page.click("#confirm-form button")]);
  const results = await page.textContent("main");
  check(/Imported as/.test(results) && results.includes("one.ris") && results.includes("two.ris"), "not imported: " + results);
  report.imported = true;

  await page.goto(origin + "/searches/new");
  await page.setViewportSize({ width: 320, height: 640 });
  report.formOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  check(report.formOverflow <= 0, "the search form scrolls sideways at 320px");


  // The other write screens, each posted by the browser itself (the Origin check only ever failed in
  // a real browser), and each looked at the width of a phone.
  await page.setViewportSize({ width: 1024, height: 768 });
  await page.goto(origin + "/records");
  const recordHref = await page.getAttribute('a[href^="/records/rec_"]', "href");
  check(recordHref, "no record to correct");
  await page.goto(origin + recordHref);
  await page.selectOption('select[name="field"]', "title");
  await page.fill('input[name="value"]', "A corrected title from the browser test");
  await page.fill('#fix-form textarea[name="rationale"]', "Correcting the title in a real browser");
  await Promise.all([page.waitForURL(origin + recordHref), page.click("#fix-form button")]);
  const corrected = await page.textContent("main");
  check(/RECORD-AMEND/i.test(corrected) && corrected.includes("A corrected title from the browser test"), "the correction is not in the timeline");
  report.corrected = true;

  await page.goto(origin + "/criteria/new");
  check(/recorded as\s+tightened/.test(await page.textContent("main")), "the form does not say it is recorded as tightened");
  await page.check('input[name="kind"][value="exclusion"]');
  await page.fill('input[name="label"]', "Not empirical");
  await page.fill('textarea[name="definition"]', "Not an empirical study");
  await page.check('input[name="applies_at"][value="title-abstract"]');
  await page.fill('#criterion-form textarea[name="rationale"]', "Adding a criterion from a real browser");
  await Promise.all([page.waitForSelector('[data-testid="added-note"]'), page.click("#criterion-form button")]);
  report.criterionAdded = true;

  await page.goto(origin + "/assign/title-abstract");
  await page.fill('input[name="filter"]', "year >= 2000");
  await Promise.all([page.waitForURL(/filter=/), page.click("#filter-form button")]);
  check(/2 of 2 records match/.test(await page.textContent('[data-testid="filter-result"]')), "the preview does not count the matches");
  await page.check('input[name="actors"][value="ethan"]');
  await page.fill('#assign-form textarea[name="rationale"]', "Assigning myself from a real browser");
  await Promise.all([page.waitForSelector('[data-testid="assigned-note"]'), page.click("#assign-form button")]);
  report.assigned = true;

  report.screenOverflow = {};
  await page.setViewportSize({ width: 320, height: 640 });
  for (const path of ["/assign/title-abstract", "/criteria/new", "/criteria", "/retrieve", "/studies", recordHref]) {
    await page.goto(origin + path);
    report.screenOverflow[path] = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check(report.screenOverflow[path] <= 0, path + " scrolls sideways at 320px");
  }

  report.problems = problems;
  check(problems.length === 0, "problems in the page: " + problems.join("; "));
  console.log(JSON.stringify(report));
  await browser.close();
})().catch((error) => {
  console.error(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
