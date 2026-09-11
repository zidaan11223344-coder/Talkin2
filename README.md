# V31 — Exact Unicode Gift Names

Gift cards now copy the exact sender and receiver usernames received from Talkin into the two rectangles.

- No transliteration or normalization of usernames.
- Added broad bundled Unicode fonts for Arabic presentation forms, symbols, Egyptian hieroglyphs, music symbols and mathematical decorative letters.
- Font coverage is checked from the actual font cmap so missing glyphs do not become false `.notdef` boxes.
- Combining marks are kept attached to their preceding character where possible.
- If a character is not present in any bundled font, its original Unicode value is still preserved; a font capable of that character would be required to display it visually.
