# $title

A portfolio for a studio or practice (it starts as an architecture firm): a big
type hero with key figures, a project grid with filters, a detail view for each
project, the practice's principles and the contact details. Each project's
picture is drawn from its own numbers (storeys, area, roof), in the page's
colours, light and dark.

- `index.html`: the page. Replace every sample line (the figures, principles,
  address and email).
- `styles.css`: the design tokens are at the top (`:root`), light and dark.
- `portfolio.js`: `PROJECTS` (name, kind, place, year, area, rating, text),
  `KIND` (the filter names, matching the buttons' `data-filter`), and
  `elevation()`, which draws each project. To show real photos instead, change
  `paint()` and `open()` to put an `<img>` where they put `elevation(...)`.
