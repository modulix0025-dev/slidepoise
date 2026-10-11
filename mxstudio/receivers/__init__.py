"""Additive receivers for the Magazine Studio contracts M1/M2/M6/M7 (operator side).

This package is *relocatable*: the Kit's P-RECEIVERS patch copies it verbatim into an
operator system (e.g. ``OrderManagement/app/mag_receivers/``). It therefore imports
only the standard library, FastAPI (already used by the operator systems) and its own
modules — never ``mxstudio``. The signing contract is the *system's own*
``modulex_signing.py`` (verified by sha256 anchor), passed in at mount time.

Rules:
* every HTTP call is signed (``verify`` then ``check_replay``); refusals are named;
* received documents are stored as **candidates** only — nothing is activated here;
* M1 activation goes through OM's own ``story_engine.add_story()/update_story()`` and
  only with the operator's confirmation code; M2 is approved by a human on the Console
  (the receiver never writes ``approvals.log.jsonl``);
* signed packs (zip + manifest + detached signature) are the fallback transport and
  are ingested through the same code path.
"""

CONTRACT_VERSION = "mag/v1"
KINDS = ("m1", "m2", "m6", "m7")
SCHEMA_FILES = {
    "m1": "m1_template_set.schema.json",
    "m2": "m2_deck_contract.schema.json",
    "m6": "m6_font_sync.schema.json",
    "m7": "m7_font_choices.schema.json",
}
ROUTES = {"m1": "m1/template-set", "m2": "m2/deck-contract", "m6": "m6/font-set", "m7": "m7/font-choices"}
