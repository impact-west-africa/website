#!/usr/bin/env python3
"""Compile the Claude Design export (*.dc.html) into the static site under site/.

The export is a design-canvas document: a React runtime (support.js) renders
`{{ expr }}` interpolation, <sc-if> conditionals, <image-slot> custom elements
and `style-hover` / `style-focus` attributes. None of that survives on a static
host, so this script resolves it all ahead of time into plain HTML + CSS.

Usage:  python3 tools/convert-design.py [SRC_DIR]
"""

import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Downloads/Website project discussion-2")
OUT = os.path.join(REPO, "site")

SITE_URL = "https://impactwestafrica.org"
CONTACT_EMAIL = "info@impactwestafrica.org"
SIGNUP_URL = "https://impact-west-africa.epistle.org/subscribe"

# The design shipped a "#give" placeholder for the donate button; giving now
# happens in an embedded DonorBox form further down the page.
GIVE_URL = "#donate"
FORMSPREE_URL = "https://formspree.io/f/mnpqloqd"
DONORBOX_CAMPAIGN = "impact-west-africa"

PAGES = [
    dict(src="Home.dc.html", out="index.html", url="/",
         title="IMPACT West Africa",
         desc="Spiritually IMPACTing the unreached in West Africa through "
              "agricultural development, medical care, and gospel transformation."),
    dict(src="About.dc.html", out="about/index.html", url="/about/",
         title="About — IMPACT West Africa",
         desc="Tom and Suja Brane have served in West Africa for fourteen years, "
              "teaching Farming God's Way and caring for patients at the Beersheba "
              "Development Farm clinic in Senegal."),
    dict(src="Get Involved.dc.html", out="get-involved/index.html",
         url="/get-involved/",
         title="Get Involved — IMPACT West Africa",
         desc="Pray with us, subscribe to Brane Family Snippets, or get in touch "
              "about partnering with the work in West Africa."),
    dict(src="Give.dc.html", out="give/index.html", url="/give/",
         title="Give — IMPACT West Africa",
         desc="Your generosity helps IMPACT West Africa invest in people and "
              "communities through agricultural development, medical care, and "
              "the transforming hope of the Gospel."),
]

LINKS = {
    "Home.dc.html": "/",
    "About.dc.html": "/about/",
    "Get Involved.dc.html": "/get-involved/",
    "Get%20Involved.dc.html": "/get-involved/",
    "Give.dc.html": "/give/",
}

# Template variables resolved from each page's DCLogic renderVals().
VARS = {
    "contactEmail": CONTACT_EMAIL,
    "mailto": "mailto:" + CONTACT_EMAIL,
    "signupUrl": SIGNUP_URL,
    "giveUrl": GIVE_URL,
}

# <sc-if> conditions, evaluated at build time. `sent` is the contact form's
# success panel — kept in the DOM and toggled by JS after the Formspree POST.
SC_IF = {"showBoard": True, "sent": "keep-hidden", "notSent": True}

# <image-slot> has no alt attribute; the design used `placeholder` as editor
# chrome. Real alt text, written here.
# Slots rendered above the fold, excluded from lazy-loading.
EAGER = {"hero-baobab"}

ALT = {
    "hero-baobab": "Farmland at the Beersheba Development Farm in Senegal",
    "why-portrait": "Portrait of a woman in West Africa",
    "gallery-1": "Teaching a Farming God's Way training session",
    "gallery-2": "Suja Brane treating a patient at the rural clinic",
    "gallery-3": "Farmers in a hands-on agricultural training",
    "gallery-4": "A village in rural Senegal",
    "gallery-5": "Caring for a patient at the clinic",
    "gallery-6": "Harvested crops from a Farming God's Way field",
    "story-photo": "The Brane family",
    "strategy-embrace": "Two women embracing",
    "give-photo-v2": "A farmer with his harvest",
    "pray-photo-v2": "Praying with a patient at the clinic",
    "board-1": "Tom Brane", "board-2": "Brian Smith", "board-3": "Dennis McDaniel",
    "board-4": "Minta Berry", "board-5": "Dean Heitkamp", "board-6": "Suja Brane",
}

