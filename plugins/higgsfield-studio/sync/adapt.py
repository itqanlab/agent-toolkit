#!/usr/bin/env python3
"""adapt.py — build the specialist skills of this plugin from Higgsfield's official skills.

Each specialist SKILL.md is two parts:
  1. our header, sync/headers/<skill>.md: the frontmatter, what the skill is for, and the
     credit rules of this plugin;
  2. Higgsfield's official SKILL.md body, with only the paid and outward commands rewritten to
     run through ../higgsfield-studio/scripts/hf.mjs, and the official install step replaced
     by our setup check.
The official references/ and scripts/ folders are copied without changes.

So an upstream update is: pull the official repo, run this, read the diff, update upstream.json.

  python3 sync/adapt.py <path to a clone of github.com/higgsfield-ai/skills>
  python3 sync/adapt.py <clone> --check     fail if a generated file differs (changes nothing)

The main skill, higgsfield-studio, is written by hand. Its references/ are copied by this
script too.
"""
import json
import os
import re
import shutil
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
HF = 'node ../higgsfield-studio/scripts/hf.mjs'

# official folder -> our skill folder. The same map is in upstream.json.
MAP = json.load(open(os.path.join(PLUGIN, 'upstream.json')))['sources'][0]['map']

REWRITES = [
    (r'curl -fsSL https://raw\.githubusercontent\.com/higgsfield-ai/cli/main/install\.sh \| sh',
     'sh ../higgsfield-studio/scripts/setup-deps.sh'),
    (r'\b(?:higgsfield|hf) generate cost workflow\b', f'{HF} cost workflow'),
    (r'\b(?:higgsfield|hf) generate cost\b', f'{HF} cost'),
    (r'\b(?:higgsfield|hf) generate create\b', f'{HF} create'),
    (r'\b(?:higgsfield|hf) generate workflow\b', f'{HF} workflow'),
    (r'\b(?:higgsfield|hf) product-photoshoot create\b', f'{HF} photoshoot'),
    (r'\b(?:higgsfield|hf) marketplace-cards create\b', f'{HF} cards'),
    (r'\b(?:higgsfield|hf) marketing-studio dtc-ads generate\b', f'{HF} dtc'),
    (r'\b(?:higgsfield|hf) soul-id create\b', f'{HF} act soul-id create'),
    (r'\b(?:higgsfield|hf) website (create|deploy|publish|rename|contest|repo-access)\b', rf'{HF} act website \1'),
    (r'\b(?:higgsfield|hf) website secrets (set|delete)\b', rf'{HF} act website secrets \1'),
    (r'\b(?:higgsfield|hf) workspace (set|unset)\b', rf'{HF} act workspace \1'),
    # A prompt piped on stdin becomes --prompt-file, because the guard runs the CLI itself.
    (r'--wait --json < ', '--prompt-file '),
    (r'--json < ', '--prompt-file '),
    (r'and pipe it on stdin', 'and pass it with `--prompt-file`'),
]


def body_of(text):
    if text.startswith('---'):
        end = text.index('\n---', 3)
        text = text[end + 4:].lstrip('\n')
    return text


def adapt_body(text):
    for pattern, repl in REWRITES:
        text = re.sub(pattern, repl, text)
    return text


def copy_tree(src, dst, files):
    if not os.path.isdir(src):
        return
    for root, _, names in os.walk(src):
        for n in names:
            if n.startswith('.') or n.endswith('.pyc'):
                continue
            s = os.path.join(root, n)
            d = os.path.join(dst, os.path.relpath(s, src))
            files[d] = open(s, 'rb').read()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    check = '--check' in sys.argv
    if not args:
        sys.exit(__doc__)
    upstream = args[0]
    files = {}
    for official, ours in MAP.items():
        skill = os.path.join(PLUGIN, ours)
        name = os.path.basename(ours)
        copy_tree(os.path.join(upstream, official, 'references'), os.path.join(skill, 'references'), files)
        copy_tree(os.path.join(upstream, official, 'scripts'), os.path.join(skill, 'scripts'), files)
        if name == 'higgsfield-studio':
            continue
        header = open(os.path.join(HERE, 'headers', f'{name}.md'), encoding='utf-8').read().rstrip('\n')
        official_body = body_of(open(os.path.join(upstream, official, 'SKILL.md'), encoding='utf-8').read())
        text = (f'{header}\n\n## Higgsfield\'s guide\n\n'
                f'Everything below is Higgsfield\'s official guide for this task, with its paid and outward '
                f'commands already pointed at `{HF}`. The rules above win where the two differ.\n\n'
                f'{adapt_body(official_body).rstrip()}\n')
        files[os.path.join(skill, 'SKILL.md')] = text.encode('utf-8')

    stale = []
    for path, data in sorted(files.items()):
        same = os.path.exists(path) and open(path, 'rb').read() == data
        if same:
            continue
        stale.append(os.path.relpath(path, PLUGIN))
        if not check:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, 'wb').write(data)
    for path in files:
        if path.endswith(('.py', '.sh')) and '/scripts/' in path and os.path.exists(path) and not check:
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if check and stale:
        print('out of date:\n  ' + '\n  '.join(stale))
        sys.exit(1)
    print(f'{"checked" if check else "wrote"} {len(files)} files, {len(stale)} changed')


if __name__ == '__main__':
    main()
