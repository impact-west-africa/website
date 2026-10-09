#!/usr/bin/env python3
"""Compile the Claude Design export (*.dc.html) into the static site under site/.

The export is a design-canvas document: a React runtime (support.js) renders
`{{ expr }}` interpolation, <sc-if> conditionals, <sc-for> loops, <image-slot>
custom elements and `style-hover` / `style-focus` attributes. None of that
survives on a static host, so this script resolves it all ahead of time into
plain HTML + CSS.

Three pieces of the design are interactive, and all three are rebuilt here
without JavaScript:

  * the header (dropdown menus on desktop, a hamburger panel on mobile) is
    thrown away and replaced by HEADER below - CSS :hover/:focus-within for the
    dropdowns, <details> for the mobile panel and its accordions;
  * the home hero (eight photos crossfading on a timer, with clickable dots) is
    replaced by HERO below - a CSS animation, plus radio inputs that pin one
    slide and stop the animation the way the design's dots did;
  * the "How We Serve" tabs become :target-selected panels, so #agriculture and
    friends keep working as deep links.

Usage:  python3 tools/convert-design.py [SRC_DIR]
"""

import datetime
import hashlib
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
    "~/Downloads/Website project discussion-5")
OUT = os.path.join(REPO, "site")

SITE_URL = "https://impactwestafrica.org"
CONTACT_EMAIL = "info@impactwestafrica.org"
SIGNUP_URL = "https://impact-west-africa.epistle.org/subscribe"
FORMSPREE_URL = "https://formspree.io/f/mnpqloqd"
CHURCH_CENTER_URL = "https://impact-west-africa-inc-544195.churchcenter.com/giving"
# The query param is what tells modal/v1 to intercept the click. Without
# JavaScript the link is still a plain link to the same giving page.
CHURCH_CENTER_MODAL = CHURCH_CENTER_URL + "?open-in-church-center-modal=true"

YEAR = datetime.date.today().year

PAGES = [
    dict(src="Home v2.dc.html", out="index.html", url="/", nav="home",
         title="IMPACT West Africa",
         desc="Spiritually IMPACTing the unreached in West Africa through "
              "agricultural development, medical care, and gospel transformation."),
    dict(src="About.dc.html", out="about/index.html", url="/about/", nav="about",
         title="About — IMPACT West Africa",
         desc="Who we are, how we work, and the board that guides IMPACT West "
              "Africa — the ministry of Tom and Suja Brane in Senegal."),
    dict(src="How We Serve.dc.html", out="how-we-serve/index.html",
         url="/how-we-serve/", nav="serve",
         title="How We Serve — IMPACT West Africa",
         desc="Farming God's Way training, rural medical care, and humanitarian "
              "relief in Senegal — meeting real needs and sharing Jesus."),
    dict(src="Get Involved.dc.html", out="get-involved/index.html",
         url="/get-involved/", nav="involved",
         title="Get Involved — IMPACT West Africa",
         desc="Pray with us, subscribe to Brane Family Snippets, or get in touch "
              "about partnering with the work in West Africa."),
    dict(src="Give.dc.html", out="give/index.html", url="/give/", nav="give",
         title="Give — IMPACT West Africa",
         desc="Give online through Planning Center or by mail. Your generosity "
              "helps meet real felt needs while opening doors for the Gospel."),
]

# Design filename (as it appears in href, URL-encoded or not) -> published path.
LINKS = {
    "Home v2.dc.html": "/",
    "Home%20v2.dc.html": "/",
    "Home.dc.html": "/",
    "About.dc.html": "/about/",
    "How We Serve.dc.html": "/how-we-serve/",
    "How%20We%20Serve.dc.html": "/how-we-serve/",
    "Get Involved.dc.html": "/get-involved/",
    "Get%20Involved.dc.html": "/get-involved/",
    "Give.dc.html": "/give/",
}

# Template variables resolved from each page's DCLogic renderVals().
# achSign/helpSign are the +/- on the Give page accordions; both glyphs are
# emitted and CSS shows whichever matches the <details> state.
SIGN = ('<span class="s-plus">+</span><span class="s-minus">−</span>')
VARS = {
    "contactEmail": CONTACT_EMAIL,
    "mailto": "mailto:" + CONTACT_EMAIL,
    "signupUrl": SIGNUP_URL,
    "giveUrl": CHURCH_CENTER_MODAL,
    "year": str(YEAR),
    "achSign": SIGN,
    "helpSign": SIGN,
    # Responsive grid values on the Agriculture panel. These are the narrow
    # (< 700px) values; AG_CSS overrides them above that width.
    "agCols": "minmax(0,1fr)",
    "agAreas": '"intro" "media" "rest" "media2"',
    "agRowGap": "28px",
    "agSqCols": "repeat(2,minmax(0,1fr))",
}

# <sc-if> conditions, resolved at build time.
#   True            keep the children, drop the wrapper
#   False           drop the subtree
#   "hidden"        keep, wrapped in a hidden div (the contact success panel)
#   ("panel", id)   keep, wrapped in a :target-selected How-We-Serve panel
#   ("class", c)    keep, adding a class to each immediate child element
#   "details"       keep; the preceding <button> already opened a <details>
SC_IF = {
    "isStory": True, "isBoard": True, "isPartners": True,
    "notSent": True,
    "sent": "hidden",
    "isHeart": ("panel", "heart"),
    "isAg": ("panel", "agriculture"),
    "isMed": ("panel", "medical"),
    "isHum": ("panel", "humanitarian"),
    "agWide": ("class", "ag-wide"),
    "agNarrow": ("class", "ag-narrow"),
    "achOpen": "details",
    "helpOpen": "details",
}

