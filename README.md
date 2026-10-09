# impactwestafrica.org

Static site for IMPACT West Africa, published to GitHub Pages from `site/`.

## Layout

```
site/                        what gets published
  index.html                 /
  about/index.html           /about/
  how-we-serve/index.html    /how-we-serve/
  get-involved/index.html    /get-involved/
  give/index.html            /give/
  404.html
  assets/                    images + contact.js
  CNAME                      custom domain
  .nojekyll                  serve the files as-is, no Jekyll build
tools/                       build + preview scripts (not published)
.github/workflows/           Pages deployment
```

Every route is a directory index, so URLs carry no `.html` suffix. Links and
canonicals use the trailing slash (`/give/`) because that is what the server
actually serves; `/give` still works, as a 301 to `/give/`. All internal links
and asset paths are root-absolute, so the nesting depth doesn't matter.

## Deploying

Set **Settings → Pages → Source** to **GitHub Actions** (branch-based Pages can
only publish from the repo root or `/docs`, not from `site/`). After that every
push to `main` runs `.github/workflows/pages.yml`, which uploads `site/` and
deploys it.

## Almost no JavaScript

The site ships two small scripts — `assets/nav.js` and `assets/contact.js` —
plus Planning Center's modal on `/give/`. Everything else that moves is CSS:

- **Header.** Desktop dropdowns open on `:hover` / `:focus-within`; the mobile
  hamburger and its three section accordions are `<details>` elements. The
  desktop and mobile headers swap at 860px, the same breakpoint the design
  used. Below that breakpoint the header row is `flex-wrap: nowrap` and the
  logo scales with the viewport: the logo is about 4:1, so at its desktop
  height it is wide enough to push the Give button and hamburger onto a second
  row on a 390px phone.
  `assets/nav.js` is the one thing `<details>` cannot do — closing the menu
  when a link inside it is tapped. A link to a `#fragment` on the page already
  loaded does not navigate, so without it the panel stays open on top of the
  section the visitor just asked for. Without the script the menu still opens
  and closes from its own button.
- **Home hero.** Eight photos crossfade on a 32-second CSS animation (4s each).
  A hidden radio per slide sits in front of them: checking one stops the
  animation and pins that photo, which is what the design's dots did. The dots
  are `<label>`s for those radios.
- **How We Serve tabs.** The four sections are `.serve-panel` divs selected by
  `:target`, so `/how-we-serve/#medical` works as a deep link from anywhere.
  With no hash, "Heart for the Poor" shows. The rules are ordered so a browser
  without `:has()` falls back to showing panels rather than hiding all of them.
- **Give accordions.** "Why choose ACH?" and "Need help?" are `<details>`.

## Cache busting

GitHub Pages serves everything with `Cache-Control: max-age=600` and offers no
way to change that, so after a deploy a browser can keep showing a stale image
or script for ten minutes — longer for a tab that is already open. Every asset
URL therefore carries a version query built from a hash of that file's bytes:

```
/assets/logo.png?v=bfc36042
```

The hash is per file, not per build. Re-running the compiler with nothing
changed produces byte-identical output and identical URLs; editing one photo
or script moves only that one URL and leaves the other ~60 alone. A single
build-wide stamp — the commit hash, say — would be simpler, but it would expire
all 7 MB of photographs on every deploy including the ones that did not change,
so returning visitors would re-download the lot after a one-word copy edit.

`asset_url()` in the compiler is the only place that builds an `/assets/` URL,
and it raises on an unknown filename, so a reference can't quietly ship without
a version. `404.html` is hand-written rather than compiled, so its references
get the same treatment by substitution on the way out.

## Giving

Giving runs on Planning Center. The "Give Now" button in the Online Giving card
on `/give/` links to

```
https://impact-west-africa-inc-544195.churchcenter.com/giving?open-in-church-center-modal=true
```

`js.churchcenter.com/modal/v1` loads only on that page. It watches for clicks on
links carrying `?open-in-church-center-modal=true` and opens the giving form in
an overlay instead of navigating. Without JavaScript nothing intercepts the
click, so the link just goes to the Church Center giving page — which is why the
button needs no `<noscript>` fallback.

## Contact form

The form on `/get-involved/` posts to Formspree at
`https://formspree.io/f/mnpqloqd`. `site/assets/contact.js` submits it over
`fetch` so the page can show the "Thank you" panel in place; without JavaScript
it falls back to a normal POST and Formspree's own confirmation page. If the
request fails, the form shows an error pointing at info@impactwestafrica.org.

The newsletter signup on the same page is an `<iframe>` of the Epistle subscribe
form at `impact-west-africa.epistle.org/subscribe`.

## Working on the site

`site/` is the source of truth — the files are plain HTML and safe to edit by
hand.

Preview locally:

```
python3 tools/serve.py        # http://localhost:8000
```

`tools/convert-design.py` is the compiler that produces `site/` from the Claude
Design export. It resolves the design runtime — `{{ }}` variables, `<sc-if>` /
`<sc-for>`, `<image-slot>` elements and their saved crops, `style-hover` /
`style-focus` attributes — into plain HTML and CSS, rebuilds the header, hero
and tabs described above, and re-encodes the export's photos (~12.5 MB) down to
what the layout renders (~7 MB). Re-run it only to re-import a fresh export; it
deletes and rewrites `site/`:

```
python3 tools/convert-design.py "path/to/Website project discussion-5"
```

Two things in that script need attention when a new export lands: `IMAGES` (the
export path → published name and max width for every photo) and `ALT` (alt text
per `<image-slot>` id). The build fails loudly on an image it has no plan or no
alt text for, rather than shipping a nameless or unlabelled file. The footer
copyright year is also stamped in at build time.
