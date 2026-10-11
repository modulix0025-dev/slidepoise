"""Child script: real ``generate_story`` dry run with OM's own interpreter, output into a temp folder.

Self-contained (stdlib + whatever OM imports): it runs under OM's Python, where ``mxstudio`` is not
installed. Inputs in environment variables: MX_OM_ROOT, MX_OUT_DIR, MX_STORY, MX_CHILD_NAME,
MX_GENDER, MX_LANGUAGE, MX_SIZE. The working directory is the temp folder, so a stray relative
write cannot land in OM's tree. Prints one JSON object.
"""
import json
import os
import sys
import traceback


def main():
    om_root = os.environ["MX_OM_ROOT"]
    out_dir = os.environ["MX_OUT_DIR"]
    sys.path.insert(0, om_root)
    os.chdir(out_dir)
    result = {"ok": False}
    try:
        from app.services import story_engine
        ret = story_engine.generate_story(os.environ["MX_STORY"], os.environ["MX_CHILD_NAME"],
                                          os.environ.get("MX_GENDER", "male"), os.environ.get("MX_LANGUAGE", "ar"),
                                          out_dir, size=os.environ.get("MX_SIZE", "A5"))
        result = {"ok": True, "returned": repr(ret)[:300],
                  "outputs": sorted(n for n in os.listdir(out_dir) if n.lower().endswith(".pptx"))}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}",
                  "trace_tail": traceback.format_exc()[-1500:]}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
