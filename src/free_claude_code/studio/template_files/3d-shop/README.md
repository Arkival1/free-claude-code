# $title

A shop or bakery site with a live 3D product scene (three.js, FCC's own copy in
`vendor/three`), product cards whose photos are rendered from the 3D models and
tilt towards the pointer, a step-by-step process, opening hours and an order form.

- `index.html`: the page. Replace every sample line (name, address, prices, steps).
- `styles.css`: the design tokens are at the top (`:root`), light and dark.
- `shop.js`: `PRODUCTS` (the menu), `HOURS`, the form, and the 3D: `makers` builds
  each product from shapes (boule, croissant, scroll, baguette). Add a maker for a
  new product, then add it to `PRODUCTS` with the same `id`.

Open `index.html` through Studio's preview (a module page needs a web server).
