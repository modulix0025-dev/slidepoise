# Phase 16 — Claude Desktop always finds the Studio · اتصال ثابت مع Claude Desktop

Branch `claude/mcp-stable-connection` (from c399b32 / 47e2221). Proofs: `tests/mag` (1056 passed on Linux, Python 3.10 +
3.12; Windows suite green), `mag-release.yml` run 38171099535 on a clean `windows-latest`
(`installer/windows_sandbox/mcp_connection_proof.ps1`, results published as a check-run annotation).

| # | البند | التيست اللي بيثبته | النتيجة |
|---|---|---|---|
| 1 | مكان التسطيب: فولدر بيتزامن مرفوض/تحذير؛ `HKCU\Software\ModuleX\MagazineStudio` InstallDir+Version | `test_mcp_connection.py::test_sync_folders_*`, `::test_install_dir_registry_*`, `::test_installer_refuses_*`; Windows: `onedrive_refused_moved_to_default`, `registry_installdir`, `registry_follows_move` | ✅ |
| 2 | مشغّل ثابت `<app home>\bin\mxstudio-mcp.exe` (C، 19 KB) وكل نسخ إعدادات Claude Desktop | `::test_entry_is_the_fixed_launcher_*`, `::test_every_claude_desktop_config_*`, `::test_acceptance_install_connect_uninstall_reinstall_*`; Windows: `entry_is_fixed_launcher`, `entry_unchanged_after_move`, `handshake_after_move` | ✅ |
| 3 | Self-healing عند التسطيب وكل فتح؛ الـuninstaller يشيل مدخلنا بس | `::test_self_heal_*`, `::test_heal_all_restores_*`; Windows: `self_heal_entry_back`, `self_heal_other_server_kept`, `self_test_on_open`, `uninstall_removed_only_ours` | ✅ |
| 4 | «لازم تعيد تشغيل Claude Desktop»: اكتشاف + زرار بتأكيد + لوج Claude | `::test_restart_is_pending_*`, `::test_restart_quits_and_reopens_*`, `::test_claude_desktop_log_last_state` | ✅ (بـfakes) — التشغيل الحقيقي على جهاز المشغّل pending |
| 5 | سيرفر MCP: handshake < 2 ث، stdout نضيف، أخطاء {code, ar, en}، SQLite WAL+busy | `::test_handshake_20_times_and_in_parallel_*`, `::test_stray_prints_*`, `::test_heavy_libraries_*`, `::test_shared_sqlite_*`; Windows: 20× + 5 بالتوازي، أقصى 1.21 ث، صفر سطور مش JSON | ✅ |
| 6 | فولدر «الوارد» + `studio_inbox_list` / `studio_inbox_use` | `::test_inbox_names_*`, `::test_acceptance_picture_dropped_on_start_here_*` (الصورة ← الباليتة) | ✅ |
| 7 | «ابدأ هنا» من غير مفتاح = تحضير طلب لـClaude Desktop؛ اختبار الموديل تلقائي | `::test_no_api_key_*`, `::test_saving_a_model_key_*`, `::test_acceptance_request_without_key_*` (طلب+صورة ← claim ← build ← done ← المعاينة)، `studio_ui.test.mjs` | ✅ |
| 8 | نسخة واحدة (named mutex) + server.lock قديم | `::test_acceptance_three_starts_give_one_window`, `::test_stale_server_lock_*`; Windows: `single_instance_count=1` | ✅ |
| 9 | الخطوط: تسجيل HKCU + AddFontResourceExW + WM_FONTCHANGE لكل ملف؛ نسخ أوفيس ثابتة بدل المتغيّرة؛ مفيش خط بديل | `fonts/test_no_substitute_export.py` (كل خطوط الـ33 ثيم في PDF واحد)، `release/test_asset_bundles.py`، فحص `font_substituted` في كل بناء | ✅ على LibreOffice — PowerPoint pending on device |
| 10 | text_proof: أسماء بتخلص بهمزة + تقطيع الاستخراج | `factory/test_hamza_names.py` (24 خط × 6 أسماء × 3 أماكن + negative controls)، `factory/test_all_themes.py` (33 ثيم بـ«جيداء»، `MXS_ALL_THEMES=1`) | ✅ |
| 11 | 16:9 بالعرض: overlay / storybook، Picture Placeholder 100، تأثيرات OOXML، safe zone وتباين على الصورة | `factory/test_landscape.py` (8 نسخ خضرا لكل layout، placeholders فاضية، insert_picture بيملاها كلها) | ✅ |
| 12 | trust.json: مفيش مفتاح ⇒ التحديث التلقائي مقفول؛ LibreOffice متثبّت؛ app home والـworkspace مايتلمسوش | `release/test_update_gate_and_data.py` | ✅ |
| 13 | بنود الفحص الشامل الجديدة بـfix_id | `release/test_doctor.py` (كلهم أخضر بالـfakes + كل fix_id موجود) | ✅ |

## اللي اتلقى أثناء الشغل · Found on the way
* The vault installed Google's **variable** font files: PowerPoint/LibreOffice only see the default instance («Marhey
  Light»), so «Marhey» was substituted. The vault now builds the deterministic Office statics (sha-checked against
  `catalog/fonts/office_builds.json`; fontTools packs GSUB/GPOS with HarfBuzz's repacker, so `uharfbuzz` must be
  present) and retires old variable registrations. Five OFL-RFN families are installed renamed («MX Kids F0xx …»):
  decks now use that installed name.
* Text extraction in 11 title fonts splits words across invented lines, and newer PDFium regroups stacked glyphs: the
  proof gained a fragment re-joiner (only into words the deck has and the PDF lacks), a geometric view for rotated
  text, and an order-free per-box view. Verdict stays exact multiset equality; negative controls fail.
* Child-name boxes are fitted for the longest expected name (4 English covers overflowed with «Abdelrahman Ali»).

## Pending on-device proof (operator's PC) · لسه محتاج إثبات على جهاز المشغّل
1. Claude Desktop itself starting `mxstudio-mcp.exe` and showing the tools; the «أعد تشغيل Claude Desktop» button
   (Store and classic builds); Claude's real `mcp-server-modulex-studio.log` lines.
2. PowerPoint: export of one deck per theme → no substitute (`pdffonts`), gradient/glow/outline on the name art.
3. Reboot → step 3 of the acceptance again (no action in between).
4. The desktop shortcut «الوارد - استوديو المجلات» on the OneDrive Desktop.
5. `standard-user-proof` already failed on the base branch before this phase (non-blocking job); not addressed here.