# In-page links to rewrite, per route. On /give/ the hero's "Give Online"
# button opened the Planning Center modal in the design's intent, not a scroll
# to the card below it; the card keeps its #give-online id so the nav dropdown
# and "Ways to give" deep links still land there.
HREF_OVERRIDES = {
    "/give/": {"#give-online": CHURCH_CENTER_MODAL},
}

# Extra classes to hang on an element, per route, keyed by a snippet of its
# raw style attribute. Used where one element on one page needs a rule that
# an inline style cannot express (a media query).
CLASS_OVERRIDES = {
    # The "Meeting physical needs / Building relationships / ..." line under
    # the Give hero. It wraps to three lines on a phone, where centring reads
    # better than the ragged left-aligned block.
    "/give/": {"letter-spacing:0.05em;font-weight:500;margin:20px 0 0;"
               "color:#bcdce0": "tagline-center"},
}

TAGLINE_CSS = "\n@media (max-width:699px){.tagline-center{text-align:center}}\n"

# onClick handlers that turn a <button> into a <summary> (Give page accordions).
ACCORDION_TOGGLES = {"toggleAch", "toggleHelp"}

# The one <sc-for> in the export: the How We Serve tab strip.
SERVE_TABS = [("heart", "Heart for the Poor"), ("agriculture", "Agriculture"),
              ("medical", "Medical"), ("humanitarian", "Humanitarian")]

# <image-slot> has no alt attribute; `placeholder` was editor chrome. Real alt
# text, written here. Slots not listed get alt="" (decorative).
EAGER = {"hero-1"}      # above the fold, excluded from lazy-loading

ALT = {
    # home hero
    "hero-1": "Tom Brane pouring water over soil to demonstrate runoff at an "
              "outdoor farming training",
    "hero-2": "A group of smiling children in a Senegalese village",
    "hero-4": "A farmer standing with his arms raised in a tall field of maize",
    "hero-5": "A woman being baptized while the congregation looks on",
    "hero-6b": "Suja Brane listening to a young child's chest with a stethoscope",
    "hero-7": "Farmers kneeling in a circle to pray at the edge of a field",
    "hero-8": "Suja Brane fitting a leg brace for a young man in a wheelchair",
    "hero-9": "Children and a visitor playing with a ball beside a child lying "
              "on a mat",
    # home body
    "why-portrait-v2": "Black and white portrait of children in a Senegalese "
                       "village",
    "strategy-embrace-v2": "A girl smiling over the shoulder of the worker "
                           "carrying her at the farm",
    "sq2b": "A boy holding two bicycle tires in a village street",
    "sq1": "Tom Brane and farmers kneeling together in a field",
    "sq8": "Suja Brane laughing with a Senegalese friend",
    "sq5": "Mulched garden rows of carrots and onions at the Beersheba farm",
    "sq6b": "Tom and Suja Brane visiting a patient resting on a mat at home",
    "sq7": "A young woman standing in front of a thatched hut",
    "sq3": "A farmer standing in front of a towering stand of sorghum",
    "sq9": "A girl sitting on a donkey cart in a village",
    # how we serve
    "serve-heart-1c": "Tom and Suja Brane sitting with a village family around "
                      "a cooking fire",
    "serve-heart-2c": "A young man walking with a new walker, supported by "
                      "visitors and his mother",
    "serve-ag-1c": "Tom Brane sitting in a field talking with a circle of farmers",
    "serve-ag-3d": "A woman planting seed by hand in a prepared field",
    "serve-ag-3d-m": "A woman planting seed by hand in a prepared field",
    "serve-ag-sq1": "A farmer harvesting bitter eggplant into buckets",
    "serve-ag-sq2": "Mulched rows of carrots and onions under drip irrigation",
    "serve-ag-sq3": "A bucket filled with freshly picked green peppers",
    "serve-ag-sq4": "A farmer kneeling in a thriving field of beans",
    "serve-ag-sq5": "A large group of farmers at a Farming God's Way training",
    "serve-ag-sq6": "Trainees gathered in a field during the West Africa "
                    "regional training",
    "serve-ag-collage": "Scenes from the West Africa Farming God's Way regional "
                        "training",
    "serve-med-1e": "Suja Brane holding the hand of a child with a feeding tube",
    "serve-med-2d": "A health worker measuring a child's arm during a screening",
    "serve-med-3b": "A teenager helping a girl walk in a village courtyard",
    "serve-med-4d": "A young man smiling in his wheelchair",
    "serve-med-6b": "A girl with a cast on her leg eating a meal",
    "serve-med-5c": "Suja Brane talking with a patient in a wheelchair at the "
                    "clinic",
    "serve-hum-1c": "Children waving outside shelters in a displacement camp",
    "serve-hum-2c": "Villagers standing behind sacks of grain and bottles of oil "
                    "ready for distribution",
    "serve-hum-4": "Tarpaulin shelters stretching across a displacement camp",
    # about
    "story-photo": "Tom and Suja Brane with Anna, Naomi, and Josiah",
    "story-photo-2012c": "The Brane family in West Africa in 2013",
    "story-photo-kidsb": "Anna, Naomi, and Josiah on the Purdue University "
                         "campus in 2025",
    "board-1": "Tom Brane", "board-2": "Brian Smith", "board-3": "Dennis McDaniel",
    "board-4": "Minta Berry", "board-5b": "Dean Heitkamp", "board-6": "Suja Brane",
    # get involved / give
    "pray-photo-v3": "Suja Brane reading the Bible with a mother and her children",
    "give-photo-v3": "Suja Brane with a boy trying out a new adaptive trike",
    "give-stay-baobab": "A baobab tree on a small island in a Senegalese river",
}

