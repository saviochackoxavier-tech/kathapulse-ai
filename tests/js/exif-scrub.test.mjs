/* Runtime test for static/js/capture.js — client-side EXIF scrubbing.
 *
 * A headless browser is not available in this sandbox, so the real capture
 * module is loaded into Node with a minimal DOM shim backed by a genuine JPEG
 * codec (@napi-rs/canvas: skia underneath, the same encoder family browsers
 * use).  That makes this a real encode/decode test of the shipped code, not a
 * static check.
 *
 * Run: node tests/js/exif-scrub.test.mjs   (from tests/js after npm install)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createCanvas, loadImage } from "@napi-rs/canvas";

const here = dirname(fileURLToPath(import.meta.url));
const captureSrc = readFileSync(join(here, "../../static/js/capture.js"), "utf8");

// ---------------------------------------------------------------------------
// Minimal DOM shim
// ---------------------------------------------------------------------------
globalThis.window = globalThis;

globalThis.document = {
  createElement(tag) {
    if (tag !== "canvas") throw new Error("unexpected element " + tag);
    const canvas = createCanvas(1, 1);
    // browsers expose toBlob; sketch exposes toBuffer. Shim the former.
    canvas.toBlob = (callback, type = "image/jpeg", quality = 0.85) => {
      const buffer = canvas.toBuffer("image/jpeg", Math.round(quality * 100));
      callback(new Blob([buffer], { type }));
    };
    return canvas;
  },
};

globalThis.createImageBitmap = async (file) => {
  const image = await loadImage(Buffer.from(file._buffer));
  return {
    width: image.width,
    height: image.height,
    close() {},
    _image: image,
  };
};

// drawImage must accept our bitmap shim.
const originalCreateCanvas = createCanvas;
globalThis.__shim = { createCanvas, originalCreateCanvas };

// Patch the shim canvas's drawImage to unwrap the bitmap.
const realCreate = globalThis.document.createElement;
globalThis.document.createElement = (tag) => {
  const canvas = realCreate(tag);
  const ctx = canvas.getContext("2d");
  const realDraw = ctx.drawImage.bind(ctx);
  ctx.drawImage = (source, ...rest) => realDraw(source._image ?? source, ...rest);
  return canvas;
};

// capture.js expects a `Blob` global (Node has one; keep it).

// ---------------------------------------------------------------------------
// Build a JPEG that really carries EXIF (GPS + timestamp + device make)
// ---------------------------------------------------------------------------
const EXIF_PAYLOAD =
  "Exif\u0000\u0000MM\u0000*" +
  "GPSLatitude=9.9312N GPSLongitude=76.2673E " +
  "DateTimeOriginal=2026:11:20 14:32:07 " +
  "Make=KathaPulseTestDevice Model=KB2001 Serial=SN-8842-TEST";

function withExifSegment(jpeg) {
  assert.equal(jpeg[0], 0xff);
  assert.equal(jpeg[1], 0xd8); // SOI
  const payload = Buffer.from(EXIF_PAYLOAD, "latin1");
  const length = payload.length + 2;
  const segment = Buffer.concat([
    Buffer.from([0xff, 0xe1, (length >> 8) & 0xff, length & 0xff]),
    payload,
  ]);
  return Buffer.concat([jpeg.subarray(0, 2), segment, jpeg.subarray(2)]);
}

// A plausible "photo of a strip": white card with dark printed blocks.
// (Rectangles rather than text so the test does not depend on a font being
// installed in the sandbox -- this test is about the pixel pipe, not OCR.)
const source = originalCreateCanvas(2400, 1800);
const sctx = source.getContext("2d");
sctx.fillStyle = "#ffffff";
sctx.fillRect(0, 0, 2400, 1800);
sctx.fillStyle = "#111111";
sctx.fillRect(140, 780, 900, 120); // "DOLO 650" block
sctx.fillRect(140, 1000, 1500, 90); // "PARACETAMOL 650 mg" block
sctx.fillRect(140, 1300, 700, 70); // expiry / batch line

const dirtyJpeg = withExifSegment(source.toBuffer("image/jpeg", 92));

// ---------------------------------------------------------------------------
// Load the shipped module
// ---------------------------------------------------------------------------
const moduleScope = {};
new Function("window", "document", "Blob", "URL", captureSrc)(
  globalThis,
  globalThis.document,
  globalThis.Blob,
  { createObjectURL: () => "blob:stub", revokeObjectURL: () => {} }
);
const capture = globalThis.KathaPulseCapture;
assert.ok(capture, "capture.js did not expose window.KathaPulseCapture");

// ---------------------------------------------------------------------------
// Run the scrub exactly as the UI does for a gallery upload
// ---------------------------------------------------------------------------
const fakeFile = {
  type: "image/jpeg",
  name: "IMG_20261120_143207.jpg", // phones put GPS + time in the filename too
  size: dirtyJpeg.length,
  _buffer: dirtyJpeg,
};

const result = await capture.scrubFile(fakeFile);
const outBuffer = Buffer.from(await result.blob.arrayBuffer());
const outBytes = outBuffer.toString("latin1");

const checks = [];
const check = (name, ok, detail) => {
  checks.push({ name, ok, detail });
  assert.ok(ok, `${name} -- ${detail}`);
};

// 1. the input really was dirty
check(
  "input JPEG carries EXIF (test validity)",
  dirtyJpeg.includes(Buffer.from("Exif")) && dirtyJpeg.includes(Buffer.from("GPSLatitude")),
  `${dirtyJpeg.length} bytes in`
);

// 2. output has no metadata markers at all
for (const marker of ["Exif", "GPSLatitude", "DateTimeOriginal", "Make=", "Serial="]) {
  check(`output has no "${marker}"`, !outBytes.includes(marker), "marker present after scrub");
}

// 3. Walk the JPEG marker chain and assert no metadata segments survive.
//    APP1 (EXIF/XMP) and COM are the carriers of GPS, timestamps and device
//    identity. An APP2 ICC colour profile may legitimately remain: it is
//    synthesised by the encoder and contains no user data.
function readSegments(buffer) {
  const found = [];
  let pos = 2; // skip SOI
  while (pos + 3 < buffer.length) {
    if (buffer[pos] !== 0xff) break; // malformed or entropy data: stop
    const marker = buffer[pos + 1];
    if (marker === 0xd8 || marker === 0xd9 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      pos += 2;
      continue;
    }
    const length = (buffer[pos + 2] << 8) | buffer[pos + 3];
    if (length < 2) break;
    const body = buffer.subarray(pos + 4, pos + 2 + length);
    found.push({ marker, body });
    if (marker === 0xda) break; // start of scan: pixel data follows
    pos += 2 + length;
  }
  return found;
}

const segments = readSegments(outBuffer);
const app1 = segments.filter((s) => s.marker === 0xe1);
const comments = segments.filter((s) => s.marker === 0xfe);
const otherApp = segments.filter(
  (s) => s.marker >= 0xe2 && s.marker <= 0xef && !s.body.includes(Buffer.from("ICC_PROFILE"))
);
check("no APP1 (EXIF/XMP) segment in output", app1.length === 0, `found ${app1.length}`);
check("no COM segment in output", comments.length === 0, `found ${comments.length}`);
check(
  "no non-ICC APPn segments in output",
  otherApp.length === 0,
  otherApp.map((s) => "0x" + s.marker.toString(16)).join(",")
);

// 4. the image is still a valid, decodable JPEG
const decoded = await loadImage(outBuffer);
check("output decodes as an image", decoded.width > 0 && decoded.height > 0,
  `${decoded.width}x${decoded.height}`);
check("output is downscaled to 1600px long edge", Math.max(decoded.width, decoded.height) === 1600,
  `long edge ${Math.max(decoded.width, decoded.height)}`);
check("aspect ratio preserved", Math.abs(decoded.width / decoded.height - 2400 / 1800) < 0.02,
  `${decoded.width}x${decoded.height}`);

// 5. the encoder never hands back the original blob
check("returned blob differs from the input file", outBuffer.length !== dirtyJpeg.length,
  `${outBuffer.length} vs ${dirtyJpeg.length}`);
check("returned blob is marked as scrubbed", result.source === "file", String(result.source));

// 6. the reprocessed JPEG still contains strip text pixels (not a blank frame)
const outCanvas = originalCreateCanvas(decoded.width, decoded.height);
outCanvas.getContext("2d").drawImage(decoded, 0, 0);
const pixels = outCanvas.getContext("2d").getImageData(0, 0, decoded.width, decoded.height).data;
let dark = 0;
for (let i = 0; i < pixels.length; i += 4) {
  if (pixels[i] < 100 && pixels[i + 1] < 100 && pixels[i + 2] < 100) dark += 1;
}
check("image content survived the re-encode", dark > 500, `${dark} dark pixels`);

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------
console.log("\nEXIF scrub — runtime checks");
for (const { name, ok, detail } of checks) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : " -- " + detail}`);
}
console.log(`\n${checks.length}/${checks.length} checks passed`);
console.log(
  `input ${(dirtyJpeg.length / 1024).toFixed(1)} KB (with EXIF) -> ` +
    `output ${(outBuffer.length / 1024).toFixed(1)} KB (pixels only)\n`
);