# Resize/re-encode plan. The export ships full-resolution originals (~36 MB
# total, a 17 MB home page); these are the sizes the layout actually renders
# at, doubled for retina.  (max_width, output_format)
IMAGES = {
    "hero-field.jpg": (2000, "jpg"),
    "portrait-bw.jpg": (1200, "jpg"),
    "teaching.jpg": (1000, "jpg"),
    "clinic.jpg": (1000, "jpg"),
    "training.png": (1000, "jpg"),
    "village.png": (1000, "jpg"),
    "care.png": (1000, "jpg"),
    "harvest.jpg": (1000, "jpg"),
    "family.jpg": (1200, "jpg"),
    "embrace.jpg": (1200, "jpg"),
    "give-harvest3.jpg": (1200, "jpg"),
    "pray-med-b.jpg": (1200, "jpg"),
    "board-tom.jpg": (360, "jpg"),
    "board-brian.jpg": (280, "jpg"),
    "board-dennis.jpg": (280, "jpg"),
    "board-minta.jpg": (280, "jpg"),
    "board-dean.jpg": (280, "jpg"),
    "board-suja.jpg": (280, "jpg"),
    "logo-dark.png": (400, "png"),
    "logo-light.png": (400, "png"),
    "cama-logo.jpg": (160, "jpg"),
    "medsend-logo.png": (340, "png"),
    "fgw-logo.png": (160, "png"),
    "give-qr.png": (320, "png"),
    "snippets-qr.png": (240, "png"),
}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


def interp(text):
    """Resolve `{{ var }}` against VARS."""
    def sub(m):
        name = m.group(1).strip()
        if name not in VARS:
            raise SystemExit("unresolved template var: {{ %s }}" % name)
        return VARS[name]
    return re.sub(r"\{\{\s*([^}]+?)\s*\}\}", sub, text)


def decls(style):
    """Split a style attribute into declarations, each marked !important.

    The runtime applied these as inline styles on hover/focus, which beat the
    element's own inline style. A class rule does not, so force it.
    """
    out = []
    for d in style.split(";"):
        d = d.strip()
        if d:
            out.append(d + "!important")
    return ";".join(out)