# Resize/re-encode plan: export path -> (published name, max width).
# The export's `w/` folder is already crop-corrected for the layout; this only
# re-encodes to the size the page renders at (doubled for retina) and gives the
# files names that mean something.
IMAGES = {
    # brand
    "logo-teal-tag.png": ("logo.png", 600),
    "badge-impact-footer.png": ("badge-footer.png", 400),
    "medsend-logo.png": ("medsend-logo.png", 560),
    "fgw-logo.png": ("fgw-logo.png", 320),
    "beersheba-logo.png": ("beersheba-logo.png", 320),
    "w/cama-logo.jpg": ("cama-logo.jpg", 300),
    "icon-impact-32.png": ("favicon-32.png", 32),
    "icon-impact-180.png": ("apple-touch-icon.png", 180),
    "icon-impact-512.png": ("icon-512.png", 512),
    # home hero
    "w/h2.jpg": ("hero-training.jpg", 1400),
    "w/h3.jpg": ("hero-children.jpg", 1400),
    "w/h5c.jpg": ("hero-maize.jpg", 1400),
    "w/hero-baptism.jpg": ("hero-baptism.jpg", 1400),
    "w/h-suja-bw.jpg": ("hero-clinic.jpg", 1400),
    "w/h8.jpg": ("hero-prayer.jpg", 1400),
    "w/h-brace.jpg": ("hero-brace.jpg", 1400),
    "w/h-play.jpg": ("hero-visit.jpg", 1400),
    # home body
    "w/portrait-bw.jpg": ("portrait-bw.jpg", 1200),
    "w/map-africa-physical.jpg": ("map-africa.jpg", 700),
    "w/embrace.jpg": ("embrace.jpg", 1200),
    "w/sq-tires.jpg": ("sq-tires.jpg", 700),
    "w/b3c.jpg": ("sq-field-team.jpg", 700),
    "w/b6.jpg": ("sq-friends.jpg", 700),
    "w/b8.jpg": ("sq-garden-rows.jpg", 700),
    "w/sq-clinic-mat.jpg": ("sq-home-visit.jpg", 700),
    "w/b2.jpg": ("sq-portrait.jpg", 700),
    "w/b4b.jpg": ("sq-sorghum.jpg", 700),
    "w/sq-cart.jpg": ("sq-cart.jpg", 700),
    # how we serve
    "w/heart-village.jpg": ("serve-heart-village.jpg", 1200),
    "w/heart-walker-top.jpg": ("serve-heart-walker.jpg", 1200),
    "w/ag-circle.jpg": ("serve-ag-circle.jpg", 1200),
    "w/ag-planting.jpg": ("serve-ag-planting.jpg", 1200),
    "w/ag-sq1.jpg": ("serve-ag-sq1.jpg", 700),
    "w/ag-sq2.jpg": ("serve-ag-sq2.jpg", 700),
    "w/ag-sq3.jpg": ("serve-ag-sq3.jpg", 700),
    "w/ag-sq4.jpg": ("serve-ag-sq4.jpg", 700),
    "w/ag-sq5.jpg": ("serve-ag-sq5.jpg", 700),
    "w/ag-sq6.jpg": ("serve-ag-sq6.jpg", 700),
    "w/ag-collage.jpg": ("serve-ag-training.jpg", 1200),
    "w/med-large1d.jpg": ("serve-med-child.jpg", 1200),
    "w/med-large3b.jpg": ("serve-med-screening.jpg", 1200),
    "w/med-sq1.jpg": ("serve-med-sq1.jpg", 700),
    "w/med-sq2.jpg": ("serve-med-sq2.jpg", 700),
    "w/med-sq5.jpg": ("serve-med-sq3.jpg", 700),
    "w/med-sq6.jpg": ("serve-med-sq4.jpg", 700),
    "w/hum-kids-wave.jpg": ("serve-hum-kids.jpg", 1200),
    "w/hum-food.jpg": ("serve-hum-food.jpg", 1200),
    "w/hum-burned.jpg": ("serve-hum-camp.jpg", 1200),
    # about
    "w/family.jpg": ("family.jpg", 1200),
    "w/family-2012-crop2.jpg": ("family-2013.jpg", 1000),
    "w/kids-purdue-crop.jpg": ("kids-2025.jpg", 1000),
    "w/board-tom.jpg": ("board-tom.jpg", 320),
    "w/board-brian.jpg": ("board-brian.jpg", 320),
    "w/board-dennis.jpg": ("board-dennis.jpg", 320),
    "w/board-minta.jpg": ("board-minta.jpg", 320),
    "w/board-dean.jpg": ("board-dean.jpg", 320),
    "w/board-suja.jpg": ("board-suja.jpg", 320),
    # get involved / give
    "w/pray-bible.jpg": ("pray-bible.jpg", 1000),
    "w/give-wheelchair.jpg": ("give-wheelchair.jpg", 1200),
    "w/epistle-baobab-43.jpg": ("baobab.jpg", 1200),
}

SOCIAL_IMAGE = "hero-training.jpg"

# Cache busting. GitHub Pages serves everything with `Cache-Control:
# max-age=600` and gives no way to change that, so a browser can hold a stale
# asset for ten minutes after a deploy - and much longer for anything it
# already has open. Every asset URL therefore carries ?v=<hash of that file's
# bytes>, so a changed file gets a new URL and an unchanged one does not. A
# single build-wide stamp (the commit hash) would work too, but it would expire
# all 7 MB of photographs on every deploy, including the ones that did not
# change. Filled in by build_assets().
ASSET_VERSIONS = {}


