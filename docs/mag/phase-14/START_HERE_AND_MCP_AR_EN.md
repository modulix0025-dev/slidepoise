# «ابدأ هنا» والتحكم بـMCP · Start here and MCP control

> 2026-10-11 · local tag `mag-phase-14`

## ١ · «ابدأ هنا» (أول صفحة في الاستوديو) · The Start page

**AR:** اكتب اللي عايزه («قصة عن طفل بيروح البحر، 6 صفحات، ألوانها زي الصورة دي، والاسم كبير على الغلاف») وارفع صورة التصميم (زرار «إرفاق صور» أو اسحبها على مربع الكتابة). المساعد:
1. يعرض خطته.
2. يطلّع الألوان من صورتك (`colour.from_art`) ويتأكد إنها هتتطبع صح، ويختار ثيم خطوط.
3. يكتب القصة (نص الولد ونص البنت كل واحد لوحده) ويبني الـ8 نسخ ويفحصها.
4. **يبص على صورة المعاينة اللي اتبنت** قبل ما يقولك خلص — والمعاينة بتظهرلك على الجنب.
5. تكتب التعديل بالكلام («كبّر الاسم»، «الألوان أهدى»، «غيّر الصفحة التالتة») في نفس المحادثة، فيبني نسخة جديدة (القديمة بتفضل محفوظة).
6. الاعتماد والنشر: لو المساعد طلبهم بيظهروا في «طلبات الموافقة» على الجنب، ومابيتنفذوش غير لما تدوس «موافق، نفّذ».

**EN:** Write what you want and attach design pictures; the assistant plans, extracts the palette from your picture, checks print safety, picks a type theme, writes the story, builds and validates all 8 variants, **looks at the rendered preview before reporting**, and revises from your plain-language feedback in the same conversation. Approve/publish requests wait in «طلبات الموافقة» for your click.

### الموديل · Which model thinks
From **Settings → Text/Vision**:
* **Claude (Anthropic API)** — model `claude-opus-5-5` by default; put the API key in Keys as `provider.text_vision`. Paid API, optional (chosen by the operator; refusals fall back automatically on Anthropic's side).
* **OpenAI-compatible (free)** — your GPU server (vLLM / LM Studio) with an open model such as Qwen3-VL.
The assistant starts in **suggestion-only** mode; press «اختبر الموديل» once on the Start page to run the safety qualification — a model that passes switches to full mode.

## ٢ · MCP: خلّي Claude Desktop / Claude Code يتحكم في الاستوديو · MCP

**AR:** لو عندك اشتراك Claude، تقدر تخلّي Claude Desktop هو اللي يشغّل الاستوديو من غير مفتاح API في الاستوديو. ضيف ده في `%APPDATA%\Claude\claude_desktop_config.json` (أو اضغط «Settings → Developer → Edit Config» في Claude Desktop) واقفل Claude Desktop وافتحه تاني:

```json
{"mcpServers": {"modulex-studio": {
  "command": "C:\\Users\\<you>\\AppData\\Local\\Programs\\ModuleX Magazine Studio\\mxstudio-cli.exe",
  "args": ["mcp"]}}}
```
المسار الصح لجهازك مكتوب جاهز في صفحة «ابدأ هنا» (مربع MCP). من Claude Code:
`claude mcp add modulex-studio -- "C:\Users\<you>\AppData\Local\Programs\ModuleX Magazine Studio\mxstudio-cli.exe" mcp`

**EN:** The MCP server (`mxstudio-cli.exe mcp`, stdio, no console window) exposes every Studio tool plus `studio_manual`, `studio_view_preview` (returns the rendered pages as an image so Claude can look), `studio_add_reference_image` (file path or base64), `studio_view_reference` and `studio_pending_approvals`. It shares the Studio's workspace, so builds made from Claude Desktop show up in the Studio and vice versa. Anything irreversible is **queued** — the operator approves it in the Studio window.

## ٣ · الأمان · Safety
* The model acts only through typed, schema-checked tools; tool results are wrapped as data and instruction-like text is flagged.
* Irreversible requests from any model (Studio chat, MCP, evals) become pending approvals; only the human UI session can decide (`ToolRegistry.decide` refuses any non-`ui:` actor; the HTTP route needs the Studio window's CSRF token). An approval mints a single-use token bound to that exact request and runs it as the human; the audit log records who.
* Uploaded pictures are verified as real PNG/JPEG/WebP/GIF (≤ 20 MB); only pictures are ever served back. Customer photos are never AI-altered.
* Agent evals: 336 scenarios (safety 160) — new family `agent_decides_own_request`.

## ٤ · الإثبات · Evidence
`tests/mag/agent/test_start_and_mcp.py` (11 tests): pending queue (agents cannot decide, rejected requests never run, duplicate requests merge), uploads (real pictures only, only pictures served), a full scripted chat (the operator's picture and the build preview reach the model; the revision turn sees the earlier turn and pictures; irreversible step queued), no-model and suggestion-only answers, Claude provider request shape (system, base64 images, effort, `fallbacks: "default"`, refusal), OpenAI-compatible per-message images, factory theme (named missing fonts), and the MCP server end to end over stdio (initialize, tools, reference by path with an Arabic file name, queued irreversible call, manual, parse/unknown-method errors, image content). Browser test: the Start page uploads a picture in Chromium and answers honestly without a model.

## ٥ · مستني الجهاز · Pending on device
A real Claude / Qwen3-VL conversation building a story end to end (needs the key or GPU URL); Claude Desktop launching `mxstudio-cli.exe mcp` on Windows (the CI smoke covers the windowed-exe stdio path once the next installer build runs).
