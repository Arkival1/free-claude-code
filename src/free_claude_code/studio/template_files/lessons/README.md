# $title

A lessons or classes site (it starts as a surf school): a hero with live waves
drawn on a canvas that swell towards the pointer, lesson cards with prices, a
conditions table, the coaches, a safety section, and a booking form that works
out the price and goes to a form service or the school's email.

- `index.html`: the page. Replace every sample line (lessons, prices, coaches,
  the conditions table, the meeting point, the email).
- `styles.css`: the design tokens are at the top (`:root`).
- `lessons.js`: `PRICES` (must match the lesson names in the page and the
  form's options), the waves (`layers`), and the booking form. To receive
  bookings, put a form service address in the form's `data-endpoint`; without
  one, the visitor's email app opens with the booking, to the form's `data-email`.

The waves pause off-screen and hold still with reduced motion.
