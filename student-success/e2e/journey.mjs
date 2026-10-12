// End-to-end journey through the real UI and API:
//   seed -> sign in -> dashboard -> enter data -> verify the score -> assign an intervention -> record its outcome,
// then confirm a student can see only their own record.
//
// Local (default): starts backend/local_server.py on a fresh SQLite database and seeds the demo dataset.
//   node e2e/journey.mjs
// Against a deployment, sign in is via Cognito, so pass a pre-obtained ID token for a mentor test account:
//   E2E_BASE_URL=https://dxxxx.cloudfront.net E2E_ID_TOKEN=... node e2e/journey.mjs
// Needs Playwright (npm i -g playwright, or PW=/path/to/playwright) and a built frontend (cd frontend && npm run build).
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PW || 'playwright');
const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const py = process.env.PYTHON || join(root, '.venv', 'bin', 'python');
const remote = process.env.E2E_BASE_URL;
const port = process.env.E2E_PORT || '8010';
const base = remote || `http://127.0.0.1:${port}`;
const SID = process.env.E2E_STUDENT || 'CSE24003';
const PERIOD = '2026-09';

const step = (s) => console.log(`✓ ${s}`);
function check(cond, msg) { if (!cond) throw new Error(`FAILED: ${msg}`); }

let server;
async function startLocal() {
  const env = { ...process.env, AUTH_MODE: 'local-demo', STORAGE: 'sqlite', SQLITE_PATH: join(mkdtempSync(join(tmpdir(), 'ssp-e2e-')), 'e2e.db'),
    LOCAL_DEMO_SECRET: 'e2e-only-secret', PORT: port };
  const seed = spawnSync(py, ['-m', 'app.seed'], { cwd: join(root, 'backend'), env, encoding: 'utf8' });
  check(seed.status === 0, `seed failed: ${seed.stderr}`);
  step(`seeded: ${seed.stdout.trim()}`);
  server = spawn(py, ['local_server.py'], { cwd: join(root, 'backend'), env, stdio: 'ignore' });
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* starting */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('server did not start');
}

async function signIn(page, username) {
  if (remote) {
    check(process.env.E2E_ID_TOKEN, 'E2E_ID_TOKEN is required against a deployment');
    await page.goto(`${base}/login`);
    await page.evaluate((t) => {
      const exp = JSON.parse(atob(t.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))).exp;
      sessionStorage.setItem('ssp.session', JSON.stringify({ idToken: t, exp }));
    }, process.env.E2E_ID_TOKEN);
    await page.goto(`${base}/`);
  } else {
    await page.goto(`${base}/login`);
    await page.getByText(username, { exact: true }).click();
  }
  await page.waitForURL((u) => !u.pathname.startsWith('/login'));
}

