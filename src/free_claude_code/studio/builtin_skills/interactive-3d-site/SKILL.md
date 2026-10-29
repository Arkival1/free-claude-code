---
name: interactive-3d-site
description: How to build a website with an interactive 3D look that moves - a 3D scene people turn by hand, products built from shapes, card photos rendered from the same 3D models that tilt and float, kept light, accessible and working without WebGL. Start from the 3d-shop template for a shop, bakery, cafe or product site.
---

# Interactive 3D website

1. **Start from the right template.** A shop, bakery, cafe or product page:
   `start_project` with `3d-shop`. A launch or portfolio hero: `3d-landing`.
   Both bring three.js in `vendor/three` (never edit it) through the import
   map, so the site works offline. Replace every sample line: name, address,
   phone (the `tel:` link too), email, prices, steps, hours.
2. **One 3D moment, the rest calm.** The hero holds the scene; everything
   else is a clean page. Products sit on something real (a board, a shelf, a
   table) on a soft floor shadow. Warm key light, cool rim light, ACES tone
   mapping.
3. **Build products from shapes.** `shop.js` has a `makers` table: each
   function returns a mesh or group. Use spheres squashed and pushed around
   with a little noise for loaves and fruit, a swept tube with a changing
   radius for croissants and pastries, lathes for bottles, cups and
   baguettes, boxes with rounded edges for packaging. Paint them with vertex
   colours (darker on top, paler where cut or folded). Add a product: a maker
   with a new `id`, then a row in `PRODUCTS` with the same `id`.
4. **Photos come from the models.** With no real photos, render each model
   alone and use the picture on its card (`photos()` in `shop.js`). With the
   owner's real photos (`list_photos`/`use_photo`), put those on the cards and
   keep the 3D for the hero.
5. **Make it move with the person, not on its own.** Drag turns the scene and
   it keeps a little spin; a tap lifts a product and shows its name and
   price. Cards tilt towards the pointer or finger and the photo floats a
   little on scroll. No autoplaying spin faster than a slow turn.
6. **Keep it light.** One renderer for the page, pixel ratio at most 2, stop
   drawing when the scene is off screen or the tab is hidden, no more than a
   few hundred particles. Render card photos once, not every frame.
7. **Everyone can use it.** `prefers-reduced-motion` turns off the spin,
   tilt and floating. Without WebGL a drawn fallback shows and the page still
   works. The stage has an `aria-label` saying what it shows and how to use
   it; every product is also in the HTML (cards), not only in 3D.
8. **Colours.** three.js manages colour: give it plain sRGB hex colours (no
   manual conversion). Both themes (light and dark tokens in `styles.css`).
9. **Before finishing.** `check_project`, `polish_check`, then `try_page`
   (tap the scene, send the order form) and `look_page` on PC and phone; fix
   what they show. The order form sends to `data-endpoint` (a form service)
   or opens the email app to `data-email`: set the real address.
