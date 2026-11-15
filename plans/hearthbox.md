# Hearthbox: a village sim for the phone

The owner asked for "Smallville had a baby with WorldBox" on mobile: villagers who
live their own lives and talk, a god who can build and break things, and every
conversation and stat visible.

Where: `docs/hearthbox/` (plain JavaScript modules, no build step, GitHub Pages
serves it next to FCC Phone). Offline; nothing is downloaded.

## Smallville side (the villagers)
- Each villager: name, family name, age, two traits, job, skills, needs
  (hunger, energy, social, fun), health, happiness.
- A memory stream (what they saw, heard and said) and a nightly reflection
  ("I feel closest to Ben", "I'm worried about food").
- A daily plan made at dawn from job, traits, goals and known events, shown
  hour by hour; needs and danger can break it.
- Conversations when they meet: greeting, news, gossip, work, village worries,
  invitations, romance, arguments, goodbye. Lines come from what they really
  know and feel (numbers from the game).
- Information spreads only by seeing or being told (facts), so a party
  invitation travels person to person; the News panel shows who knows.
- Whisper: plant a thought (any text), throw a party, a crush, a grudge,
  or build something.
- Relationships: friends, rivals, partners, families, babies, ageing, death.
- Optional "AI voices": an OpenAI-compatible endpoint (LM Studio or a cloud
  key) phrases the talk; game effects stay rule-based; off by default.

## WorldBox side (the god)
- Island world with lakes, forests, hills, mountains; pinch-zoom and pan.
- Build: 12 building types placed as blueprints that villagers fund and build
  (or instant build); roads. Villages grow on their own too (houses, farms,
  tavern, school ...).
- Powers: villager, sheep, wolf, fire, lightning, meteor, rain, bless, plague,
  madness, smite, erase; land brushes (grass, forest, water, sand, mountain,
  road).
- A villager dropped far away founds a new village with its own store.

## Screens
Top bar (day, clock, weather, food, wood, stone, gold, people, speed).
Bottom tabs: Build, Powers, Land, People, Talk, Stats, Menu. Tap a villager
for the inspector (bars, plan, thoughts, friends, memories, their talk).

## Acceptance
- Plays in iPhone Safari portrait; touch pan, pinch zoom, tap to inspect.
- A headless run of 10 days keeps a living village with conversations,
  facts spreading, buildings finished and no errors (node test).
- A browser test loads the page, opens each tab, places a building, uses a
  power, inspects a villager and sees talk lines, with no console errors.
- Saves to the browser and loads back.

## Later (offered, not built)
Wars between villages, mayor elections, seasons, sound.
