"""ModuleX Magazine Studio — Integration Kit («ربط أنظمتي»).

The Kit runs inside the installed Studio on the operator's Windows PC. It
discovers the operator's systems under the project root, verifies anchors
(signatures, verbatim bodies, constants, sha256 of contract files), probes the
estate read-only, plans and applies small additive patches behind env flags
that default OFF (only after per-patch operator confirmation), proves export
behaviour on the device and writes a redacted device report.

Rules this package enforces:
* an anchor mismatch blocks the patch and records the difference — it never patches;
* frozen operator files are never written (checked by path and by sha before/after);
* every write is backed up outside any ``static`` folder and reverts byte-identically;
* child processes only through :mod:`mxstudio.proc`.
"""

KIT_VERSION = "0.8.0"
