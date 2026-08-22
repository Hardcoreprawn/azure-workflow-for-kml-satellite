// Executes website/js/app-analysis-preflight.js's buildKmzFromKmlText in a
// real JS runtime (not string-matching) to catch the class of bug string
// assertions can't: wrong ZIP bytes, broken async/Promise wiring, etc.
//
// No npm dependencies — uses only Node's built-in node:test/node:vm/node:zlib,
// consistent with this repo's "no build step" convention for website/js.
// Run with: node --test tests/js/test_build_kmz.js
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const PREFLIGHT_JS = fs.readFileSync(
  path.join(REPO_ROOT, 'website', 'js', 'app-analysis-preflight.js'),
  'utf8'
);
const FFLATE_JS = fs.readFileSync(
  path.join(REPO_ROOT, 'website', 'vendor', 'fflate', 'fflate.js'),
  'utf8'
);

// Loads the real source files into an isolated sandbox and returns the
// module's public API — the same object `window.CanopexAnalysisPreflight`
// would be in a browser.
function loadPreflightModule() {
  const sandbox = {
    window: {},
    document: { getElementById: () => null },
    Promise,
    console,
  };
  vm.createContext(sandbox);
  // A bare vm context has its own native Uint8Array (a core JS built-in) but
  // NOT TextEncoder (a Node/Web-API global, not part of ECMAScript core) --
  // injecting the outer realm's TextEncoder directly would produce
  // Uint8Arrays from the WRONG realm, silently failing fflate's internal
  // `instanceof Uint8Array` checks (confirmed while writing this test: it
  // produced a corrupt multi-thousand-entry archive for larger inputs,
  // purely a test-harness artifact -- real browsers have only one realm,
  // so this can't happen in production). Wrap it so bytes get copied into
  // the sandbox's own Uint8Array.
  const InnerUint8Array = vm.runInContext('Uint8Array', sandbox);
  sandbox.TextEncoder = class {
    encode(str) {
      return new InnerUint8Array(new TextEncoder().encode(str));
    }
  };
  vm.runInContext(FFLATE_JS, sandbox, { filename: 'fflate.js' });
  vm.runInContext(PREFLIGHT_JS, sandbox, { filename: 'app-analysis-preflight.js' });
  return sandbox.window.CanopexAnalysisPreflight;
}

test('buildKmzFromKmlText produces a KMZ readable by Node zlib inflateRaw', async () => {
  const preflight = loadPreflightModule();
  const kmlText = '<?xml version="1.0"?><kml><Document><name>Round-trip test</name></Document></kml>';

  const kmzBytes = await preflight.buildKmzFromKmlText(kmlText);
  // ArrayBuffer.isView (not `instanceof Uint8Array`) is realm-agnostic —
  // kmzBytes correctly belongs to the sandbox's own realm now that the
  // TextEncoder wrapper above avoids the cross-realm Uint8Array mismatch.
  assert.ok(ArrayBuffer.isView(kmzBytes), 'must return a typed array');

  // Parse the ZIP structure ourselves (independent of fflate's own code) to
  // prove the bytes are a genuinely valid, standards-compliant archive.
  const buf = Buffer.from(kmzBytes);
  assert.deepEqual(buf.subarray(0, 4), Buffer.from([0x50, 0x4b, 0x03, 0x04]), 'must start with a local file header signature');

  const compSize = buf.readUInt32LE(18);
  const rawSize = buf.readUInt32LE(22);
  const nameLen = buf.readUInt16LE(26);
  const extraLen = buf.readUInt16LE(28);
  const name = buf.subarray(30, 30 + nameLen).toString('utf8');
  assert.equal(name, 'doc.kml', 'the archived file must be named doc.kml');

  const dataStart = 30 + nameLen + extraLen;
  const compressed = buf.subarray(dataStart, dataStart + compSize);
  const inflated = zlib.inflateRawSync(compressed);

  assert.equal(inflated.length, rawSize, 'decompressed size must match the size recorded in the local file header');
  assert.equal(inflated.toString('utf8'), kmlText, 'decompressed content must exactly match the original KML text');
});

test('buildKmzFromKmlText round-trips a larger KML with many placemarks', async () => {
  const preflight = loadPreflightModule();
  const placemarks = Array.from({ length: 500 }, (_, i) => `<Placemark><name>AOI ${i}</name></Placemark>`).join('');
  const kmlText = `<?xml version="1.0"?><kml><Document>${placemarks}</Document></kml>`;

  const kmzBytes = await preflight.buildKmzFromKmlText(kmlText);
  const buf = Buffer.from(kmzBytes);
  const compSize = buf.readUInt32LE(18);
  const nameLen = buf.readUInt16LE(26);
  const extraLen = buf.readUInt16LE(28);
  const dataStart = 30 + nameLen + extraLen;
  const inflated = zlib.inflateRawSync(buf.subarray(dataStart, dataStart + compSize));

  assert.equal(inflated.toString('utf8'), kmlText);
  assert.ok(compSize < kmlText.length, 'repeated placemark markup must actually compress smaller than the input');
});