def asset_url(name):
    """/assets/logo.png -> /assets/logo.png?v=1a2b3c4d"""
    version = ASSET_VERSIONS.get(name)
    if version is None:
        raise SystemExit("unknown asset: " + name)
    return "/assets/%s?v=%s" % (name, version)


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
# The design's header is a React widget: `isDesktop`/`isMobile` branches chosen
# from window.innerWidth, hover-opened dropdowns, and a hamburger panel with
# accordions. Rather than try to resolve that, the whole <header> is dropped
# and this one is emitted in its place - same markup shape, same colours, but
# driven by a media query, :hover/:focus-within and <details>.

NAV = [
    ("home", "Home", "/", []),
    ("about", "About", "/about/", [
        ("Our Story", "#story"),
        ("Board of Directors", "#board"),
        ("Our Partners", "#partners")]),
    ("serve", "How We Serve", "/how-we-serve/", [
        ("Heart for the Poor", "#heart"),
        ("Agriculture", "#agriculture"),
        ("Medical", "#medical"),
        ("Humanitarian", "#humanitarian")]),
    ("involved", "Get Involved", "/get-involved/", [
        ("Pray With Us", "#pray"),
        ("Stay Connected", "#snippets"),
        ("Contact Us", "#contact")]),
    ("give", "Give", "/give/", [
        ("Give Online", "#give-online"),
        ("Give by Mail", "#give-mail")]),
]


def header(active):
    """Site header for `active` (one of the NAV keys)."""
    desktop, mobile = [], []
    for key, label, href, subs in NAV:
        give = key == "give"
        cur = key == active
        cls = "nav-give" if give else ("nav-top nav-cur" if cur else "nav-top")
        aria = ' aria-current="page"' if cur else ""
        link = '<a href="%s" class="%s"%s>%s</a>' % (href, cls, aria, label)

        if not subs:
            desktop.append(link)
            mobile.append('<a href="%s" class="m-top m-row"%s>%s</a>'
                          % (href, aria, label))
            continue

        items = "".join('<a href="%s%s">%s</a>' % (href, frag, text)
                        for text, frag in subs)
        desktop.append(
            '<div class="nav-item">%s<div class="dd%s"><div class="dd-in">%s'
            '</div></div></div>' % (link, " dd-right" if give else "", items))
        if give:
            # The mobile panel closes with a full-width Give button and the two
            # giving links under it, rather than an accordion.
            mobile.append(
                '<a href="%s" class="m-give"%s>Give</a>'
                '<div class="m-give-sub">%s</div>' % (href, aria, items))
            continue
        mobile.append(
            '<details class="m-sec"><summary><a href="%s" class="m-top"%s>%s</a>'
            '<span class="m-sign">%s</span></summary><div class="m-sub">%s</div>'
            '</details>' % (href, aria, label, SIGN, items))

    return HEADER.format(logo=asset_url("logo.png"),
                         desktop="\n        ".join(desktop),
                         mobile="\n          ".join(mobile))


HEADER = """  <header class="site-head">
    <div class="head-in">
      <a href="/" class="brand">
        <img src="{logo}" width="600" height="149" alt="IMPACT — Impacting West Africa for Christ">
      </a>
      <nav class="nav-d" aria-label="Main">
        {desktop}
      </nav>
      <div class="nav-m">
        <a href="/give/" class="nav-give nav-give-m">Give</a>
        <details class="mnav">
          <summary aria-label="Menu"><span class="s-plus">☰</span><span class="s-minus">✕</span></summary>
          <div class="mpanel">
          {mobile}
          </div>
        </details>
      </div>
    </div>
  </header>
"""

