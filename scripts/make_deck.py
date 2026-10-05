"""Build the presentation deck (outputs/Perceptor-AI.pptx) from repo config and benchmark data.

Numbers, weights, stages and rules are read from config/, rules/ and outputs/benchmark-results,
so the deck stays in step with the product. Run: python scripts/make_deck.py
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "Perceptor-AI.pptx"


def load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


policy = load(ROOT / "config" / "policy.yaml")
pipeline = load(ROOT / "config" / "pipeline.yaml")
settings = load(ROOT / "config" / "settings.yaml")
bench = json.loads((ROOT / "outputs" / "benchmark-results" / "benchmark.json").read_text(encoding="utf-8"))
rules = [r for f in sorted((ROOT / "rules").glob("*.yaml")) for r in load(f)["rules"]]
product = settings["product"]


def rgb(hex_: str) -> RGBColor:
    hex_ = hex_.lstrip("#")
    return RGBColor(int(hex_[0:2], 16), int(hex_[2:4], 16), int(hex_[4:6], 16))


# Palette follows frontend/app/globals.css.
BG, RAISE, INK, MUTED = rgb("04050a"), rgb("0d111a"), rgb("f6f8fc"), rgb("a8b1c4")
CYAN, VIOLET, MAGENTA, AMBER, ROSE, GOOD = (rgb(c) for c in ("5eead4", "a5b4fc", "f472b6", "fbbf24", "fb7185", "4ade80"))
GROUP_ACCENT = {k: rgb(v["accent"]) for k, v in pipeline["groups"].items()}

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
W, H = prs.slide_width, prs.slide_height
BLANK = prs.slide_layouts[6]


def text(slide, x, y, w, h, value, size=18, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    lines = value if isinstance(value, list) else [value]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(6)
        run = p.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(size), bold, color, "Calibri"
    return box


def card(slide, x, y, w, h, accent=CYAN, fill=RAISE):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shp.adjustments[0] = 0.06
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = accent
    shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def new_slide(title: str, kicker: str = ""):
    s = prs.slides.add_slide(BLANK)
    s.background.fill.solid()
    s.background.fill.fore_color.rgb = BG
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.18), H)
    bar.fill.solid()
    bar.fill.fore_color.rgb = CYAN
    bar.line.fill.background()
    if kicker:
        text(s, Inches(0.6), Inches(0.35), Inches(10), Inches(0.4), kicker.upper(), 12, CYAN, True)
    text(s, Inches(0.6), Inches(0.7), Inches(12), Inches(0.9), title, 34, INK, True)
    text(s, Inches(0.6), Inches(7.0), Inches(8), Inches(0.35), product["name"], 11, MUTED)
    text(s, Inches(11.5), Inches(7.0), Inches(1.4), Inches(0.35), str(len(prs.slides)), 11, MUTED, align=PP_ALIGN.RIGHT)
    return s


def cards(slide, items, top=Inches(1.9), cols=3, height=Inches(2.3), accents=None, body_size=14):
    gap = Inches(0.25)
    width = int((W - Inches(1.2) - gap * (cols - 1)) / cols)
    for i, (head, body) in enumerate(items):
        r, c = divmod(i, cols)
        x, y = Inches(0.6) + (width + gap) * c, top + (height + gap) * r
        accent = (accents or [CYAN, VIOLET, MAGENTA, AMBER, GOOD, ROSE])[i % 6]
        card(slide, x, y, width, height, accent)
        text(slide, x + Inches(0.2), y + Inches(0.15), width - Inches(0.4), Inches(0.5), head, 18, accent, True)
        text(slide, x + Inches(0.2), y + Inches(0.7), width - Inches(0.4), height - Inches(0.8), body, body_size, INK)


def bullets(slide, items, top=Inches(1.8), size=20, left=Inches(0.7), width=Inches(11.9)):
    text(slide, left, top, width, Inches(5), ["•  " + i for i in items], size, INK)


# ---------- 1. Title ----------
s = prs.slides.add_slide(BLANK)
s.background.fill.solid()
s.background.fill.fore_color.rgb = BG
text(s, Inches(0.9), Inches(2.0), Inches(11.5), Inches(1.4), product["name"], 72, CYAN, True)
text(s, Inches(0.9), Inches(3.4), Inches(11.5), Inches(1.2), product["short"], 32, INK, True)
text(s, Inches(0.9), Inches(4.6), Inches(11.5), Inches(1.0), product["tagline"], 16, MUTED)
text(s, Inches(0.9), Inches(6.2), Inches(11.5), Inches(0.5), "E-TRONIX'26  |  PS 3: AI Code Review & Release-Risk Assistant", 16, VIOLET)

# ---------- 2. Problem ----------
s = new_slide("Releases fail where a diff cannot see", "The problem")
cards(s, [
    ("The chain", "Authentication is removed from one handler. Eight callers still compile. The tests that would catch it were deleted in the same change."),
    ("Reviewers skim", "Hundreds of PRs merge weekly. Fatigue and LGTM rubber-stamping let bugs and leaked secrets reach production."),
    ("Tools are siloed", "Static tools, tests and CI report separately. Nothing answers: is this release safe, and why?"),
], height=Inches(2.6))
text(s, Inches(0.6), Inches(5.0), Inches(12), Inches(1.5), [
    "Knight Capital (2012): $460M+ lost in 45 minutes.   CrowdStrike (2024): one bad update crashed millions of PCs.",
    "The gap: no tool joins code analysis, security and repository context into one explainable release decision.",
], 16, MUTED)

# ---------- 3. Solution ----------
s = new_slide("Not 'is this code okay?' but 'what breaks if we ship it?'", "Our solution")
labels = policy["decision_labels"]
cards(s, [
    ("Input", "Paste a GitHub URL or upload a zip."),
    ("Analysis", "Parse, diff, rules, blast radius, optional AI review."),
    ("Decision", " / ".join(labels.values()) + ", each with reasons."),
    ("Proof", "Apply repairs, compile, run tests, rescore."),
], cols=4, height=Inches(2.2))
bullets(s, [
    "Every finding keeps its line, evidence, impact and fix.",
    "Works with no model key. The AI only reviews evidence the engine already found.",
    "Exports Markdown and SARIF 2.1.0 for existing security tooling.",
], top=Inches(4.6), size=18)

# ---------- 4. Pipeline ----------
s = new_slide("Evidence first, AI second", "How it works")
nodes = pipeline["nodes"]
bw, bh = Inches(1.3), Inches(0.85)
x0, y0 = Inches(0.6), Inches(1.9)
max_x = max(n["position"]["x"] for n in nodes) or 1
max_y = max(n["position"]["y"] for n in nodes) or 1
span_x, span_y = W - Inches(1.2) - bw, Inches(3.3)
pos = {n["id"]: (x0 + int(span_x * n["position"]["x"] / max_x), y0 + int(span_y * n["position"]["y"] / max_y)) for n in nodes}
for n in nodes:
    for dep in n["depends_on"]:
        (ax, ay), (bx, by) = pos[dep], pos[n["id"]]
        ln = s.shapes.add_connector(1, ax + bw, ay + bh // 2, bx, by + bh // 2)
        ln.line.color.rgb = MUTED
        ln.line.width = Pt(1.25)
for n in nodes:
    x, y = pos[n["id"]]
    accent = GROUP_ACCENT[n["group"]]
    shp = card(s, x, y, bw, bh, accent)
    tf = shp.text_frame
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = n["title"] + (" *" if n.get("optional") else "")
    r.font.size, r.font.bold, r.font.color.rgb, r.font.name = Pt(13), True, accent, "Calibri"
lx = Inches(0.6)
for key, grp in pipeline["groups"].items():
    text(s, lx, Inches(6.3), Inches(2), Inches(0.35), "■ " + grp["label"], 12, GROUP_ACCENT[key], True)
    lx += Inches(1.9)
text(s, Inches(0.6), Inches(6.6), Inches(12), Inches(0.35), "* optional stage. Stages, dependencies and layout are read from config/pipeline.yaml.", 11, MUTED)

# ---------- 5. Capabilities ----------
s = new_slide(f"{len(rules)} detectors across security, regression and quality", "What it finds")
dim_of = policy["category_dimension"]
by_dim = {}
for r in rules:
    by_dim.setdefault(dim_of[r["category"]], []).append(r["title"])
items = [(f"{dim.title()} ({len(t)})", t) for dim, t in by_dim.items()]
cards(s, items[:6], cols=3, height=Inches(2.35), body_size=12)
text(s, Inches(0.6), Inches(6.55), Inches(12), Inches(0.4), "Rules are YAML under rules/. Add a detector without changing code.", 13, MUTED)

# ---------- 6. Blast radius ----------
s = new_slide("See the blast radius, not just the diff", "Repository context")
bullets(s, [
    "Builds a symbol and call graph (tree-sitter + Python AST + NetworkX).",
    "Maps each changed symbol to callers, callees and affected endpoints.",
    "Builds a failure chain from the change up to the endpoint users hit.",
    "Simulate release walks that chain step by step.",
    "Flags regression tests removed while the code they covered was changing.",
], size=22)

# ---------- 7. Scoring ----------
s = new_slide("An explainable score, not a black box", "Release decision")
w = policy["weights"]
x = Inches(0.7)
for i, (k, v) in enumerate(w.items()):
    y = Inches(2.0) + Inches(0.75) * i
    text(s, x, y, Inches(2.3), Inches(0.5), k.title(), 20, INK, True)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, x + Inches(2.4), y + Inches(0.05), int(Inches(5) * v / max(w.values())), Inches(0.4))
    bar.fill.solid()
    bar.fill.fore_color.rgb = [CYAN, VIOLET, MAGENTA, AMBER, GOOD][i % 5]
    bar.line.fill.background()
    text(s, x + Inches(7.6), y, Inches(1), Inches(0.5), f"{int(v * 100)}%", 20, MUTED)
sev = policy["severity_points"]
card(s, Inches(9.2), Inches(1.9), Inches(3.5), Inches(3.9), VIOLET)
text(s, Inches(9.4), Inches(2.0), Inches(3.2), Inches(0.5), "Points per finding", 18, VIOLET, True)
text(s, Inches(9.4), Inches(2.6), Inches(3.2), Inches(3), [f"{k.title()}: {v}" for k, v in sev.items()], 18, INK)
t = policy["thresholds"]
always_set = set(policy.get("always_blocking_severities", []))
always = " or ".join(x.title() for x in policy.get("always_blocking_severities", []))
blocking = " or ".join(x.title() for x in policy.get("blocker_severities", []) if x not in always_set)
scale = policy.get("scoring", {}).get("scale")
text(s, Inches(0.7), Inches(6.0), Inches(12), Inches(0.9), [
    f"Each dimension is 100 x (1 - e^(-points / {scale})): it never caps, so more findings always score higher.  "
    f"Bands: Low 0-{t['low_max']}, Medium {t['low_max'] + 1}-{t['medium_max']}, High {t['medium_max'] + 1}-{t['high_max']}, Critical above.",
    f"Decision is separate from the band: any {always} finding, or a {blocking} finding in a blocking category, means NOT READY.",
], 14, MUTED)

# ---------- 8. Fix and verify ----------
s = new_slide("It proposes a fix, then proves it holds", "Close the loop")
cards(s, [
    ("1. Repair", "Parameterized SQL, secrets moved to the environment, restored checks, tests and pins."),
    ("2. Verify", "Work on a copy. Run compileall and pytest with a timeout. The original tree is untouched."),
    ("3. Rescore", "Before and after on one screen. Blocking findings cleared means the status improves."),
], height=Inches(2.6))
text(s, Inches(0.6), Inches(4.9), Inches(12), Inches(1), "Query-in-loop is deliberately not auto-fixed. It is not a blocker, so the repaired tree ends at READY WITH WARNINGS.", 16, MUTED)

# ---------- 9. Results ----------
d = bench["detection"]
sizes = bench["repository_sizes"]
s = new_slide(f"{d['detected']} of {d['planted']} planted issues found, 0 missed", "Measured results")
cards(s, [
    ("Detection", f"Planted {d['planted']}\nDetected {d['detected']}\nMissed {len(d['missed'])}\nExtra {len(d['unlabeled'])}"),
    ("Decision", f"{d['decision'].replace('_', ' ')}\nScore {d['score']}\nAnalysis {d['seconds']}s"),
    ("Speed", "\n".join(f"{v['files']} files: {v['seconds']}s" for v in sizes.values())),
], height=Inches(2.5))
text(s, Inches(0.6), Inches(4.8), Inches(12), Inches(1.2),
     "Honest scope: this is a controlled regression fixture (tests/fixtures.py), not a general detection rate. Real-repository accuracy is the next measurement. Source: outputs/benchmark-results/benchmark.json.",
     16, AMBER)

# ---------- 10. Stack / Planned ----------
llm = settings["llm"]
s = new_slide("Built today, planned next", "Stack and roadmap")
cards(s, [
    ("Implemented", f"FastAPI + SSE, Next.js graph UI\nTree-sitter, Python AST, NetworkX\nYAML rules, SQLite cache\nLLM via {llm['provider'].title()} ({llm['model']})\nMarkdown + SARIF reports"),
    ("Limits (stated)", "Deep analysis: Python and JavaScript\nSandbox: copied workspace + timeout, not a container\nRisk weights: prototype policy\nAccuracy on real repos: not yet measured"),
    ("Planned", "GitHub Action / PR comment bot\nSemgrep, Gitleaks, OSV integrations\nContainer sandbox\nMore languages\nWeights calibrated on incident data"),
], accents=[GOOD, AMBER, VIOLET], height=Inches(3.6))

# ---------- 11. Impact / close ----------
s = new_slide("Know what will break, why, and whether the fix holds", "Impact")
bullets(s, [
    "Developers: instant, evidence-backed feedback.",
    "Reviewers: focus on design, not tracing callers by hand.",
    "Security teams: SARIF output and an audit trail per finding.",
    "Release managers: one clear go or no-go with reasons.",
], size=22)
text(s, Inches(0.7), Inches(5.0), Inches(12), Inches(0.8), "Live app: perceptor-ai-release.vercel.app   |   github.com/Itx-Ace7/PERCEPTOR-ai", 18, CYAN, True)
text(s, Inches(0.7), Inches(5.8), Inches(12), Inches(0.6), "Thank you. Questions?", 28, INK, True)

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print("saved", OUT, "slides:", len(prs.slides))
