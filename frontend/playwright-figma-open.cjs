const { chromium } = require("./node_modules/playwright");

(async () => {
  const browser = await chromium.launch({
    headless: false,
    slowMo: 100,
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();
  await page.goto(
    "https://www.figma.com/make/kLt4wzLHStiz2YN7XQ1nKM/Minimalist-sidebar-component--Copy-?p=f&t=YWuUo8Rbx2yJZX6A-0",
    { waitUntil: "domcontentloaded", timeout: 60000 },
  );

  console.log("Figma window opened. Keep this process running while logging in.");
  setInterval(() => {}, 60000);
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
