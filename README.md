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

## No JavaScript

The only script the site ships is `assets/contact.js` (and Planning Center's
modal on `/give/`). Everything else that moves is CSS:

- **Header.** Desktop dropdowns open on `:hover` / `:focus-within`; the mobile
  hamburger and its three section accordions are `<details>` elements. The
  desktop and mobile headers swap at 860px, the same breakpoint the design used.
- **Home hero.** Eight photos crossfade on a 32-second CSS animation (4s each).
  A hidden radio per slide sits in front of them: checking one stops the
  animation and pins that photo, which is what the design's dots did. The dots
  are `<label>`s for those radios.
- **How We Serve tabs.** The four sections are `.serve-panel` divs selected by
  `:target`, so `/how-we-serve/#medical` works as a deep link from anywhere.
  With no hash, "Heart for the Poor" shows. The rules are ordered so a browser
  without `:has()` falls back to showing panels rather than hiding all of them.
- **Give accordions.** "Why choose ACH?" and "Need help?" are `<details>`.

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
