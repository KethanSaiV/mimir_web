"""Static checks for static/index.html: colour tokens, contrast, a11y markup.

Run from mimir_web/:  ../venv/Scripts/python.exe tests/check_ui.py
"""
import re
import sys
from pathlib import Path

HTML = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
ROOT_RE = re.compile(r":root\{(.*?)\}", re.S)


def _lum(hexc):
    c = [int(hexc[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def tokens():
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", ROOT_RE.search(HTML).group(1)))


def check_contrast():
    t = tokens()
    bgs = ("bg-0", "bg-1", "bg-2", "bg-3")
    for fg in ("text-1", "text-2", "text-3", "text-4", "red", "amber", "teal-glow"):
        for bg in bgs:
            r = contrast(t[fg], t[bg])
            assert r >= 4.5, f"--{fg} on --{bg} is {r:.2f}:1, needs 4.5"
    for bg in bgs:
        r = contrast(t["text-5"], t[bg])
        assert r >= 3.0, f"--text-5 on --{bg} is {r:.2f}:1, needs 3.0 (disabled/borders)"
    r = contrast(t["text-1"], t["teal-solid"])
    assert r >= 4.5, f"--text-1 on --teal-solid is {r:.2f}:1, needs 4.5"


def check_no_stray_colors():
    body = ROOT_RE.sub("", HTML, count=1)
    body = re.sub(r'url\("data:[^"]*"\)', "", body)
    stray = re.findall(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", body)
    assert not stray, f"hex colours outside :root: {sorted(set(stray))}"


def check_min_font_size():
    sizes = [float(s) for s in re.findall(r"font-size:\s*([\d.]+)px", HTML)]
    small = [s for s in sizes if s < 12]
    assert not small, f"font sizes below 12px: {small}"


def run():
    checks = [v for k, v in globals().items() if k.startswith("check_")]
    failed = 0
    for fn in checks:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"{len(checks) - failed}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    run()
