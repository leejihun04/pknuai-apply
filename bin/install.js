#!/usr/bin/env node
'use strict';
// Copies this skill into <target>/.claude/skills/pknuai-apply so that
//   npx github:leejihun04/pknuai-apply
// drops a ready-to-run skill into the project the user is standing in.

const fs = require('fs');
const path = require('path');

const SOURCE = path.resolve(__dirname, '..');
const ITEMS = ['pknuai_apply', 'assets', 'tests', 'SKILL.md', 'README.md', 'pknuai-apply', 'LICENSE'];
const SKIP = new Set(['__pycache__', '.DS_Store', '.git', 'node_modules']);

function copy(from, to) {
  const stat = fs.statSync(from);
  if (stat.isDirectory()) {
    fs.mkdirSync(to, { recursive: true });
    for (const entry of fs.readdirSync(from)) {
      if (SKIP.has(entry) || entry.endsWith('.pyc')) continue;
      copy(path.join(from, entry), path.join(to, entry));
    }
    return;
  }
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.copyFileSync(from, to);
  fs.chmodSync(to, stat.mode & 0o777);
}

const base = path.resolve(process.argv[2] || process.cwd());
const target = path.join(base, '.claude', 'skills', 'pknuai-apply');

if (fs.existsSync(path.join(target, 'SKILL.md'))) {
  console.log(`기존 설치를 덮어씁니다: ${target}`);
}
for (const item of ITEMS) {
  const from = path.join(SOURCE, item);
  if (!fs.existsSync(from)) continue;
  copy(from, path.join(target, item));
}
fs.chmodSync(path.join(target, 'pknuai-apply'), 0o755);

console.log(`
✅ 설치 완료: ${target}

다음 단계
  cd ${target}
  ./pknuai-apply session set      # 브라우저 쿠키 저장 (README의 "처음 한 번" 참고)
  ./pknuai-apply install-agent    # 모집 시작을 기다리는 감시자 등록
  ./pknuai-apply serve            # 웹 화면 (http://127.0.0.1:8765)

Claude Code에서는 "비교과 예약해줘" 처럼 말하면 이 스킬이 실행됩니다.
`);
