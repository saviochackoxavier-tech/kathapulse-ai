/* Local audio pack — loader contract and fallback statuses.
 *
 * The pack ships empty today, so the important behaviour is not "plays audio":
 * it is that every failure path answers with a status instead of throwing, so
 * the warning always falls through to the device voice and then to text.
 *
 * Run: node audio-pack.test.mjs   (from tests/js)
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, "../../static/js/audio-pack.js"), "utf8");

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (err) {
    results.push({ name, ok: false, detail: err.message });
  }
}

/** Fresh module instance with a scripted window: no jsdom, no network. */
function makePack({ manifest, fetchFails = false, playRejects = false } = {}) {
  const played = [];
  const context = {
    Promise,
    fetch: async (url) => {
      if (fetchFails) throw new Error("offline");
      return {
        ok: true,
        status: 200,
        json: async () => (typeof manifest === "function" ? manifest() : manifest),
      };
    },
    Audio: function Audio(src) {
      this.src = src;
      this.preload = "";
      played.push(src);
      this.play = () => (playRejects ? Promise.reject(new Error("NotAllowedError")) : Promise.resolve());
      this.pause = () => {};
    },
  };
  context.window = context;
  new Function("window", source)(context);
  return { pack: context.AudioPack, played };
}

const CLIP = "/static/audio/ml/DUPLICATE_SALT.webm";
const WITH_CLIP = { schema: 1, version: "3", clips: { "ml:DUPLICATE_SALT": CLIP } };

await test("empty pack loads and reports zero clips", async () => {
  const { pack } = makePack({ manifest: { schema: 1, version: "0", clips: {} } });
  const data = await pack.load();
  assert.equal(data.version, "0");
  assert.deepEqual(data.clips, {});
  assert.equal(pack.status().clips, 0);
});

await test("canPlay is false for a missing key and true for a present one", async () => {
  const empty = makePack({ manifest: { schema: 1, version: "0", clips: {} } });
  assert.equal(await empty.pack.canPlay("ml", "DUPLICATE_SALT"), false);

  const withClip = makePack({ manifest: WITH_CLIP });
  assert.equal(await withClip.pack.canPlay("ml", "DUPLICATE_SALT"), true);
  assert.equal(await withClip.pack.canPlay("hi", "DUPLICATE_SALT"), false);
});

await test("play() returns 'played' and hands the clip to the audio element", async () => {
  const { pack, played } = makePack({ manifest: WITH_CLIP });
  const result = await pack.play("ml", "DUPLICATE_SALT", { rate: 0.85 });
  assert.equal(result.status, "played");
  assert.equal(result.clip, CLIP);
  assert.deepEqual(played, [CLIP]);
});

await test("an empty pack answers 'unavailable' instead of throwing", async () => {
  const { pack } = makePack({ manifest: { schema: 1, version: "0", clips: {} } });
  const result = await pack.play("ml", "DUPLICATE_SALT");
  assert.equal(result.status, "unavailable");
  assert.match(result.reason, /no clip/);
});

await test("a failed manifest fetch degrades to an empty pack with a recorded error", async () => {
  const { pack } = makePack({ fetchFails: true });
  const data = await pack.load();
  assert.deepEqual(data.clips, {});
  assert.equal(pack.status().loaded, true);
  assert.equal(pack.status().error, "offline");
  const result = await pack.play("ml", "INTRO");
  assert.equal(result.status, "unavailable");
});

await test("autoplay rejection is reported as 'blocked', not an exception", async () => {
  const { pack } = makePack({ manifest: WITH_CLIP, playRejects: true });
  const result = await pack.play("ml", "DUPLICATE_SALT");
  assert.equal(result.status, "blocked");
  assert.match(result.reason, /NotAllowedError/);
});

await test("path traversal in a manifest value is dropped", async () => {
  const { pack } = makePack({
    manifest: { schema: 1, version: "9", clips: { "ml:BAD": "../../secret.webm", "ml:OK": CLIP } },
  });
  const data = await pack.load();
  assert.deepEqual(Object.keys(data.clips), ["ml:OK"]);
});

const failed = results.filter((r) => !r.ok);
for (const r of results) console.log(`${r.ok ? "ok  " : "FAIL"} ${r.name}${r.ok ? "" : " — " + r.detail}`);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