NAV_CSS = """
.site-head{position:sticky;top:0;z-index:50;background:rgba(241,234,216,0.95);backdrop-filter:blur(8px);border-bottom:1px solid rgba(43,43,43,0.1)}
.head-in{max-width:1180px;margin:0 auto;padding:14px clamp(20px,4vw,32px);display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px 24px}
.brand{display:flex;align-items:center;gap:12px;min-width:0;color:#2b2b2b}
.brand img{height:clamp(52px,6vw,64px);width:auto;object-fit:contain}
.nav-d{display:flex;flex-wrap:wrap;align-items:center;gap:14px clamp(14px,2vw,26px)}
.nav-m{display:none;align-items:center;gap:10px}
.nav-top{font-size:12px;letter-spacing:0.14em;text-transform:uppercase;color:#2b2b2b}
.nav-cur{font-weight:600;border-bottom:1px solid #cca54f;padding-bottom:3px}
.nav-give{padding:11px 24px;background:#a55229;color:#f1ead8;border-radius:2px;font-size:12px;font-weight:600;letter-spacing:0.16em;text-transform:uppercase}
.nav-give:hover{background:#2b2b2b;color:#f1ead8}
.nav-item{position:relative;display:flex;align-items:center}
.dd{position:absolute;top:100%;left:-18px;padding-top:14px;z-index:70;display:none}
.dd-right{left:auto;right:0}
.nav-item:hover>.dd,.nav-item:focus-within>.dd{display:block}
.dd-in{background:#ffffff;border:1px solid rgba(43,43,43,0.12);box-shadow:0 12px 32px rgba(0,0,0,0.14);display:flex;flex-direction:column;padding:6px 0;min-width:230px}
.dd-in a{padding:12px 18px;font-size:12px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:#2b2b2b;white-space:nowrap}
.dd-in a:hover{background:#f1ead8;color:#a55229}
.mnav>summary{width:44px;height:44px;display:flex;align-items:center;justify-content:center;border:1px solid rgba(43,43,43,0.2);border-radius:2px;cursor:pointer;font-size:20px;color:#2b2b2b;list-style:none}
.mnav>summary::-webkit-details-marker{display:none}
.mpanel{position:absolute;top:100%;left:0;right:0;background:#f1ead8;border-top:1px solid rgba(43,43,43,0.1);box-shadow:0 18px 30px rgba(0,0,0,0.12);max-height:calc(100vh - 80px);overflow-y:auto;padding:4px clamp(20px,4vw,32px) 28px;display:flex;flex-direction:column}
.m-row,.m-sec{border-bottom:1px solid rgba(43,43,43,0.1)}
.m-top{display:block;padding:16px 0;font-size:14px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:#2b2b2b}
.m-sec>summary{display:flex;align-items:center;justify-content:space-between;cursor:pointer;list-style:none}
.m-sec>summary::-webkit-details-marker{display:none}
.m-sign{width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:300;line-height:1;color:#a55229}
.m-sub{display:flex;flex-direction:column;padding-bottom:10px}
.m-sub a{display:block;padding:12px 0 12px 18px;font-size:13px;font-weight:500;letter-spacing:0.08em;text-transform:uppercase;color:#487a81}
.m-give{margin-top:22px;display:block;text-align:center;padding:16px;background:#a55229;color:#f1ead8;border-radius:2px;font-size:13px;font-weight:700;letter-spacing:0.16em;text-transform:uppercase}
.m-give:hover{background:#2b2b2b;color:#f1ead8}
.m-give-sub{display:flex;justify-content:center;gap:28px;margin-top:14px}
.m-give-sub a{padding:10px 0;font-size:12px;font-weight:600;letter-spacing:0.12em;text-transform:uppercase;color:#487a81}
.s-minus{display:none}
details[open]>summary .s-plus{display:none}
details[open]>summary .s-minus{display:inline}
@media (max-width:859px){.nav-d{display:none}.nav-m{display:flex}}
/* The logo is ~4:1, so at 52px tall it is 209px wide - wide enough that the
   Give button and hamburger wrapped onto a second row on a 390px phone. Below
   the desktop breakpoint the row is locked to one line and the logo scales
   with the viewport instead. */
@media (max-width:859px){
.head-in{flex-wrap:nowrap;gap:12px;padding-left:clamp(14px,4vw,32px);padding-right:clamp(14px,4vw,32px)}
.brand img{height:clamp(40px,11vw,64px)}
.nav-m{flex:none;gap:8px}
}
@media (max-width:389px){.nav-give-m{padding:10px 12px;letter-spacing:0.1em}}
"""


# ---------------------------------------------------------------------------
# home hero
# ---------------------------------------------------------------------------
# Eight photos crossfading every four seconds, with dots under them. In the
# design a setInterval drove `opacity` and a dot click called clearInterval and
# pinned one slide. Here a CSS animation does the cycling and a radio per slide
# does the pinning: checking one stops the animation (`:has`) and the
# `#hN:checked ~ #hsN` rules decide what stays visible.

HERO_SLIDES = [("hero-training.jpg", "hero-1"), ("hero-children.jpg", "hero-2"),
               ("hero-maize.jpg", "hero-4"), ("hero-baptism.jpg", "hero-5"),
               ("hero-clinic.jpg", "hero-6b"), ("hero-prayer.jpg", "hero-7"),
               ("hero-brace.jpg", "hero-8"), ("hero-visit.jpg", "hero-9")]
HERO_SECONDS = 4


def hero_block():
    n = len(HERO_SLIDES)
    total = n * HERO_SECONDS
    inputs, slides, dots, rules = [], [], [], []
    for i, (name, slot) in enumerate(HERO_SLIDES, start=1):
        inputs.append('<input class="hero-r" type="radio" name="hero" id="h%d" '
                      'aria-label="Show photo %d">' % (i, i))
        load = ('loading="eager" fetchpriority="high"' if slot in EAGER
                else 'loading="lazy"')
        slides.append(
            '<div class="hs" id="hs%d"><img src="%s" alt="%s" %s '
            'decoding="async"></div>'
            % (i, asset_url(name), html.escape(ALT[slot], quote=True), load))
        dots.append('<label for="h%d"></label>' % i)
        # -1s so the first slide is already faded in at load.
        delay = (i - 1) * HERO_SECONDS - total - 1
        rules.append(".hs:nth-of-type(%d),.hero-dots label:nth-child(%d)"
                     "{animation-delay:%ds}" % (i, i, delay))
        rules.append("#h%d:checked~#hs%d{opacity:1}" % (i, i))
        rules.append("#h%d:checked~.hero-dots label:nth-child(%d)"
                     "{background:#cca54f}" % (i, i))
        rules.append("#h%d:focus-visible~.hero-dots label:nth-child(%d)"
                     "{outline:2px solid #f1ead8;outline-offset:3px}" % (i, i))

    markup = HERO.format(inputs="\n      ".join(inputs),
                         slides="\n      ".join(slides),
                         dots="".join(dots))
    css = HERO_CSS.format(total=total) + "\n" + "\n".join(rules)
    return markup, css


HERO = """  <section class="hero">
    <div class="hero-stage">
      {inputs}
      {slides}
      <div class="hero-dots">{dots}</div>
    </div>
  </section>
"""

