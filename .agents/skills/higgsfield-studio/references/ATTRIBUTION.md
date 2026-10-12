# Attribution

This plugin is built on Higgsfield's official agent skills at https://github.com/higgsfield-ai/skills (version 0.13.0, commit f83af0bc1d937c8119099a11f8ebbf5e6fb99819), used under the MIT License below.

- The files in each skill's `references/` folder are copied from the matching official skill without changes. So are the Python scripts in `higgsfield-studio-brandkit/scripts/` and `higgsfield-studio-websites/scripts/`.
- In each specialist skill, the part of `SKILL.md` under "Higgsfield's guide" is the official skill's body. Only the paid and outward commands are rewritten to run through `hf.mjs`, and the official install step is replaced by `setup-deps`. `sync/adapt.py` at the plugin root makes that change and nothing else.
- The guard script `hf.mjs`, the setup scripts, the price table, the measured costs, the working order and the rules on spending and outward actions are our own.

The upstream commit and the map from each official skill to ours are in `upstream.json` at the plugin root.

```
MIT License

Copyright (c) 2026 Higgsfield AI

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
