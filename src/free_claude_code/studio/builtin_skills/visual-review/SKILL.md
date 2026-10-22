---
name: visual-review
description: How to look at a page you built and fix how it looks - screenshots at PC and phone size judged by the Vision Model, a checklist for what to look for, the most visible fixes first, and another look after each round.
---

# Visual review (look, fix, look again)

1. **Look at both sizes.** `look_page` (a project page) or `fcc_changer
   look` (FCC's own pages) takes PC and phone screenshots and the Vision
   Model says what looks wrong. Ask it something specific when you can
   (question: "is the price table readable on a phone?"). With no Vision
   Model you get each page's text and checks: read them closely.
2. **What to look for.** Text that overlaps, is cut off or runs off
   screen; sideways scrolling on a phone; faint text on its background;
   broken images; empty areas that should show something; crowded or
   misaligned parts; buttons smaller than a fingertip (44px); fonts,
   colours and spacing that don't match the rest; a page that looks
   unfinished (placeholder text, "Lorem ipsum", default blue links).
3. **Fix the most visible first.** Broken layout and unreadable text before
   colour and spacing. Fix the cause in the CSS (a fixed width, a missing
   `max-width: 100%`, `flex-wrap`, `min-width: 0`), not with a one-off nudge.
   Use the design system's own colours and spacing, never new one-offs.
4. **Check it still works.** After a fix, `try_page`/`fcc_changer try`
   the main flow again: a layout fix can hide a button.
5. **Look again.** Repeat 1-4 up to three rounds. Stop when it says the
   page looks fine, or say what is left and why.
6. **Say what you saw.** Report what the review found, what you fixed,
   and what the last look said.
