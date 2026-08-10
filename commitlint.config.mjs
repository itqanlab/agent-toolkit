// Commit format: <emoji> <type>(<scope>): <subject>
//
//   ✨ feat(watch-video): add --lang flag for non-English captions
//   🐛 fix(install): keep .claude-plugin when target is ~/.claude/skills
//   📝 docs(compat): record verified discovery paths for eight agents
//
// The emoji is required and comes first, so `git log --oneline` stays scannable.
// Everything after it follows Conventional Commits, so tooling still parses it.
// See CONTRIBUTING.md for the type/emoji table.

const emoji = '(?:\\p{Extended_Pictographic}(?:\\uFE0F|\\u200D\\p{Extended_Pictographic})*)+';

export default {
  extends: ['@commitlint/config-conventional'],
  parserPreset: {
    parserOpts: {
      headerPattern: new RegExp(`^${emoji}\\s(\\w+)(?:\\(([^)]+)\\))?(!)?: (.+)$`, 'u'),
      headerCorrespondence: ['type', 'scope', 'breaking', 'subject'],
    },
  },
  rules: {
    'type-enum': [2, 'always', [
      'feat',     // ✨ new skill, or new capability in an existing one
      'fix',      // 🐛 bug fix
      'docs',     // 📝 documentation only
      'style',    // 💄 formatting, no behaviour change
      'refactor', // ♻️  restructure without changing behaviour
      'perf',     // ⚡ performance
      'test',     // ✅ tests and validation
      'build',    // 📦 build system, dependencies, packaging
      'ci',       // 👷 CI configuration
      'chore',    // 🔧 tooling, hooks, housekeeping
      'revert',   // ⏪ revert a previous commit
    ]],
    'type-case': [2, 'always', 'lower-case'],
    'type-empty': [2, 'never'],
    'scope-case': [2, 'always', 'kebab-case'],
    'subject-empty': [2, 'never'],
    'subject-full-stop': [2, 'never', '.'],
    'subject-case': [2, 'never', ['start-case', 'pascal-case', 'upper-case']],
    'header-max-length': [2, 'always', 100],
    'body-max-line-length': [2, 'always', 100],
    'footer-leading-blank': [1, 'always'],
    'body-leading-blank': [1, 'always'],
  },
};