HERO_CSS = """
.hero{{position:relative;background:#2b2b2b;overflow:hidden}}
.hero-stage{{position:relative;width:100%;aspect-ratio:16/9;max-height:74vh;min-height:320px}}
.hero-r{{position:absolute;width:1px;height:1px;opacity:0;margin:0;pointer-events:none}}
.hs{{position:absolute;inset:0;opacity:0;animation:heroFade {total}s linear infinite}}
.hs img{{width:100%;height:100%;object-fit:cover}}
.hero-dots{{position:absolute;bottom:18px;left:0;right:0;z-index:3;display:flex;justify-content:center;gap:10px}}
.hero-dots label{{width:9px;height:9px;border-radius:50%;cursor:pointer;background:rgba(241,234,216,0.5);animation:dotFade {total}s linear infinite}}
@keyframes heroFade{{0%,100%{{opacity:0}}3%,12.5%{{opacity:1}}15.5%{{opacity:0}}}}
@keyframes dotFade{{0%,100%{{background:rgba(241,234,216,0.5)}}3%,12.5%{{background:#cca54f}}15.5%{{background:rgba(241,234,216,0.5)}}}}
.hero-stage:has(.hero-r:checked) .hs{{animation:none;opacity:0;transition:opacity 1.1s ease-in-out}}
.hero-stage:has(.hero-r:checked) .hero-dots label{{animation:none;background:rgba(241,234,216,0.5)}}
@media (prefers-reduced-motion:reduce){{.hs{{animation:none;opacity:0}}#hs1{{opacity:1}}.hero-dots label{{animation:none}}#h1:not(:checked)~.hero-dots label:nth-child(1){{background:#cca54f}}}}
"""


# ---------------------------------------------------------------------------
# page-specific CSS
# ---------------------------------------------------------------------------

# How We Serve: the design's four tabs become :target-selected panels, so the
# nav's /how-we-serve/#medical links keep working and nothing needs JS. With no
# hash the first panel shows.
def serve_css():
    """Tab CSS, written so a browser without :has() degrades to all-visible.

    The plain rules show "Heart for the Poor" and mark its tab; the :has()
    rules hide it again once another panel is the :target. Drop the :has()
    rules and every panel a visitor lands on still renders.
    """
    on = "color:#2b2b2b;font-weight:700;border-bottom-color:#a55229"
    off = "color:rgba(43,43,43,0.62);font-weight:600;border-bottom-color:transparent"
    first = SERVE_TABS[0][0]
    rules = [
        "#serve-links>div::-webkit-scrollbar{display:none}",
        ".serve-tab{flex:0 0 auto;white-space:nowrap;border-bottom:3px solid transparent;padding:16px 2px 13px;font-size:12px;font-weight:600;letter-spacing:0.14em;text-transform:uppercase;color:rgba(43,43,43,0.62)}",
        ".serve-tab:hover{color:#a55229}",
        ".serve-panel{display:none;scroll-margin-top:140px}",
        ".serve-panel:target{display:block}",
        "#%s{display:block}" % first,
        'body:has(.serve-panel:target) #%s{display:none}' % first,
        'body:has(#%s:target) #%s{display:block}' % (first, first),
        '.serve-tab[href="#%s"]{%s}' % (first, on),
        'body:has(.serve-panel:target) .serve-tab[href="#%s"]{%s}' % (first, off),
    ]
    for slug, _ in SERVE_TABS:
        rules.append('body:has(#%s:target) .serve-tab[href="#%s"]{%s}'
                     % (slug, slug, on))
    return "\n".join(rules)


# Agriculture panel: two grids whose columns/areas came from window.innerWidth.
# The narrow values are inlined by VARS; these override above 700px.
AG_CSS = """
@media (min-width:700px){.ag-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)!important;grid-template-areas:"intro media" "rest media"!important;row-gap:18px!important}.ag-sq{grid-template-columns:repeat(3,minmax(0,1fr))!important}.ag-narrow{display:none!important}}
@media (max-width:699px){.ag-wide{display:none!important}}
"""

# Give page: the two "Why choose ACH?" / "Need help?" disclosures.
ACC_CSS = """
.acc>summary{list-style:none;cursor:pointer}
.acc>summary::-webkit-details-marker{display:none}
"""


