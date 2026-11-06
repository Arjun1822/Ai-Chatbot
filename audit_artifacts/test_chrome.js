const puppeteer = require('../frontend/node_modules/puppeteer-core');
const fs = require('fs');
const path = require('path');
const os = require('os');

async function test() {
  const profileDir = path.join(os.tmpdir(), 'puppeteer_test_' + Date.now());

  try {
    const browser = await puppeteer.launch({
      executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
      headless: 'new',
      pipe: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        `--user-data-dir=${profileDir}`,
      ],
    });
    console.log('Chrome launched with pipe!');
    const version = await browser.version();
    console.log('Browser version:', version);
    const page = await browser.newPage();
    await page.setContent('<h1>Orbit AI Test with Chrome</h1>');
    await page.screenshot({ path: 'audit_artifacts/screenshots/test_chrome.png' });
    console.log('Screenshot saved to audit_artifacts/screenshots/test_chrome.png');
    await browser.close();
  } catch (err) {
    console.error('Error launching Chrome:', err.message);
  } finally {
    try {
      fs.rmSync(profileDir, { recursive: true, force: true });
    } catch (e) {}
  }
}

test();