class Compiler(HTMLParser):
    def __init__(self, page, assets):
        super().__init__(convert_charrefs=False)
        self.page = page
        self.assets = assets      # original filename -> published filename
        self.buf = []
        self.rules = []           # generated CSS rules
        self.classes = {}         # (pseudo, css) -> class name
        self.skip_depth = 0       # >0 while inside a dropped <sc-if>
        self.sc_stack = []        # 'keep' | 'drop' | 'hide' per open <sc-if>
        self.slot_depth = 0       # >0 while inside a replaced <image-slot>

    # -- helpers ----------------------------------------------------------
    def emit(self, s):
        if not self.skip_depth:
            self.buf.append(s)

    def klass(self, pseudo, style):
        key = (pseudo, style)
        if key not in self.classes:
            name = "%s%d" % (pseudo[0], len(self.classes) + 1)
            self.classes[key] = name
            self.rules.append(".%s:%s{%s}" % (name, pseudo, decls(style)))
        return self.classes[key]

    def asset(self, path):
        """assets/foo.png -> /assets/foo.jpg (root-absolute, post-optimisation)."""
        name = path.split("/")[-1]
        return "/assets/" + self.assets.get(name, name)

    def rewrite_attrs(self, tag, attrs):
        out, extra_class = [], []
        for k, v in attrs:
            if k.startswith("on"):
                continue      # design-canvas event bindings, not real handlers
            if v is None:
                out.append((k, None))
                continue
            v = interp(v)
            if k in ("style-hover", "style-focus"):
                extra_class.append(self.klass(k.split("-")[1], v))
                continue
            if k == "href" and not v.startswith(("http", "mailto:", "#", "/")):
                v = LINKS.get(v, v)
            elif k in ("src", "href") and v.startswith("assets/"):
                v = self.asset(v)
            if k == "required" and v == "true":
                v = None
            out.append((k, v))
        if extra_class:
            merged = " ".join(extra_class)
            for i, (k, v) in enumerate(out):
                if k == "class":
                    out[i] = (k, v + " " + merged)
                    break
            else:
                out.append(("class", merged))
        return out

    def render(self, tag, attrs, self_close=False):
        parts = ["<" + tag]
        for k, v in attrs:
            if v is None:
                parts.append(" " + k)
            else:
                parts.append(' %s="%s"' % (k, html.escape(v, quote=True)))
        parts.append("/>" if (self_close and tag not in VOID) else ">")
        return "".join(parts)

    # -- image-slot -------------------------------------------------------
    def image_slot(self, attrs):
        """Replace <image-slot> with a cropping frame + <img>.

        Reproduces the component's geometry: :host is display:block /
        position:relative / 100%x100% with a 3:2 default aspect-ratio, .frame
        clips, and the image is cover-fit then transformed by the saved crop
        (scale s, offset x/y as a percentage of the frame).
        """
        a = dict(attrs)
        sid = a.get("id", "")
        src = a.get("src", "")
        shape = (a.get("shape") or "rounded").lower()
        fit = (a.get("fit") or "cover").lower()
        radius = {"circle": "50%", "pill": "9999px"}.get(shape, "")
        if shape == "rounded":
            radius = (a.get("radius") or "12") + "px"

        view = STATE.get(sid) or {}
        if view.get("u"):                      # image replaced in the editor
            src = "assets/" + SIDECAR_FILES[sid]
        s = float(view.get("s", 1) or 1)
        x = float(view.get("x", 0) or 0)
        y = float(view.get("y", 0) or 0)

        img_style = "width:100%;height:100%;object-fit:" + fit
        if (s, x, y) != (1.0, 0.0, 0.0):
            img_style += ";transform:translate(%.4f%%,%.4f%%) scale(%.6f)" % (x, y, s)

        frame = ("display:block;position:relative;overflow:hidden;"
                 "width:100%;height:100%;aspect-ratio:3/2")
        if radius:
            frame += ";border-radius:" + radius
        if a.get("style"):
            frame += ";" + a["style"]

        loading = ('loading="eager" fetchpriority="high"' if sid in EAGER
                   else 'loading="lazy"')
        return ('<div style="{frame}"><img src="{src}" alt="{alt}" '
                '{loading} decoding="async" style="{img}"></div>').format(
            loading=loading,
            frame=html.escape(frame, quote=True),
            src=html.escape(self.asset(src), quote=True),
            alt=html.escape(ALT.get(sid, ""), quote=True),
            img=html.escape(img_style, quote=True))

    # -- parser callbacks -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "sc-if":
            cond = re.sub(r"[{}\s]", "", dict(attrs).get("value", ""))
            verdict = SC_IF.get(cond, False)
            if verdict == "keep-hidden":
                self.sc_stack.append("hide")
                self.emit('<div id="contact-sent" hidden>')
            elif verdict:
                self.sc_stack.append("keep")
            else:
                self.sc_stack.append("drop")
                self.skip_depth += 1
            return
        if tag == "image-slot":
            self.slot_depth += 1
            self.emit(self.image_slot(attrs))
            return
        if self.slot_depth:
            return
        if self.skip_depth:
            if tag not in VOID:
                self.skip_depth += 1
            return
        a = self.rewrite_attrs(tag, attrs)
        if tag == "form":
            # The design's onSubmit only flipped a local `sent` flag without
            # sending anything. Point it at Formspree and let contact.js POST it.
            a = [(k, v) for k, v in a if k != "onsubmit"]
            a = [("id", "contact-form"), ("action", FORMSPREE_URL),
                 ("method", "POST")] + a
            self.emit(self.render(tag, a))
            # Formspree conventions: _subject names the notification email,
            # _gotcha is a honeypot that bots fill in and people never see.
            self.emit('<input type="hidden" name="_subject" '
                      'value="New message from impactwestafrica.org">'
                      '<input type="text" name="_gotcha" tabindex="-1" '
                      'autocomplete="off" aria-hidden="true" '
                      'style="position:absolute;left:-9999px">')
            return
        self.emit(self.render(tag, a))

    def handle_startendtag(self, tag, attrs):
        if tag == "image-slot":
            self.emit(self.image_slot(attrs))
            return
        if self.slot_depth or self.skip_depth:
            return
        self.emit(self.render(tag, self.rewrite_attrs(tag, attrs), self_close=True))

    def handle_endtag(self, tag):
        if tag == "sc-if":
            state = self.sc_stack.pop()
            if state == "drop":
                self.skip_depth -= 1
            elif state == "hide":
                self.emit("</div>")
            return
        if tag == "image-slot":
            self.slot_depth -= 1
            return
        if self.slot_depth:
            return
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag not in VOID:
            self.emit("</%s>" % tag)

    def handle_data(self, data):
        self.emit(interp(data))

    def handle_entityref(self, name):
        self.emit("&%s;" % name)

    def handle_charref(self, name):
        self.emit("&#%s;" % name)

    def handle_comment(self, data):
        pass


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

