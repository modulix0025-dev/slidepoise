# MAG_PHASE_8_REPORT_AR_EN — المرحلة 8: «ربط أنظمتي» · Phase 8: the Integration Kit

> 2026-10-11 · local tag `mag-phase-8` · details: `KIT_NOTES.md` (Kit + receivers), `MXLIBS_NOTES.md` (libraries, committed earlier as `mag-phase-8` libraries)

**AR:** الـKit بيدوّر على أنظمتك (OM / Console / Store) جوه `C:\المشروع` من غير ما يسألك هي فين، بيتأكد من نقاط الربط حرفيًا (التوقيعات، أجسام الدوال اللي اتنقلت بالنص، الثوابت، بصمات العقود)، بيفحص قراءة بس، وبعدين بيركّب **باتشات صغيرة جنب الكود** — كل باتش ورا فلاج **مقفول افتراضيًا**، محتاج كود تأكيد منك للباتش ده بالذات، وبيرجع زي ما كان **بالبايت**. الملفات المجمّدة (`config.py`، `deck_pdf.py`، `modulex_signing.py`، `modulex_pairing.py`، `ui-utils.js`) مرفوضة بالمسار ومتبصّمة قبل وبعد كل عملية. المستقبلات (receivers) بتستلم حزم M1/M2/M6/M7 الموقّعة بـ`modulex_signing` الأصلي.

**EN:** The Kit discovers the operator's systems under the project root without asking where they are, verifies anchors verbatim, probes read-only, and applies small additive patches — each behind a default-OFF flag, each with its own confirmation code, each byte-identically revertible (LIFO for shared files). Frozen files are refused by path and hashed before/after. A new `RUN_TESTS.bat` failure rolls the patch back. Receivers accept M1/M2/M6/M7 packs signed with the vendored `modulex_signing`.

## Patches · الباتشات
| Patch | Flag (default OFF) |
|---|---|
| P-TEXTFIT | `MODULEX_MAG_TEXTFIT` |
| P-SAFEZONE | `MODULEX_MAG_SAFEZONE` |
| P-PREVIEW | `MODULEX_MAG_PAGE_PREVIEW` |
| P-PROOF | `MODULEX_MAG_PROOF_APPROVAL` |
| P-PREFLIGHT2 (+ QA gate checks) | `MODULEX_MAG_PREFLIGHT2` / `MODULEX_MAG_QA_GATE` |
| P-RECEIVERS | `MODULEX_MAG_RECEIVERS` |

## Evidence
`tests/mag/kit/` — 103 tests on synthetic replicas of the operator's tree under an Arabic root «المشروع»: discovery, anchor mismatch ⇒ blocked with diff, operator-updated contract ⇒ behaviour compared with signing vectors / `pdf_stats` known answers, apply → flag OFF behaves exactly like before → flag ON works → revert gives the original sha256, drift refused, frozen-file hashes unchanged, failing system tests roll back.

## Pending on device · مستني الجهاز
Real anchors in the operator's code, `RUN_TESTS.bat` results, process owners/font visibility, a live `generate_story` dry run, editor error path for `TextDoesNotFit`, the print-portal sidecar reader, Console frozen-build status. Runbook: `KIT_NOTES.md` (Proof Runner: `mxstudio kit discover → verify → probe → plan → apply → proofs → report`).

**Note from the libraries:** `mx_preflight2`'s `safe_mm` default with OM's `bleed_mm=0` could block printing; the Kit passes `safe_mm` explicitly.
