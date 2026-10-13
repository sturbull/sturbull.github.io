# Git conventions

## Message format

```text
[marker] [type]: [short description]

[optional body]
```

## Markers and types

Use exactly one marker per commit. The marker and the type always agree.

| Emoji | Codepoints | Type | Use for |
| --- | --- | --- | --- |
| ✨ | U+2728 | `feat` | A new capability |
| 🐛 | U+1F41B | `fix` | A defect correction |
| ♻️ | U+267B U+FE0F | `refactor` | Restructuring with no behaviour change |
| ⚡️ | U+26A1 U+FE0F | `perf` | A performance improvement |
| ✅ | U+2705 | `test` | A test-only change |
| 📝 | U+1F4DD | `docs` | A documentation-only change |
| 🎨 | U+1F3A8 | `style` | Formatting only, no behaviour change |
| 📦 | U+1F4E6 | `build` | Dependencies, packaging, environment setup |
| 👷 | U+1F477 | `ci` | CI/CD configuration |
| 🧹 | U+1F9F9 | `chore` | Maintenance not covered above |
| ⏪️ | U+23EA U+FE0F | `revert` | Reverting an earlier commit |

Copy the marker exactly, including any variation selector, and follow it with an ordinary space.

Pick the type from the result, not the effort. A large rewrite that leaves behaviour unchanged is `refactor`. An intentional visual change is `feat`; a corrected visual defect is `fix`.

## Classifying changes in this repository

- A new blog post, or new content in an existing post, is `feat`.
- A correction to a post's text, code or figures is `fix`.
- Theme, SCSS, CSS and layout template changes follow the visual rule above.
- `renv.lock` updates and Quarto configuration are `build`.
- Commit `_freeze/` output with the source change that produced it, under that change's type. The rendered site is not committed to `main`; `quarto publish gh-pages` pushes it to the `gh-pages` branch.

## Subject

- Lowercase past tense. Describe the result, not the activity.
- Do not restate the type. No trailing period.
- Aim for 20 to 30 characters; do not exceed 50.

Examples:

```text
✨ feat: added census ethnicity post
🐛 fix: corrected axis labels
🎨 style: reformatted theme files
📦 build: updated renv lockfile
```

## Body

Most commits need no body. Add one only for durable information the diff does not show, such as a tradeoff, non-obvious behaviour, or a constraint future work must preserve. Leave out investigation history, reproduction steps and measurements.

For a necessary cross-area change, keep one primary subject line and list the secondary changes as short body bullets.

Never put data values, row-level details or personal information in a commit message.