STATE = {}
SIDECAR_FILES = {}
USED_SLOTS = set()


def sips(src, dst, max_width, fmt):
    fmt_name = {"jpg": "jpeg", "png": "png"}[fmt]
    subprocess.run(
        ["sips", "-s", "format", fmt_name, "-s", "formatOptions", "72",
         "-Z", str(max_width), src, "--out", dst],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_assets():
    """Resize/re-encode every referenced asset into site/assets/.

    Returns {original_filename: published_filename}; extensions change where a
    photo shipped as PNG.
    """
    dst_dir = os.path.join(OUT, "assets")
    os.makedirs(dst_dir, exist_ok=True)
    mapping = {}
    for name, (max_w, fmt) in IMAGES.items():
        out_name = os.path.splitext(name)[0] + "." + fmt
        sips(os.path.join(SRC, "assets", name),
             os.path.join(dst_dir, out_name), max_w, fmt)
        mapping[name] = out_name

    # Slots whose image was replaced in the editor live only in the sidecar,
    # as a data: URL. Write those out as real files.
    for sid, view in STATE.items():
        data_url = view.get("u")
        if not data_url or sid not in USED_SLOTS:
            continue      # sidecar keeps entries for slots since removed
        header, _, payload = data_url.partition(",")
        ext = re.search(r"image/(\w+)", header).group(1)
        tmp = os.path.join(dst_dir, "_tmp." + ext)
        with open(tmp, "wb") as fh:
            fh.write(base64.b64decode(payload))
        out_name = sid + ".jpg"
        sips(tmp, os.path.join(dst_dir, out_name), 1000, "jpg")
        os.remove(tmp)
        SIDECAR_FILES[sid] = out_name
        mapping[out_name] = out_name
    return mapping


# ---------------------------------------------------------------------------
# page assembly
# ---------------------------------------------------------------------------

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{site}{url}">
<meta name="theme-color" content="#f1ead8">
<link rel="icon" href="/assets/logo-dark.png">
<link rel="apple-touch-icon" href="/assets/logo-dark.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="IMPACT West Africa">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{site}{url}">
<meta property="og:image" content="{site}/assets/hero-field.jpg">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&family=Merriweather:ital,wght@0,300;0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
{css}
</style>
{extra_head}</head>
<body>
"""

FOOT = """</body>
</html>
"""

CONTACT_JS = """<script src="/assets/contact.js" defer></script>
"""

DONORBOX_HEAD = ('<script type="module" src="https://donorbox.org/widgets.js" '
                 'async></script>\n')

DONATE_SECTION = """
  <section id="donate" style="background:#ecd9b9;border-top:1px solid rgba(43,43,43,0.1)">
    <div style="max-width:1180px;margin:0 auto;padding:clamp(56px,8vw,96px) clamp(20px,4vw,32px)">
      <div style="display:flex;align-items:center;gap:14px">
        <span style="width:44px;height:1px;background:#cca54f"></span>
        <h2 style="font-size:11px;letter-spacing:0.28em;text-transform:uppercase;color:#487a81;font-weight:600">{eyebrow}</h2>
      </div>
      <p style="font-family:Merriweather,Georgia,serif;font-size:clamp(22px,2.4vw,28px);line-height:1.5;font-weight:300;max-width:720px;margin:22px 0 0">{heading}</p>
      {lead}
      <div style="margin-top:clamp(32px,4vw,48px);max-width:760px;background:#ffffff;padding:clamp(10px,1.6vw,18px)">
        <dbox-widget campaign="{campaign}" type="donation_form" enable-auto-scroll="true"></dbox-widget>
        <noscript>
          <p style="font-size:15px;line-height:1.8;margin:24px 20px;color:rgba(43,43,43,0.8)">The giving form needs JavaScript. You can also <a href="https://donorbox.org/{campaign}" style="border-bottom:1px solid rgba(165,82,41,0.4)">give on our DonorBox page</a>.</p>
        </noscript>
      </div>
    </div>
  </section>

"""

HOME_LEAD = ('<p style="font-size:16px;line-height:1.85;margin:20px 0 0;'
             'max-width:720px;color:rgba(43,43,43,0.82)">Gifts of any size go '
             'directly into the work on the ground. See <a href="/give/" '
             'style="border-bottom:1px solid rgba(165,82,41,0.4)">where your '
             'gift goes</a>.</p>')


def donate_section(eyebrow, heading, lead=""):
    return DONATE_SECTION.format(campaign=DONORBOX_CAMPAIGN, eyebrow=eyebrow,
                                 heading=heading, lead=lead)


# Home: the donate form is the closing call to action, just above the footer.
HOME_ANCHOR = '<footer style="background:#487a81;color:#f1ead8">'

# Give: the form lives inside the "Give online" card, above the QR code. The
# design's auto-fit grid is swapped for an explicit one so the card can be
# ordered ahead of "Why it matters" when the columns stack.
GIVE_CSS = (
    ".give-grid{display:grid;grid-template-columns:minmax(0,1fr);"
    "gap:clamp(36px,5vw,72px);align-items:start}\n"
    ".give-card{order:-1}\n"
    "@media (min-width:900px){"
    ".give-grid{grid-template-columns:minmax(0,1fr) minmax(0,1.1fr)}"
    ".give-card{order:0}}"
)

GIVE_WIDGET = """<div style="margin-top:26px">
          <dbox-widget campaign="{campaign}" type="donation_form" enable-auto-scroll="true"></dbox-widget>
          <noscript>
            <p style="font-size:14px;line-height:1.75;margin:18px 0 0;color:rgba(43,43,43,0.8)">The giving form needs JavaScript. You can also <a href="https://donorbox.org/{campaign}" style="border-bottom:1px solid rgba(165,82,41,0.4)">give on our DonorBox page</a>, or scan the code below.</p>
          </noscript>
        </div>
        """

GIVE_QR_ROW = ('<div style="display:flex;flex-wrap:wrap;align-items:center;'
               'gap:22px;margin-top:28px">')


def give_layout(body):
    """Move the DonorBox form into the "Give online" card, above the QR code."""
    widget = GIVE_WIDGET.format(campaign=DONORBOX_CAMPAIGN)
    edits = [
        ('<div style="display:grid;grid-template-columns:repeat(auto-fit,'
         'minmax(320px,1fr));gap:clamp(36px,5vw,72px);align-items:start">',
         '<div class="give-grid">'),
        ('<div style="background:#ffffff;border-top:3px solid #cca54f;'
         'padding:clamp(28px,4vw,44px)">',
         '<div class="give-card" id="donate" style="background:#ffffff;'
         'border-top:3px solid #cca54f;padding:clamp(28px,4vw,44px)">'),
        ("Scan the code with your phone, or use the button below to give and "
         "direct your gift.",
         "Give once, or set up a recurring gift. Prefer your phone? Scan the "
         "code below."),
        (GIVE_QR_ROW,
         widget + '<div style="display:flex;flex-wrap:wrap;align-items:center;'
         'gap:22px;margin-top:30px;border-top:1px solid rgba(43,43,43,0.12);'
         'padding-top:26px">'),
    ]
    for old, new in edits:
        assert body.count(old) == 1, "Give page layout changed: " + old[:60]
        body = body.replace(old, new)

    # The "Give Now" button pointed at a form that is now on the same screen.
    button = re.search(r'\s*<a href="#donate"[^>]*>Give Now</a>', body)
    assert button, "Give page: donate button not found"
    return body[:button.start()] + body[button.end():]



def compile_page(page, assets, base_css):
    raw = open(os.path.join(SRC, page["src"]), encoding="utf-8").read()

    body = re.search(r"<x-dc>(.*)</x-dc>", raw, re.S).group(1)
    body = body[body.index("</helmet>") + len("</helmet>"):]

    c = Compiler(page, assets)
    c.feed(body)
    c.close()

    body_html = "".join(c.buf).strip() + "\n"

    css = base_css
    extra_head = ""
    if page["url"] == "/give/":
        body_html = give_layout(body_html)
        css += "\n" + GIVE_CSS
        extra_head = DONORBOX_HEAD
    elif page["url"] == "/":
        section = donate_section("Give", "Give to the work in West Africa.",
                                 HOME_LEAD)
        assert HOME_ANCHOR in body_html, "Home page layout changed"
        body_html = body_html.replace(HOME_ANCHOR, section + HOME_ANCHOR, 1)
        extra_head = DONORBOX_HEAD

    # Only keep hover/focus rules whose element survived the edits above.
    used = [r for r in c.rules
            if ('class="%s"' % r[1:r.index(":")]) in body_html
            or (' %s"' % r[1:r.index(":")]) in body_html]
    if used:
        css += "\n" + "\n".join(used)

    doc = HEAD.format(title=html.escape(page["title"]),
                      desc=html.escape(page["desc"]),
                      site=SITE_URL, url=page["url"], css=css,
                      extra_head=extra_head)
    doc += body_html
    if 'id="contact-form"' in doc:
        doc += CONTACT_JS
    doc += FOOT
    return doc


def main():
    global STATE
    sidecar = os.path.join(SRC, ".image-slots.state.json")
    if os.path.exists(sidecar):
        STATE = json.load(open(sidecar))

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)

    for page in PAGES:
        raw = open(os.path.join(SRC, page["src"]), encoding="utf-8").read()
        USED_SLOTS.update(re.findall(r'<image-slot[^>]*\bid="([^"]+)"', raw))

    assets = build_assets()

    # The shared reset/base rules live in each page's <helmet>; they are
    # identical across pages, so take them from the first one.
    first = open(os.path.join(SRC, PAGES[0]["src"]), encoding="utf-8").read()
    base_css = re.search(r"<style>(.*?)</style>", first, re.S).group(1).strip()

    for page in PAGES:
        doc = compile_page(page, assets, base_css)
        dest = os.path.join(OUT, page["out"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print("%-24s %6.1f KB" % (page["out"], len(doc) / 1024))

    shutil.copy(os.path.join(REPO, "tools", "contact.js"),
                os.path.join(OUT, "assets", "contact.js"))
    shutil.copy(os.path.join(REPO, "tools", "404.html"),
                os.path.join(OUT, "404.html"))
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    with open(os.path.join(OUT, "CNAME"), "w") as fh:
        fh.write("impactwestafrica.org\n")

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(OUT) for f in fs)
    print("site total: %.1f MB" % (total / 1024 / 1024))


if __name__ == "__main__":
    main()
