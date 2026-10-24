# PocketPal AI (design reference)

- Upstream: https://github.com/a-ghorbani/pocketpal-ai
- Commit looked at: `213cdfe46b7690aadfd3dc5779c2d11d14fb3f2d`
- Licence: MIT (`LICENSE`, copied from that commit)

## How FCC uses it

The Studio classroom page (`src/free_claude_code/api/studio_static/classroom.js`
and `classroom.css`) copies PocketPal's look: its light and dark colours
(primary `#333333`/`#DADDE6`, secondary `#1E4DF6`/`#95ABE6`, tertiary
`#7880FF`/`#80E6E4`), Inter type, the drawer of chats, the header with a menu
and a new-chat button, the plain assistant replies with a copy footer, the
lilac user bubbles, and the dark rounded input bar.

No PocketPal code, images or fonts are copied: it is a React Native app and the
classroom is written from scratch in FCC's plain JavaScript, so nothing here
needs installing or rebuilding if the upstream repo is deleted. The licence is
kept because the page follows its design.