async function main() {
  if (!remote) await startLocal();
  const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
  const errors = [];
  try {
    const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => errors.push(e.message));
    const writes = [];
    page.on('response', (r) => { if (['PUT', 'POST', 'PATCH'].includes(r.request().method()) && r.url().includes('/api/')) writes.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });

    // 1. sign in and open the dashboard on the demo dataset
    await signIn(page, 'mentor.arjun');
    await page.goto(`${base}/overview`);
    await page.getByLabel('Dataset').selectOption('demo');
    await page.getByText('Average Success Score').waitFor();
    step('mentor signed in; dashboard loaded on the demo dataset');

    // 2. score before
    await page.goto(`${base}/students/demo/${SID}`);
    await page.getByRole('tab', { name: 'Score & trends' }).click();
    await page.getByText('How the score is calculated').waitFor();
    const lmsRow = page.locator('tr', { hasText: 'assignment_completion_pct' });
    const lmsBefore = (await lmsRow.count()) ? (await lmsRow.locator('td').nth(2).textContent())?.trim() : 'not recorded';
    const lmsStatusBefore = (await page.locator('tr', { hasText: 'LMS' }).first().textContent()) || '';
    step(`profile ${SID}: LMS ${/Missing/.test(lmsStatusBefore) ? 'missing (excluded from score)' : 'included'}; assignment completion before = ${lmsBefore}`);

    // 3. enter LMS data through the role-specific form
    await page.goto(`${base}/entry`);
    await page.getByRole('button', { name: /LMS summary/ }).click();
    await page.getByLabel('Reporting period').selectOption(PERIOD);
    const row = page.locator('tr', { hasText: SID });
    await row.waitFor();
    await row.getByLabel(/assignments_due/).fill('12');
    await row.getByLabel(/assignments_submitted/).fill('12');
    await row.getByLabel(/logins/).fill('40');
    await page.getByRole('button', { name: /Save 1 changed row/ }).click();
    await row.getByText('Saved').waitFor();
    step('LMS record saved through the form');

    // 4. the score reflects it
    await page.goto(`${base}/students/demo/${SID}`);
    await page.getByRole('tab', { name: 'Score & trends' }).click();
    await page.getByText('How the score is calculated').waitFor();
    const lmsAfter = (await page.locator('tr', { hasText: 'assignment_completion_pct' }).locator('td').nth(2).textContent())?.trim();
    const lmsStatusAfter = (await page.locator('tr', { hasText: 'LMS' }).first().textContent()) || '';
    check(/Included/.test(lmsStatusAfter), 'LMS component is included after entry');
    check(lmsAfter === '100', `assignment completion should be 100 after entry, got ${lmsAfter}`);
    step('score recalculated: assignment completion now 100%');

    // 5. assign an intervention after reviewing the evidence
    await page.getByRole('tab', { name: /Risks/ }).click();
    await page.getByRole('button', { name: /without a recommendation/ }).waitFor();
    const rec = page.getByRole('button', { name: 'Review and assign' }).first();
    if (await rec.count()) await rec.click();
    else await page.getByRole('button', { name: /without a recommendation/ }).click();
    const title = page.getByLabel('Title');
    if (!(await title.inputValue())) await title.fill('E2E mentoring plan');
    await page.getByRole('button', { name: 'Assign', exact: true }).isDisabled().then((d) => check(d, 'Assign must be disabled until reviewed'));
    await page.getByLabel(/I have reviewed this recommendation/).check();
    await page.getByRole('button', { name: 'Assign', exact: true }).click();
    await page.getByText('Intervention assigned.').waitFor();
    step('intervention assigned after confirming review');

    // 6. record the outcome and complete it
    const card = page.locator('section.card', { has: page.locator('summary', { hasText: 'Update' }) }).first();
    await card.locator('summary', { hasText: 'Update' }).click();
    await card.getByRole('combobox', { name: /^Status/ }).selectOption('Completed');
    await card.getByRole('combobox', { name: /^Outcome/ }).selectOption('improved');
    await card.getByLabel('Outcome note').fill('Submitted all assignments this month.');
    await card.getByRole('button', { name: 'Save' }).click();
    await page.getByText('Intervention updated.').waitFor();
    await page.getByText(/an association, not proof|Not comparable/).first().waitFor();
    step('outcome recorded; before/after shown without a causal claim (or marked not comparable)');

    // 7. a confidential note
    await page.getByLabel('Note').first().fill('Discussed workload privately.');
    await page.getByRole('combobox', { name: 'Visibility' }).first().selectOption('confidential');
    await page.getByRole('button', { name: 'Add', exact: true }).first().click();
    await page.getByText('Note added.').waitFor();
    step('confidential note added');

    check(writes.every((w) => /^2\d\d /.test(w)), `all writes succeed: ${writes.join(', ')}`);
    step(`${writes.length} write requests, all 2xx (payload hash + app token headers accepted)`);

    if (!remote) {
      // 8. a student sees only their own record and no notes
      const s = await (await browser.newContext()).newPage();
      await signIn(s, 'student.cse');
      await s.getByText('Success Score').first().waitFor();
      check(!(await s.getByText('Discussed workload privately').count()), 'students never see notes');
      await s.goto(`${base}/students/demo/${SID}`);
      await s.getByText(/don't have access/).waitFor();
      step('student sees own progress only; other students are refused');
    }
    check(!errors.length, `no page errors: ${errors.join('; ')}`);
    console.log('\nE2E journey passed.');
  } catch (e) {
    const shot = join(tmpdir(), 'ssp-e2e-failure.png');
    await browser.contexts()[0]?.pages()[0]?.screenshot({ path: shot, fullPage: true }).catch(() => undefined);
    console.error(`Screenshot of the failure: ${shot}`);
    throw e;
  } finally {
    await browser.close();
    server?.kill();
  }
}

main().catch((e) => { console.error(e.message || e); server?.kill(); process.exit(1); });