# ---------------------------------------------------------------------------
# compiler
# ---------------------------------------------------------------------------

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
    def __init__(self, assets, href_overrides=None, class_overrides=None):
        super().__init__(convert_charrefs=False)
        self.assets = assets      # export path -> published filename
        self.href_overrides = href_overrides or {}
        self.class_overrides = class_overrides or {}
        self.buf = []
        self.rules = []           # generated hover/focus CSS rules
        self.classes = {}         # (pseudo, css) -> class name
        self.skip_depth = 0       # >0 while inside a dropped subtree
        self.sc_stack = []        # one entry per open <sc-if>
        self.slot_depth = 0       # >0 while inside a replaced <image-slot>
        self.pending_class = None  # class for the next element (sc-if wrapper)
        self.in_summary = False   # inside a <button> turned <summary>
        self.open_details = False  # a <details> is waiting for its sc-if body

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
        """assets/w/foo.jpg -> /assets/published-name.jpg?v=hash."""
        key = path[len("assets/"):]
        if key not in self.assets:
            raise SystemExit("asset not in the resize plan: " + path)
        return asset_url(self.assets[key])

    def rewrite_attrs(self, tag, attrs):
        out, extra_class = [], []
        if self.pending_class:
            extra_class.append(self.pending_class)
            self.pending_class = None
        for k, v in attrs:
            if k.startswith("on"):
                continue      # design-canvas event bindings, not real handlers
            if v is None:
                out.append((k, None))
                continue
            if k == "style":
                # Grid values that came from window.innerWidth; AG_CSS takes
                # over above 700px, so tag the element for those rules.
                if "{{ agAreas }}" in v:
                    extra_class.append("ag-grid")
                if "{{ agSqCols }}" in v:
                    extra_class.append("ag-sq")
                for needle, cls in self.class_overrides.items():
                    if needle in v:
                        extra_class.append(cls)
            if self.in_summary and k == "aria-expanded":
                continue      # <details> announces its own state
            v = interp(v)
            if k in ("style-hover", "style-focus"):
                extra_class.append(self.klass(k.split("-")[1], v))
                continue
            if k == "href" and v in self.href_overrides:
                v = self.href_overrides[v]
            elif k == "href":
                base, sep, frag = v.partition("#")
                if base in LINKS:
                    v = LINKS[base] + sep + frag
                elif v.startswith("assets/"):
                    v = self.asset(v)
            elif k == "src" and v.startswith("assets/"):
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
        if sid not in ALT:
            raise SystemExit("no alt text for image slot: " + sid)
        return ('<div style="{frame}"><img src="{src}" alt="{alt}" '
                '{loading} decoding="async" style="{img}"></div>').format(
            loading=loading,
            frame=html.escape(frame, quote=True),
            src=html.escape(self.asset(src), quote=True),
            alt=html.escape(ALT[sid], quote=True),
            img=html.escape(img_style, quote=True))

    # -- sc-if ------------------------------------------------------------
    def start_sc_if(self, attrs):
        cond = re.sub(r"[{}\s]", "", dict(attrs).get("value", ""))
        if cond not in SC_IF:
            raise SystemExit("unhandled <sc-if> condition: " + cond)
        verdict = SC_IF[cond]
        if verdict is True:
            self.sc_stack.append("keep")
        elif verdict == "hidden":
            self.sc_stack.append("close-div")
            self.emit('<div id="contact-sent" hidden>')
        elif verdict == "details":
            # The <button> just before this opened the <details>; its body is
            # simply the children here.
            assert self.open_details, "sc-if %s without a summary" % cond
            self.open_details = False
            self.sc_stack.append("close-details")
        elif isinstance(verdict, tuple) and verdict[0] == "panel":
            self.sc_stack.append("close-div")
            self.emit('<div id="%s" class="serve-panel">' % verdict[1])
        elif isinstance(verdict, tuple) and verdict[0] == "class":
            self.sc_stack.append("keep")
            self.pending_class = verdict[1]
        else:
            self.sc_stack.append("drop")
            self.skip_depth += 1

    def end_sc_if(self):
        state = self.sc_stack.pop()
        if state == "drop":
            self.skip_depth -= 1
        elif state == "close-div":
            self.emit("</div>")
        elif state == "close-details":
            self.emit("</details>")

    # -- parser callbacks -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "sc-if":
            self.start_sc_if(attrs)
            return
        if tag == "sc-for":
            # The only loop in the export is the How We Serve tab strip.
            assert dict(attrs).get("list") == "{{ sectionLinks }}"
            self.emit("".join(
                '<a class="serve-tab" href="#%s">%s</a>' % (slug, label)
                for slug, label in SERVE_TABS))
            self.skip_depth += 1
            self.sc_stack.append("for")
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
        if tag == "button" and dict(attrs).get("onclick", "").strip(
                "{} ") in ACCORDION_TOGGLES:
            self.in_summary = True
            a = [(k, v) for k, v in self.rewrite_attrs(tag, attrs)
                 if k != "type"]
            self.emit('<details class="acc">' + self.render("summary", a))
            return
        a = self.rewrite_attrs(tag, attrs)
        if tag == "iframe":
            a.append(("loading", "lazy"))
        if tag == "form":
            # The design's onSubmit only flipped a local `sent` flag without
            # sending anything. Point it at Formspree and let contact.js POST it.
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
            self.end_sc_if()
            return
        if tag == "sc-for":
            self.skip_depth -= 1
            assert self.sc_stack.pop() == "for"
            return
        if tag == "image-slot":
            self.slot_depth -= 1
            return
        if self.slot_depth:
            return
        if self.skip_depth:
            self.skip_depth -= 1
            return
        if tag == "button" and self.in_summary:
            self.in_summary = False
            self.open_details = True
            self.emit("</summary>")
            return
        if tag not in VOID:
            self.emit("</%s>" % tag)

    def handle_data(self, data):
        if self.skip_depth:
            return
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


