# impactwestafrica.org

Static site for IMPACT West Africa, published to GitHub Pages from `site/`.

## Layout

```
site/                      what gets published
  index.html               /
  about/index.html         /about/
  get-involved/index.html  /get-involved/
  give/index.html          /give/
  404.html
  assets/                  images + contact.js
  CNAME                    custom domain
  .nojekyll                serve the files as-is, no Jekyll build
tools/                     build + preview scripts (not published)
.github/workflows/         Pages deployment
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

## Giving

Giving runs on Planning Center. A "Give online" button appears twice, and both
copies link to

```
https://impact-west-africa-inc-544195.churchcenter.com/giving?open-in-church-center-modal=true
```

- **`/give/`** — inside the "Give online" card, above the QR code. The card is
  the second grid column on wide screens; when the columns stack it is ordered
  ahead of "Why it matters" so the button is the first thing on the page. That
  reordering is why the design's `auto-fit` grid was replaced with the explicit
  `.give-grid` / `.give-card` rules (breakpoint 900px) in that page's `<style>`.
- **`/`** — as the closing call to action, just above the footer.

`js.churchcenter.com/modal/v1` loads only on those two pages. It watches for
clicks on links carrying `?open-in-church-center-modal=true` and opens the
giving form in an overlay instead of navigating. Without JavaScript nothing
intercepts the click, so the link just goes to the Church Center giving page —
which is why these buttons need no `<noscript>` fallback.

`site/assets/give-qr.png` encodes the same giving URL without the modal
parameter (a phone camera opens the page directly). Regenerate it with any QR
encoder if the URL changes — it is a plain black-on-white code, 33 modules at
scale 8 with a 2-module quiet zone.

## Contact form

The form on `/get-involved/` posts to Formspree at
`https://formspree.io/f/mnpqloqd`. `site/assets/contact.js` submits it over
`fetch` so the page can show the "Thank you" panel in place; without JavaScript
it falls back to a normal POST and Formspree's own confirmation page. If the
request fails, the form shows an error pointing at info@impactwestafrica.org.

## Working on the site

`site/` is the source of truth — the files are plain HTML and safe to edit by
hand.

Preview locally:

```
python3 tools/serve.py        # http://localhost:8000
```

`tools/convert-design.py` is the one-time compiler that produced `site/` from
the Claude Design export. It resolves the design runtime — `{{ }}` variables,
`<sc-if>` conditionals, `<image-slot>` elements and their saved crops,
`style-hover`/`style-focus` attributes — into plain HTML and CSS, and resizes
the full-resolution originals (~36 MB) down to what the layout renders (~4 MB).
Re-run it only to re-import a fresh export; it deletes and rewrites `site/`:

```
python3 tools/convert-design.py "path/to/Website project discussion-2"
```
