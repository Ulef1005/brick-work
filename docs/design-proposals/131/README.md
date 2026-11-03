# #131 Max price with box: proposed design frames

Proposed frames for a wish's **Max price with box** (#131, schema 4.1). They complete frames 7b and 12k, which show only **Your max price**. They are a proposal for review, not part of `design/`: that folder is exported from the design project and is not edited here (CLAUDE.md). Once approved, the frames are redrawn or imported in the design project and come back with its next export into `design/`.

Review page (private claude.ai artifact): https://claude.ai/artifact/FzSBTeyaYqVwWmeuBTDn47

## What is here

- `frames/<id>-<view>-<width>-<theme>.png`: each frame at 390 (phone), 1024 (iPad landscape) and 1440 (desktop), light and dark, named as in `design/frames/`.
- `html/<id>-<view>-<width>.html`: the frame as inline-styled markup with `var(--tw-*)` tokens from `design/tokens-v2.css`. It is the 12k markup with the changes below, so its values can be read as with `design/sections/`.

| Id | State |
|---|---|
| 131a | A set wish, editable. The price card footer has the price with box, then **Your max price** and **Max with box**, each a button that opens Edit on its field. An empty max with box reads "not set". The Wish card shows the max with box beside your max price. |
| 131b | The Edit sheet of a set wish. **Max price with box** and its currency sit under **Your max price**, with one line on what an empty value means. |
| 131c | Without edit rights. The footer labels are plain secondary text, not buttons, and the Wish card has no Edit button. The max with box here is €200.00. |
| 131d | A minifigure wish. A figure has no quote with box, so there is no footer row, no Max with box in the Wish card and no field for it in Edit. |

Sample data only: 6085-1 Black Monarch's Castle and cas086 Black Knight (the kit's own examples), with invented prices. Images are the kit's placeholders.

## Where the drawing and the shipped app differ

These are listed for review. Neither the drawing nor the app was changed to match the other.

1. **Footer layout.** The app stacks Your max price and Max with box at the right, each a text button over its value, beside "With box: €… · age". The drawing gives each its own row, with the label as a button with a pencil and the value at the right.
2. **Estimate.** The app keeps the set's estimate in a wish's footer. The drawing leaves it out of a wish.
3. **Wish card.** The drawing shows Max with box beside Your max price in the Wish card. The app shows it only in the price card footer and the Edit sheet.
4. **Empty value.** The app's footer says "not set", and its Info card says "Not recorded" for an empty max. The drawing uses "not set" in the footer and "Not set" in the Wish card. One wording should be chosen.
5. **Edit sheet.** The app labels the second field "Max with box currency" and has no helper text for the max with box. The drawing labels both currency fields "Currency", as 12k does, and adds one helper line.

## Where they agree

- Only a set wish has a max with box (`collection._check_wish_edits`; the footer renders for sets only).
- Without edit rights, the labels are plain text in `--tw-text-2` (`.bc-estimate-label`).
- A price with box is compared with the max with box, or with your max price when it is empty (`planning.max_limit`). The screen gives no verdict for it; the API does (`under_max_boxed`). **Open question:** should *Against your max* also show a verdict with box?
