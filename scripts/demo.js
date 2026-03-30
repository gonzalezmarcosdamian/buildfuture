/**
 * BuildFuture — Demo automatizado
 *
 * Uso:
 *   node scripts/demo.js
 *
 * Requiere:
 *   npx playwright install chromium  (solo la primera vez)
 *
 * El script abre la app en modo "presentación":
 *   - Ventana 390×844 (iPhone 14 Pro)
 *   - Navega página por página con pauses para que grabes con Loom / Game Bar
 *   - Presionás ENTER en la terminal para avanzar al siguiente paso
 */

const { chromium } = require("playwright");
const readline = require("readline");

const BASE_URL = "http://localhost:3001";
const VIEWPORT = { width: 390, height: 844 };  // iPhone 14 Pro
const SLOW_MO = 600;  // ms entre acciones

const rl = readline.createInterface({ input: process.stdin, output: process.stdout });

function pause(msg = "Presioná ENTER para continuar...") {
  return new Promise((resolve) => {
    process.stdout.write(`\n  ⏸  ${msg} `);
    rl.once("line", resolve);
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function smoothScroll(page, targetY, steps = 10) {
  const current = await page.evaluate(() => window.scrollY);
  const delta = (targetY - current) / steps;
  for (let i = 0; i < steps; i++) {
    await page.evaluate((d) => window.scrollBy(0, d), delta);
    await sleep(80);
  }
}

async function run() {
  console.log("\n╔══════════════════════════════════════╗");
  console.log("║   BuildFuture — Demo automatizado    ║");
  console.log("╚══════════════════════════════════════╝");
  console.log("\n  Asegurate de tener corriendo:");
  console.log("  • Frontend: http://localhost:3001");
  console.log("  • Backend:  http://localhost:8007");
  console.log("\n  Activá tu grabador (Loom, Game Bar, etc.)");

  await pause("cuando estés listo para empezar");

  const browser = await chromium.launch({
    headless: false,
    slowMo: SLOW_MO,
    args: [
      "--start-maximized",
      "--disable-infobars",
      "--no-default-browser-check",
    ],
  });

  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2,
    colorScheme: "dark",
  });

  const page = await context.newPage();
  page.setDefaultTimeout(15000);

  // ── PANTALLA 1: Dashboard ─────────────────────────────────────────────────
  console.log("\n  [1/5] Dashboard — hero portafolio vs gastos");
  await page.goto(`${BASE_URL}/dashboard`);
  await page.waitForLoadState("networkidle");
  await sleep(1500);

  // Mostrar hero
  await smoothScroll(page, 0);
  await sleep(2000);

  await pause("mostrando hero — ENTER para hacer scroll al presupuesto");

  // Scroll al presupuesto del mes
  await smoothScroll(page, 380, 15);
  await sleep(1500);

  await pause("mostrando presupuesto — ENTER para scroll a racha");

  // Scroll a la racha
  await smoothScroll(page, 580, 10);
  await sleep(1500);

  await pause("mostrando racha — ENTER para ir a Presupuesto");

  // ── PANTALLA 2: Presupuesto ───────────────────────────────────────────────
  console.log("\n  [2/5] Presupuesto — editor de categorías");
  await page.goto(`${BASE_URL}/budget`);
  await page.waitForLoadState("networkidle");
  await sleep(1500);

  // Mostrar sección de ingresos
  await smoothScroll(page, 0);
  await sleep(2000);

  await pause("mostrando ingreso bruto — ENTER para scroll a distribución");

  // Scroll a las categorías
  await smoothScroll(page, 500, 15);
  await sleep(1500);

  // Mover un slider para mostrar interactividad
  const sliders = page.locator('input[type="range"]');
  const count = await sliders.count();
  if (count > 1) {
    const slider = sliders.nth(1);
    const box = await slider.boundingBox();
    if (box) {
      await page.mouse.move(box.x + box.width * 0.4, box.y + box.height / 2);
      await sleep(400);
      await page.mouse.down();
      await page.mouse.move(box.x + box.width * 0.55, box.y + box.height / 2, { steps: 10 });
      await sleep(300);
      await page.mouse.up();
      await sleep(800);
    }
  }

  await pause("mostrando sliders — ENTER para ir a Metas");

  // ── PANTALLA 3: Metas ─────────────────────────────────────────────────────
  console.log("\n  [3/5] Metas — categorías desbloqueadas + roadmap");
  await page.goto(`${BASE_URL}/goals`);
  await page.waitForLoadState("networkidle");
  await sleep(1500);

  // Mostrar resumen del juego
  await smoothScroll(page, 0);
  await sleep(2000);

  await pause("mostrando resumen del juego — ENTER para scroll a roadmap");

  // Scroll al roadmap de desbloqueo
  await smoothScroll(page, 500, 15);
  await sleep(1500);

  await pause("mostrando roadmap — ENTER para scroll a racha");

  // Scroll a la racha
  await smoothScroll(page, 900, 12);
  await sleep(1500);

  await pause("mostrando racha de inversión — ENTER para ir a Portafolio");

  // ── PANTALLA 4: Portafolio ────────────────────────────────────────────────
  console.log("\n  [4/5] Portafolio — posiciones actuales");
  await page.goto(`${BASE_URL}/portfolio`);
  await page.waitForLoadState("networkidle");
  await sleep(1500);

  await smoothScroll(page, 0);
  await sleep(2000);

  await smoothScroll(page, 350, 12);
  await sleep(1500);

  await pause("mostrando portafolio — ENTER para ir a Recomendaciones IA");

  // ── PANTALLA 5: Recomendaciones ───────────────────────────────────────────
  console.log("\n  [5/5] Recomendaciones IA — volvemos al dashboard");
  await page.goto(`${BASE_URL}/dashboard`);
  await page.waitForLoadState("networkidle");
  await sleep(1000);

  // Scroll directo a las recomendaciones
  await smoothScroll(page, 900, 20);
  await sleep(1500);

  // Cambiar perfil de riesgo
  const agresivo = page.locator("button", { hasText: "Agresivo" });
  if (await agresivo.isVisible()) {
    await agresivo.click();
    await sleep(2500);
  }

  const conservador = page.locator("button", { hasText: "Conservador" });
  if (await conservador.isVisible()) {
    await conservador.click();
    await sleep(2500);
  }

  await pause("fin de la demo — ENTER para cerrar");

  // ── Cierre ────────────────────────────────────────────────────────────────
  await browser.close();
  rl.close();

  console.log("\n  Demo completada. Pará la grabación.\n");
}

run().catch((err) => {
  console.error("\n  Error:", err.message);
  rl.close();
  process.exit(1);
});
