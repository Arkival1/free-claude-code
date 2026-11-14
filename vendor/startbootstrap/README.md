# Start Bootstrap layouts

- Upstream: https://github.com/StartBootstrap (one repo per layout,
  `startbootstrap-<name>`; each repo's built `dist/` folder is used)
- Licence: MIT (`LICENSE`, copyright Start Bootstrap LLC; every layout repo
  has the same text)
- Owner approved on 23 October 2026 after a preview of all 26.

## What FCC uses

`src/free_claude_code/studio/site_layouts/layouts.zip` holds the 26 built
layouts (`<layout>/...`), a `catalogue.json` (name, kind, pages, files), and
the libraries they load, kept so a site works offline:

| In the zip | Upstream | Licence |
| --- | --- | --- |
| `vendor/bootstrap/` | Bootstrap 5.2.3 `bootstrap.bundle.min.js` | MIT |
| `vendor/bootstrap-icons/` | Bootstrap Icons 1.8.1 (CSS and fonts) | MIT |
| `vendor/fontawesome/` | Font Awesome Free 6.3.0 `all.js` | icons CC BY 4.0, code MIT (licence file included) |
| `vendor/chartjs/` | Chart.js 2.8.0 (SB Admin only) | MIT |
| `vendor/simple-datatables/` | simple-datatables 7.1.2 (SB Admin only) | LGPL-3.0 (licence file included; unmodified; source at github.com/fiduswriter/simple-datatables) |

`pack.py` rebuilt it from the checkouts: big photos shrunk to at most
1600 px, Coming Soon's background video re-encoded at 720p without sound,
CDN links pointed at the vendor copies, and Start Bootstrap's own form
service (`sb-forms-latest.js` and its token) taken out. `SHA256SUMS` holds
the zip's checksum (a test checks it).

Left out: each repo's source (Pug/SCSS) and build scripts; the built pages
are what FCC copies. The sample photos and grey dummyimage.com boxes stay as
the layouts' placeholders; check_project flags them (and the lorem ipsum)
until the Builder replaces them.

The Builder, Coder, Designer and Developer use them through the
`site_layouts` tool (`studio/site_layouts/__init__.py`).

## Commits

| Repo | Commit |
| --- | --- |
| startbootstrap-agency | b2d5d5c |
| startbootstrap-bare | 9e17b37 |
| startbootstrap-blog-home | 4227045 |
| startbootstrap-blog-post | 85c4c8d |
| startbootstrap-business-casual | b6f9289 |
| startbootstrap-business-frontpage | b330ff6 |
| startbootstrap-clean-blog | 1ebc4f8 |
| startbootstrap-coming-soon | 5c42810 |
| startbootstrap-creative | b1762d8 |
| startbootstrap-freelancer | 5bc65b4 |
| startbootstrap-full-width-pics | 899a83c |
| startbootstrap-grayscale | d974402 |
| startbootstrap-heroic-features | a9b7e38 |
| startbootstrap-landing-page | 247a46a |
| startbootstrap-modern-business | 7d29710 |
| startbootstrap-new-age | 5f61977 |
| startbootstrap-one-page-wonder | 4a2712c |
| startbootstrap-personal | 6a1ebcc |
| startbootstrap-resume | c6fbe5e |
| startbootstrap-sb-admin | adde34b |
| startbootstrap-scrolling-nav | 45ee8f6 |
| startbootstrap-shop-homepage | fb3a490 |
| startbootstrap-shop-item | 7eee616 |
| startbootstrap-simple-sidebar | 72f0de1 |
| startbootstrap-small-business | 9c5ef57 |
| startbootstrap-stylish-portfolio | a658eb7 |
