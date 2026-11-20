/* Generate a realistic Indian medicine-strip photograph for demo + live vision
 * testing. Writes ../../samples/strip-dolo.jpg (1600x1000, JPEG).
 *
 * Run from tests/js:  node make-sample-strip.mjs
 */

import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createCanvas, GlobalFonts } from "@napi-rs/canvas";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "../../samples");
const outFile = join(outDir, "strip-dolo.jpg");

// A font is required: without one, canvas silently draws nothing and the image
// would be blank white (useless for OCR or a vision model).
const FONT_DIRS = [
  "/opt/freestyle/python/lib/python3.12/site-packages/matplotlib/mpl-data/fonts/ttf",
  "/usr/share/fonts/truetype/dejavu",
  "/usr/share/fonts",
];

function findFont() {
  for (const dir of FONT_DIRS) {
    if (!existsSync(dir)) continue;
    try {
      for (const file of readdirSync(dir)) {
        if (/^DejaVuSans-Bold\.ttf$/i.test(file)) return join(dir, file);
      }
      for (const file of readdirSync(dir)) {
        if (/\.ttf$/i.test(file)) return join(dir, file);
      }
    } catch {
      continue;
    }
  }
  return null;
}

const fontPath = findFont();
if (!fontPath) {
  console.error("No TTF font found — cannot render the sample strip.");
  process.exit(1);
}
GlobalFonts.registerFromPath(fontPath, "StripSans");

const W = 1600;
const H = 1000;
const canvas = createCanvas(W, H);
const ctx = canvas.getContext("2d");

// Blister foil: light silver card with a subtle sheen.
ctx.fillStyle = "#f4f5f7";
ctx.fillRect(0, 0, W, H);
const sheen = ctx.createLinearGradient(0, 0, W, H);
sheen.addColorStop(0, "rgba(255,255,255,0.9)");
sheen.addColorStop(0.55, "rgba(226,232,240,0.55)");
sheen.addColorStop(1, "rgba(255,255,255,0.85)");
ctx.fillStyle = sheen;
ctx.fillRect(0, 0, W, H);

// Brand band (the part a patient actually reads).
ctx.fillStyle = "#0b3d91";
ctx.fillRect(0, 0, W, 210);

ctx.fillStyle = "#ffffff";
ctx.font = "bold 116px StripSans";
ctx.fillText("DOLO 650", 70, 145);

ctx.fillStyle = "#111827";
ctx.font = "bold 74px StripSans";
ctx.fillText("PARACETAMOL 650 mg", 70, 330);

ctx.font = "54px StripSans";
ctx.fillText("TABLETS  ·  15 TABLETS", 70, 420);
ctx.fillText("For fever and pain relief", 70, 495);

// Batch / expiry block, plus the usual strip boilerplate the parser must ignore.
ctx.font = "40px StripSans";
ctx.fillStyle = "#374151";
ctx.fillText("B.No. DLX2291   Mfg. 03/2026   Exp. 02/2029", 70, 610);
ctx.fillText("Mfd. by MICRO LABS LTD, BENGALURU", 70, 675);
ctx.fillText("MRP Rs. 30.00 (Incl. of all taxes)", 70, 740);

// Blister domes, for realism.
ctx.fillStyle = "rgba(148,163,184,0.35)";
for (let i = 0; i < 5; i += 1) {
  ctx.beginPath();
  ctx.ellipse(200 + i * 280, 880, 90, 55, 0, 0, Math.PI * 2);
  ctx.fill();
}

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, canvas.toBuffer("image/jpeg", 92));

console.log(`wrote ${outFile} (${(canvas.toBuffer("image/jpeg", 92).length / 1024).toFixed(1)} KB)`);
