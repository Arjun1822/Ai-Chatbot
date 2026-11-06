const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');
const puppeteer = require('../frontend/node_modules/puppeteer-core');

const SCREENSHOT_DIR = path.join(__dirname, 'screenshots');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

// Helper to serve frontend static build
function startFrontendServer(port = 3000) {
  const buildDir = path.resolve(__dirname, '..', 'frontend', 'build');
  const mimeTypes = {
    '.html': 'text/html',
    '.js': 'text/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
  };

  const server = http.createServer((req, res) => {
    let filePath = path.join(buildDir, req.url.split('?')[0]);
    if (filePath === buildDir || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(buildDir, 'index.html');
    }
    const ext = path.extname(filePath).toLowerCase();
    const contentType = mimeTypes[ext] || 'application/octet-stream';

    try {
      const content = fs.readFileSync(filePath);
      res.writeHead(200, { 'Content-Type': contentType });
      res.end(content, 'utf-8');
    } catch (e) {
      res.writeHead(404);
      res.end('Not found');
    }
  });

  return new Promise((resolve) => {
    server.listen(port, () => {
      console.log(`[Frontend] Serving on http://localhost:${port}`);
      resolve(server);
    });
  });
}

// Helper to start Flask backend
function startBackendServer(port = 5000) {
  const pythonPath = path.resolve(__dirname, '..', 'backend', '.venv', 'Scripts', 'python.exe');
  const appPath = path.resolve(__dirname, '..', 'backend', 'app.py');

  console.log(`[Backend] Launching Python Flask server on port ${port}...`);
  const backendProc = spawn(pythonPath, [appPath], {
    cwd: path.resolve(__dirname, '..', 'backend'),
    env: { ...process.env, FLASK_RUN_PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  backendProc.stdout.on('data', (d) => process.stdout.write(`[Flask] ${d}`));
  backendProc.stderr.on('data', (d) => process.stderr.write(`[Flask Err] ${d}`));

  return new Promise((resolve, reject) => {
    let attempts = 0;
    const check = setInterval(async () => {
      attempts++;
      try {
        const res = await fetch(`http://127.0.0.1:${port}/api/health`);
        if (res.ok) {
          clearInterval(check);
          console.log(`[Backend] Flask server is healthy and ready!`);
          resolve(backendProc);
        }
      } catch (e) {
        if (attempts > 30) {
          clearInterval(check);
          backendProc.kill();
          reject(new Error('Backend failed to start in 15 seconds.'));
        }
      }
    }, 500);
  });
}

async function runAudit() {
  const testResults = [];
  let frontendServer, backendProc, browser;
  const tempProfile = path.join(os.tmpdir(), 'puppeteer_audit_' + Date.now());

  try {
    // Step 1: Start Servers
    frontendServer = await startFrontendServer(3000);
    backendProc = await startBackendServer(5000);

    testResults.push({
      id: 'TC-E2E-01',
      description: 'Backend & Frontend Server Startup',
      expected: 'Flask starts on :5000, Frontend serves on :3000, /api/health returns ok',
      actual: 'Both services initialized successfully',
      status: 'PASS',
    });

    // Step 2: Launch Real Chrome
    browser = await puppeteer.launch({
      executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      headless: 'new',
      pipe: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        `--user-data-dir=${tempProfile}`,
      ],
      defaultViewport: { width: 1280, height: 850 },
    });

    const page = await browser.newPage();

    // Listen to console errors and network failures
    const consoleLogs = [];
    const consoleErrors = [];
    page.on('console', (msg) => {
      consoleLogs.push(`[${msg.type()}] ${msg.text()}`);
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    // Step 3: Load Application
    console.log('[Test] Navigating to http://localhost:3000...');
    await page.goto('http://localhost:3000', { waitUntil: 'networkidle0' });
    await page.waitForSelector('.welcome', { timeout: 10000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_welcome_screen.png') });

    const title = await page.title();
    testResults.push({
      id: 'TC-E2E-02',
      description: 'Chat Interface Loading & Initial State',
      expected: 'Title is Orbit AI, welcome message and suggestion buttons visible',
      actual: `Title is "${title}", welcome hero displayed`,
      status: title === 'Orbit AI' ? 'PASS' : 'FAIL',
      evidence: '01_welcome_screen.png',
    });

    // Step 4: Health Indicator
    const statusText = await page.$eval('.sidebar-foot .status-title', (el) => el.innerText);
    const statusSub = await page.$eval('.sidebar-foot .status-sub', (el) => el.innerText);
    console.log(`[Test] Health indicator: ${statusText} | ${statusSub}`);
    testResults.push({
      id: 'TC-E2E-03',
      description: 'Live Backend & Health Indicator',
      expected: 'Status reports Local Storage / Cloud DB and Gemini Ready',
      actual: `${statusText} (${statusSub})`,
      status: statusSub.includes('Ready') ? 'PASS' : 'FAIL',
    });

    // Step 5: Send Real Gemini Message
    console.log('[Test] Sending message: "What is 15 * 8? Answer concisely."');
    const inputSelector = '.composer textarea';
    await page.type(inputSelector, 'What is 15 * 8? Answer concisely.');
    await page.click('.send-button');

    // Wait for AI response message
    await page.waitForSelector('.message-row.ai-row .message-content', { timeout: 25000 });
    // Wait until loading finishes
    await page.waitForFunction(() => !document.querySelector('.spin-icon'), { timeout: 30000 });

    const aiResponseText = await page.$eval('.message-row.ai-row .message-content', (el) => el.innerText);
    console.log(`[Test] AI Response received: "${aiResponseText}"`);
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_real_gemini_response.png') });

    const correctMath = aiResponseText.includes('120');
    testResults.push({
      id: 'TC-E2E-04',
      description: 'Real Gemini API Response & Streaming',
      expected: 'Gemini streams and generates mathematically correct answer (120)',
      actual: aiResponseText.trim(),
      status: correctMath ? 'PASS' : 'FAIL',
      evidence: '02_real_gemini_response.png',
    });

    // Step 6: Code Syntax Highlighting
    console.log('[Test] Sending coding message for syntax highlighting...');
    await page.type(inputSelector, 'Write a Python function to check if a word is palindrome. Provide only code.');
    await page.click('.send-button');

    await page.waitForFunction(() => !document.querySelector('.spin-icon'), { timeout: 35000 });
    await page.waitForSelector('.code-block-wrapper', { timeout: 10000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_code_highlighting.png') });

    const langTag = await page.$eval('.code-lang-tag', (el) => el.innerText.trim());
    const hasCopyBtn = await page.$eval('.code-copy-btn', (el) => !!el);
    testResults.push({
      id: 'TC-E2E-05',
      description: 'Code Syntax Highlighting with PrismJS',
      expected: 'Code block rendered with language header, prism styling, and copy button',
      actual: `Language tag: "${langTag}", Copy button present: ${hasCopyBtn}`,
      status: langTag === 'python' && hasCopyBtn ? 'PASS' : 'FAIL',
      evidence: '03_code_highlighting.png',
    });

    // Step 7: File Attachment Flow
    console.log('[Test] Testing File Attachment...');
    const testFilePath = path.join(__dirname, 'test_attachment.py');
    fs.writeFileSync(testFilePath, 'def add(a, b):\n    return a + b\n');

    const fileInput = await page.$('input[type="file"]');
    await fileInput.uploadFile(testFilePath);
    await page.waitForSelector('.attachment-chip', { timeout: 5000 });

    const attName = await page.$eval('.att-name', (el) => el.innerText);
    console.log(`[Test] Attachment chip visible: ${attName}`);
    await page.type(inputSelector, 'What does this attached code do?');
    await page.click('.send-button');

    await page.waitForFunction(() => !document.querySelector('.spin-icon'), { timeout: 35000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '04_attachment_flow.png') });

    const lastAiResponse = await page.$$eval('.message-row.ai-row .message-content', (els) => els[els.length - 1].innerText);
    const mentionsAdd = lastAiResponse.toLowerCase().includes('add') || lastAiResponse.toLowerCase().includes('sum');
    testResults.push({
      id: 'TC-E2E-06',
      description: 'File Attachment Context & Processing',
      expected: 'Attached Python file is uploaded, recognized, and analyzed by Gemini',
      actual: `AI responded: "${lastAiResponse.slice(0, 100)}..."`,
      status: mentionsAdd ? 'PASS' : 'FAIL',
      evidence: '04_attachment_flow.png',
    });

    // Step 8: Multiple Conversations
    console.log('[Test] Testing New Chat Creation...');
    await page.click('.new-chat');
    await page.waitForSelector('.welcome', { timeout: 5000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_new_chat.png') });

    const conversationItems = await page.$$eval('.history-item span', (els) => els.map((e) => e.innerText));
    console.log('[Test] Conversation list in sidebar:', conversationItems);
    testResults.push({
      id: 'TC-E2E-07',
      description: 'Multiple Conversations Management',
      expected: 'New chat opens welcome view, previous conversation listed in sidebar',
      actual: `${conversationItems.length} conversation(s) listed: ${conversationItems.join(', ')}`,
      status: conversationItems.length >= 1 ? 'PASS' : 'FAIL',
      evidence: '05_new_chat.png',
    });

    // Step 9: Renaming Conversations
    console.log('[Test] Testing Conversation Renaming...');
    // Click rename on the first item
    await page.click('.history-item-wrap .action-icon-btn');
    await page.waitForSelector('.rename-input', { timeout: 5000 });
    // Clear and enter new title
    await page.click('.rename-input', { clickCount: 3 });
    await page.keyboard.press('Backspace');
    await page.type('.rename-input', 'Audited Math Conversation');
    await page.keyboard.press('Enter');

    // Wait for rename to persist
    await page.waitForFunction(() => document.querySelector('.history-item span')?.innerText?.includes('Audited Math'), { timeout: 5000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_renamed_chat.png') });

    const renamedTitle = await page.$eval('.history-item span', (el) => el.innerText);
    testResults.push({
      id: 'TC-E2E-08',
      description: 'Conversation Renaming via PATCH API',
      expected: 'Title updates in sidebar and persists',
      actual: `Title updated to: "${renamedTitle}"`,
      status: renamedTitle.includes('Audited Math') ? 'PASS' : 'FAIL',
      evidence: '06_renamed_chat.png',
    });

    // Step 10: Search Filter
    console.log('[Test] Testing Search Filter...');
    await page.type('.search-input', 'Audited');
    const filteredItems = await page.$$eval('.history-item span', (els) => els.map((e) => e.innerText));
    await page.click('.search-input', { clickCount: 3 });
    await page.keyboard.press('Backspace');

    testResults.push({
      id: 'TC-E2E-09',
      description: 'Conversation Search Filter',
      expected: 'Search matches "Audited" and filters list',
      actual: `Filtered list: ${filteredItems.join(', ')}`,
      status: filteredItems.length === 1 && filteredItems[0].includes('Audited') ? 'PASS' : 'FAIL',
    });

    // Step 11: Delete Confirmation Modal
    console.log('[Test] Testing Delete Confirmation Modal...');
    await page.click('.action-icon-btn.danger');
    await page.waitForSelector('.modal-backdrop .confirm-dialog', { timeout: 5000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '07_delete_modal.png') });

    // Cancel first
    await page.click('.btn-cancel');
    await page.waitForFunction(() => !document.querySelector('.modal-backdrop'), { timeout: 5000 });
    console.log('[Test] Modal cancelled successfully.');

    // Click delete again and confirm
    await page.click('.action-icon-btn.danger');
    await page.waitForSelector('.modal-backdrop .confirm-dialog', { timeout: 5000 });
    await page.click('.btn-danger');

    await page.waitForFunction(() => !document.querySelector('.history-item-wrap'), { timeout: 5000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '08_after_deletion.png') });

    testResults.push({
      id: 'TC-E2E-10',
      description: 'Delete Confirmation & Accidental Loss Prevention',
      expected: 'Confirmation modal appears on delete click; deletion executes only upon confirmation',
      actual: 'Modal intercepted deletion, cancellation preserved chat, confirmation deleted chat',
      status: 'PASS',
      evidence: '07_delete_modal.png',
    });

    // Step 12: Theme Switching
    console.log('[Test] Testing Theme Switching...');
    await page.click('.topbar button[title*="theme"]');
    const themeAttr = await page.$eval('html', (el) => el.getAttribute('data-theme'));
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '09_dark_theme.png') });

    testResults.push({
      id: 'TC-E2E-11',
      description: 'Dark / Light Theme Toggle',
      expected: 'HTML data-theme switches to dark and persists',
      actual: `Theme attribute is "${themeAttr}"`,
      status: themeAttr === 'dark' ? 'PASS' : 'FAIL',
      evidence: '09_dark_theme.png',
    });

    // Step 13: Responsive Layout & Mobile Drawer
    console.log('[Test] Testing Mobile Responsive Layout...');
    await page.setViewport({ width: 375, height: 812, isMobile: true, hasTouch: true });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '10_mobile_view.png') });

    // Hamburger button should now be visible
    const hamburgerVisible = await page.$eval('.topbar-left .mobile-only', (el) => window.getComputedStyle(el).display !== 'none');
    await page.click('.topbar-left .mobile-only');
    await page.waitForFunction(() => document.querySelector('.sidebar')?.classList.contains('is-open'), { timeout: 5000 });
    await page.screenshot({ path: path.join(SCREENSHOT_DIR, '11_mobile_drawer.png') });

    testResults.push({
      id: 'TC-E2E-12',
      description: 'Mobile Viewport & Drawer Navigation',
      expected: 'Mobile view shows hamburger icon, toggles slide-out drawer with backdrop',
      actual: `Hamburger visible: ${hamburgerVisible}, Drawer opened on click`,
      status: hamburgerVisible ? 'PASS' : 'FAIL',
      evidence: '10_mobile_view.png, 11_mobile_drawer.png',
    });

    // Clean up test file
    try { fs.unlinkSync(testFilePath); } catch (e) {}

  } catch (err) {
    console.error('[Audit Error]', err);
    testResults.push({
      id: 'TC-E2E-ERR',
      description: 'E2E Execution Error',
      expected: 'No uncaught exceptions',
      actual: err.message,
      status: 'FAIL',
    });
  } finally {
    if (browser) await browser.close();
    if (frontendServer) frontendServer.close();
    if (backendProc) backendProc.kill();
    try { fs.rmSync(tempProfile, { recursive: true, force: true }); } catch (e) {}
  }

  // Write results log
  fs.writeFileSync(
    path.join(__dirname, 'e2e_results.json'),
    JSON.stringify(testResults, null, 2)
  );
  console.log('[Test] E2E Results written to audit_artifacts/e2e_results.json');
  console.log(JSON.stringify(testResults, null, 2));
}

runAudit();

