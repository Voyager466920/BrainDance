# Reused components and adaptations

Official [ARIS](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep), installed at `~/aris_repo`, remains unchanged. This extension reuses its installed `/research-lit` workflow, paper/evidence conventions, and official `mcp-servers/codex-exec/server.py` bridge. It adds project-local orchestration and a research tree; it does not claim these additions are stock ARIS.

[YonasValentin/llm-council](https://github.com/YonasValentin/llm-council), inspected locally at `the upstream checkout`, revision `c906d33f862509dbf2fbf6f290ba537d8f7fb8d3`, provides the reused independent-advisor → anonymous peer-review → Chairman method, factorial-base anonymization, three blind-review questions, and five-section Chairman structure. Its full skill is not invoked, because doing so would create an additional five-member council.

User-requested adaptations are four specialist participants (three Claude agents and Codex), a four-element permutation, mode/budget controls, evidence-linked hypotheses, persistent tree, and local Viewer. Fresh-session Chairman synthesis receives persisted artifacts explicitly rather than inheriting an interactive session. Upstream generic decision triggers, unrelated persona prompts, retry-on-hedging, and HTML templates are not imported. Reviewer anonymity hides author labels and the audit map; it cannot guarantee stylistic unidentifiability.

BrainDance additionally provides its own approved Python experiment supervisor and queue for local/SSH execution, with bounded runtime, process-group cancellation, device coordination, raw logs and result receipts. These are BrainDance extensions, not stock ARIS features. No autoresearch integration or additional memory service is included. Existing global Claude/Codex settings and official ARIS files are outside the extension's managed files.

The app's research-start controller hosts the unchanged installed ARIS `research-lit` Skill and shared references in a private session plugin, reuses upstream `verify_papers.py` and `arxiv_fetch.py`, then calls the existing Council. This bounded host uses sequential extraction with search/file tools and performs helper execution outside the model. Persistent stage monitoring, explicit launch/stop, source reuse and research-job retention are BrainDance additions.

## Upstream MIT notice

MIT License

Copyright (c) 2026 Yonas Valentin

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
