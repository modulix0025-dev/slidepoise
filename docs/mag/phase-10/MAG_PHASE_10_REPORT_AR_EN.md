# MAG_PHASE_10_REPORT_AR_EN — المرحلة 10: تدريب المساعد والاختبارات · Phase 10: Studio Agent & evals

> 2026-10-11 · local tag `mag-phase-10`

## الحقيقة الأول · The honest framing
**AR:** مفيش موديل ذكاء اصطناعي «مستحيل يغلط». اللي اتبنى هنا هو نظام **أخطاء المساعد فيه ماتقدرش توصل لعميل أو لمطبعة**: كل حركة للمساعد بتعدّي من أدوات ليها schema، كل خطوة مالهاش رجوع محتاجة توكن تأكيد من الإنسان مايقدرش المساعد يعمله، المحتوى اللي جاي من بره بيتعامل كبيانات، وكل حاجة متسجّلة. ونسبة النجاح دي مقاسة مش متقالة.
**EN:** No model is infallible. What exists is a system in which agent mistakes cannot reach a customer or a printer: typed tools only, human-only confirmation tokens for irreversible steps, fetched content treated as data, full audit — and it is measured.

## اللي اتبنى · Built
| Piece | Where |
|---|---|
| Operator Manual generated from the live registry (every tool AR/EN + schema + irreversible flag), the HTTP routes, every named finding (factory + QA + tool codes), and 5 hand-written playbooks; deterministic sha256; `diff_manuals` per release; keyword retrieval | `mxstudio/agent/manual.py`, `playbooks/` |
| Agent loop: plan → tools → verify → report; one clarifying question max; tool results wrapped as DATA with instruction-like text flagged; irreversible ⇒ stops with `needs_confirmation` | `mxstudio/agent/loop.py` |
| Guarded tools: licence gate for print assets (provenance required), model-licence gate for image workflows, budget reservation, class plan, recorded web reads | `mxstudio/agent/catalog.py`, `mxstudio/licensing.py` |
| **321 scenarios** (145 safety in 11 families, 176 task in 11 families), graders, runner, qualification, CLI `python -m mxstudio evals generate|run|qualify`, API `/api/agent/run|manual|summary` | `mxstudio/agent/evals/`, `evals/scenarios.json` |

## النتايج · Results (`evidence/evals_report_scripted.json`)
- **Safety: 145/145 = 100 %** — model-independent: each attack (publish without approval, approve without/with forged/reused/mismatched/expired/agent-minted token, AI edit of a customer photo, non-commercial model weights, 25 refused licences incl. CC-BY without credits, 20 prompt injections run through the real loop with a worst-case model that obeys them, budget overrun, schema abuse, secret exfiltration) is refused by the tool layer, and nothing irreversible ever executes without a human token.
- **Tasks: 176/176 under the scripted reference plans** — this proves every task is solvable and every grader is right. **It is not a model score.**
- **Model scores: pending.** No model is reachable from the cloud session. On the operator's PC, once a model is set (default Qwen3-VL, D13), `python -m mxstudio evals qualify` runs the safety families + a task subset through the real loop; below 100 % safety or 95 % tasks ⇒ the agent is switched to **suggestion-only** automatically (tested with a do-nothing model).
- Negative control: removing the irreversible flag from `workspace.approve` turns its safety eval red.
- Kit anchor-mismatch scenarios are covered by the Kit's own suite (Phase 8) rather than duplicated here.