def sips(src, dst, max_width, fmt):
    fmt_name = {"jpg": "jpeg", "png": "png"}[fmt]
    subprocess.run(
        ["sips", "-s", "format", fmt_name, "-s", "formatOptions", "55",
         "-Z", str(max_width), src, "--out", dst],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_assets():
    """Re-encode every referenced asset into site/assets/, scripts included.

    Records each published file's content hash in ASSET_VERSIONS and returns
    {export path: published filename}.
    """
    dst_dir = os.path.join(OUT, "assets")
    os.makedirs(dst_dir, exist_ok=True)
    mapping = {}
    for name, (out_name, max_w) in IMAGES.items():
        src = os.path.join(SRC, "assets", name)
        if not os.path.exists(src):
            raise SystemExit("missing export asset: " + name)
        fmt = "png" if out_name.endswith(".png") else "jpg"
        sips(src, os.path.join(dst_dir, out_name), max_w, fmt)
        mapping[name] = out_name

    for script in SCRIPTS:
        shutil.copy(os.path.join(REPO, "tools", script),
                    os.path.join(dst_dir, script))

    for out_name in sorted(os.listdir(dst_dir)):
        with open(os.path.join(dst_dir, out_name), "rb") as fh:
            ASSET_VERSIONS[out_name] = hashlib.sha256(fh.read()).hexdigest()[:8]
    return mapping


# ---------------------------------------------------------------------------
# page assembly
# ---------------------------------------------------------------------------

BASE_CSS = """* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: #f1ead8; color: #2b2b2b; font-family: Montserrat, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; }
a { color: #a55229; text-decoration: none; }
a:hover { color: #2b2b2b; }
img { display: block; max-width: 100%; }
input, textarea, button { font: inherit; color: inherit; }
h1, h2, h3, h4 { margin: 0; font-weight: 400; text-wrap: pretty; }
p { text-wrap: pretty; }
section { scroll-margin-top: 84px; }"""

HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{site}{url}">
<meta name="theme-color" content="#f1ead8">
<link rel="icon" href="{icon32}" sizes="32x32">
<link rel="icon" href="{icon512}" sizes="512x512">
<link rel="apple-touch-icon" href="{touch}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="IMPACT West Africa">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{site}{url}">
<meta property="og:image" content="{site}{image}">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
{css}
</style>
{extra_head}</head>
<body>
"""

FOOT = """</body>
</html>
"""

# contact.js posts the Get Involved form; nav.js closes the mobile menu when a
# link inside it is tapped. Copied from tools/ by build_assets().
SCRIPTS = ("contact.js", "nav.js")


def script_tag(name):
    return '<script src="%s" defer></script>\n' % asset_url(name)
CHURCH_CENTER_HEAD = ('<script src="https://js.churchcenter.com/modal/v1" '
                      'defer></script>\n')

HEADER_RE = re.compile(r"[ \t]*<header\b.*?</header>\s*", re.S)
HERO_RE = re.compile(
    r'[ \t]*<section style="position:relative;background:#2b2b2b;'
    r'overflow:hidden">.*?\n  </section>\s*', re.S)


def compile_page(page, assets):
    raw = open(os.path.join(SRC, page["src"]), encoding="utf-8").read()

    body = re.search(r"<x-dc>(.*)</x-dc>", raw, re.S).group(1)
    body = body[body.index("</helmet>") + len("</helmet>"):]

    # The design wraps every page in overflow-x:hidden, which makes that div a
    # scroll container and leaves the sticky header with nothing to stick to.
    # overflow-x:clip clips the same way without creating one; the `hidden` is
    # kept first for browsers that don't know `clip`.
    wrap = '<div style="width:100%;overflow-x:hidden">'
    assert body.count(wrap) == 1, "page wrapper changed in " + page["src"]
    body = body.replace(
        wrap, '<div style="width:100%;overflow-x:hidden;overflow-x:clip">')

    # Swap the two interactive blocks for the static rebuilds above.
    body, n = HEADER_RE.subn("@@HEADER@@\n", body, count=1)
    assert n == 1, "header not found in " + page["src"]
    css = BASE_CSS + "\n" + NAV_CSS
    extra_head = ""

    if page["url"] == "/":
        body, n = HERO_RE.subn("@@HERO@@\n", body, count=1)
        assert n == 1, "home hero not found"
        hero_html, hero_css = hero_block()
        css += hero_css
    elif page["url"] == "/how-we-serve/":
        css += "\n" + serve_css() + "\n" + AG_CSS
    elif page["url"] == "/give/":
        css += ACC_CSS + TAGLINE_CSS
        extra_head = CHURCH_CENTER_HEAD

    c = Compiler(assets, HREF_OVERRIDES.get(page["url"]),
                 CLASS_OVERRIDES.get(page["url"]))
    c.feed(body)
    c.close()
    assert not c.sc_stack and not c.skip_depth, "unbalanced sc-if/sc-for"
    body_html = "".join(c.buf).strip() + "\n"

    body_html = body_html.replace("@@HEADER@@", header(page["nav"]).strip())
    if page["url"] == "/":
        body_html = body_html.replace("@@HERO@@", hero_html.strip())

    # Only keep hover/focus rules whose element survived.
    used = [r for r in c.rules if ('%s"' % r[1:r.index(":")]) in body_html]
    if used:
        css += "\n" + "\n".join(used)

    doc = HEAD.format(title=html.escape(page["title"]),
                      desc=html.escape(page["desc"]),
                      site=SITE_URL, url=page["url"],
                      image=asset_url(SOCIAL_IMAGE),
                      icon32=asset_url("favicon-32.png"),
                      icon512=asset_url("icon-512.png"),
                      touch=asset_url("apple-touch-icon.png"),
                      css=css.strip(), extra_head=extra_head)
    doc += body_html
    doc += script_tag("nav.js")
    if 'id="contact-form"' in doc:
        doc += script_tag("contact.js")
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

    assets = build_assets()

    for page in PAGES:
        doc = compile_page(page, assets)
        dest = os.path.join(OUT, page["out"])
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(doc)
        print("%-26s %6.1f KB" % (page["out"], len(doc) / 1024))

    # 404.html is hand-written rather than compiled, so its asset references
    # get the same ?v= treatment here.
    page404 = open(os.path.join(REPO, "tools", "404.html"),
                   encoding="utf-8").read()
    page404 = re.sub(r"/assets/([A-Za-z0-9._-]+)",
                     lambda m: asset_url(m.group(1)), page404)
    with open(os.path.join(OUT, "404.html"), "w", encoding="utf-8") as fh:
        fh.write(page404)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    with open(os.path.join(OUT, "CNAME"), "w") as fh:
        fh.write("impactwestafrica.org\n")

    total = sum(os.path.getsize(os.path.join(dp, f))
                for dp, _, fs in os.walk(OUT) for f in fs)
    print("site total: %.1f MB" % (total / 1024 / 1024))


if __name__ == "__main__":
    main()
