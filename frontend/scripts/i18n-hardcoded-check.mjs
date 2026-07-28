import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const SRC_DIR = path.join(ROOT, 'src');
const BASELINE_PATH = path.join(ROOT, 'scripts', 'i18n-hardcoded-baseline.json');
const WRITE_BASELINE = process.argv.includes('--write-baseline');
const REPORT = process.argv.includes('--report');

const IGNORE_FILES = new Set([
  path.normalize('src/i18n/config.ts'),
  path.normalize('src/i18n/locales/en.json'),
  path.normalize('src/i18n/locales/ru.json'),
  path.normalize('src/components/msmAsciiVariants.ts'),
  path.normalize('src/components/UIIcon.tsx'),
  path.normalize('src/vite-env.d.ts'),
]);

const IGNORED_SUBSTRINGS = [
  'http://',
  'https://',
  '/api/',
  'className',
  'btn btn-',
  'form-control',
  'spinner-border',
  'react',
  'i18next',
  'axios',
  'localhost',
  'window.',
  'document.',
  'import ',
  'export ',
];

function collectFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...collectFiles(full));
      continue;
    }
    if (!/\.(tsx|ts)$/.test(entry.name)) continue;
    const rel = path.relative(ROOT, full);
    if (IGNORE_FILES.has(path.normalize(rel))) continue;
    out.push(full);
  }
  return out;
}

function isLikelyUserFacingText(text) {
  const t = text.trim();
  if (t.length < 2) return false;
  if (/[{}]/.test(t) || t.includes('=>') || t.includes('&&') || t.includes('===')) return false;
  if (!/[A-Za-zА-Яа-яЁё]/.test(t)) return false;
  if (/^[A-Za-z0-9_./:-]+$/.test(t)) return false;
  if (/^\{.*\}$/.test(t)) return false;
  if (/^#?[A-Fa-f0-9]{3,8}$/.test(t)) return false;
  if (/^v\d+(\.\d+)*$/i.test(t)) return false;
  if (/^[a-z]+(\.[a-z]+)+$/i.test(t)) return false;
  if (IGNORED_SUBSTRINGS.some((part) => t.includes(part))) return false;
  return true;
}

function lineNumberAt(content, index) {
  let line = 1;
  for (let i = 0; i < index; i += 1) {
    if (content.charCodeAt(i) === 10) line += 1;
  }
  return line;
}

function scanFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const findings = [];
  const isPlainTs = filePath.endsWith('.ts');

  const patterns = [
    {
      kind: 'jsx-text',
      regex: />\s*([^<>{}\n][^<\n]*[A-Za-zА-Яа-яЁё][^<\n]*)\s*</g,
      group: 1,
    },
    {
      kind: 'attr-string',
      regex: /\b(?:placeholder|title|aria-label)\s*=\s*(["'`])((?:\\.|(?!\1).){2,})\1/g,
      group: 2,
    },
    {
      kind: 'call-string',
      regex: /\b(?:alert|confirm|prompt|setError|setSuccess)\(\s*(["'`])((?:\\.|(?!\1).){2,})\1/g,
      group: 2,
    },
    {
      kind: 'label-field',
      regex: /\blabel\s*:\s*(["'`])((?:\\.|(?!\1).){2,})\1/g,
      group: 2,
    },
  ];

  for (const pattern of patterns) {
    pattern.regex.lastIndex = 0;
    let match;
    while ((match = pattern.regex.exec(content)) !== null) {
      if (isPlainTs && pattern.kind === 'jsx-text') continue;
      const text = (match[pattern.group] || '').trim();
      if (!isLikelyUserFacingText(text)) continue;

      const before = content.slice(Math.max(0, match.index - 140), Math.min(content.length, match.index + 180));
      if (/\bt\(\s*["'`][^"'`]+["'`]/.test(before)) continue;

      const line = lineNumberAt(content, match.index);
      const rel = path.relative(ROOT, filePath).replace(/\\/g, '/');
      const stableId = `${rel}:${pattern.kind}:${text}`;
      findings.push({
        id: stableId,
        legacyId: `${rel}:${line}:${pattern.kind}:${text}`,
        file: rel,
        line,
        kind: pattern.kind,
        text,
      });
    }
  }

  return findings;
}

const files = collectFiles(SRC_DIR);
const allFindings = files.flatMap(scanFile);

function printReport(findings) {
  const byFile = new Map();
  const byKind = new Map();

  for (const item of findings) {
    byFile.set(item.file, (byFile.get(item.file) || 0) + 1);
    byKind.set(item.kind, (byKind.get(item.kind) || 0) + 1);
  }

  console.log(`i18n hardcoded report: ${findings.length} findings`);
  console.log('By kind:');
  for (const [kind, count] of [...byKind.entries()].sort((a, b) => b[1] - a[1])) {
    console.log(` - ${kind}: ${count}`);
  }

  console.log('Top files:');
  for (const [file, count] of [...byFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 25)) {
    console.log(` - ${file}: ${count}`);
  }

  console.log('First findings:');
  for (const item of findings.slice(0, 40)) {
    console.log(` - ${item.file}:${item.line} [${item.kind}] ${item.text}`);
  }
}

if (REPORT) {
  printReport(allFindings);
  process.exit(0);
}

if (WRITE_BASELINE) {
  const baseline = {
    generatedAt: new Date().toISOString(),
    count: allFindings.length,
    ids: allFindings.map((item) => item.id),
  };
  fs.writeFileSync(BASELINE_PATH, JSON.stringify(baseline, null, 2) + '\n', 'utf8');
  console.log(`i18n baseline written: ${path.relative(ROOT, BASELINE_PATH)} (${baseline.count} entries)`);
  process.exit(0);
}

if (!fs.existsSync(BASELINE_PATH)) {
  console.error('i18n baseline is missing. Run: npm run i18n:baseline');
  process.exit(2);
}

const baseline = JSON.parse(fs.readFileSync(BASELINE_PATH, 'utf8'));
const baselineIds = new Set(Array.isArray(baseline.ids) ? baseline.ids : []);
const stableBaselineIds = new Set(
  [...baselineIds].map((id) => {
    const match = String(id).match(/^(.+?):\d+:(jsx-text|attr-string|call-string|label-field):([\s\S]*)$/);
    return match ? `${match[1]}:${match[2]}:${match[3]}` : id;
  }),
);
const newViolations = allFindings.filter((item) => !stableBaselineIds.has(item.id) && !baselineIds.has(item.legacyId));

if (newViolations.length > 0) {
  console.error(`New hardcoded i18n strings found: ${newViolations.length}`);
  for (const item of newViolations.slice(0, 80)) {
    console.error(` - ${item.file}:${item.line} [${item.kind}] ${item.text}`);
  }
  if (newViolations.length > 80) {
    console.error(` ... and ${newViolations.length - 80} more`);
  }
  process.exit(1);
}

console.log(`i18n hardcoded check passed (baseline count: ${baselineIds.size}, current findings: ${allFindings.length})`);
