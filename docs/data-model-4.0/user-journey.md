# Brick Work 4.0: user journey on the revised model (revision 2)

Written 2026-10-23, as a walk through `data-model-design.md` and `schema-4.0.sql` in this folder. Same scenario as the initial journey: a fresh install, onboarding, an owned copy of 6081-1, three loose parts, two loose figures. Nothing personal: every number is a catalogue number.

**Every row below was written, not just described.** `test_journey.py` replays this journey against the DDL: a fresh collection file with the real 22 Oct catalogue attached read-only. It ends with a clean `foreign_key_check` and `integrity_check` *(measured; log in the scratchpad `revise-4.0/journey.log`)*.

**The ids are real.** They are the running numbers a first build of the 22 Oct dump gives (colours 1 and 2 fixed, then colours by Rebrickable id; items as sets, then parts, then figures, each sorted by key; `revise-4.0/build_dump.py`) *(measured)*. Another install, or a build from another dump, numbers differently (design § 3.1). That is why nothing below relies on a particular number.

| Thing | Brick Work id | Born key |
|---|---|---|
| 6081-1 King's Mountain Fortress | 15011 | `rebrickable sets 6081-1` |
| Plate 1 x 2 | 44289 | `rebrickable parts 3023` |
| Brick Arch 1 x 5 x 4 | 37722 | `rebrickable parts 2339` |
| Hips and Black Legs | 75973 | `rebrickable parts 970c03` |
| Knight (Crusader Lion) - Black Legs | 97969 | `rebrickable minifigs fig-004576` |
| Pizzaria Waiter, White Torso, Warm Pink Legs | 110744 | `rebrickable minifigs fig-018222` |
| Colours | 1 no colour, 2 unknown, 3 Black, 7 Red, 10 Light Gray, 11 Dark Gray, 17 Yellow, 18 White, 109 Dark Brown, 274 Warm Pink | Rebrickable 9999, −1, 0, 4, 7, 8, 14, 15, 308, 1146 |

BrickLink colour ids used below (White 1, Black 11, Red 5, Yellow 3, Dark Gray 10, Light Gray 9, Dark Brown 120) are what the shipped `colors.csv` will carry. I wrote them from memory: **confirm them against the mapping build**.

Budgets as in the code today: BrickLink 4,400 calls a day (`sources/bricklink.py:49`), Rebrickable 1,000 at 1 s spacing, Brickset 100 `getSets`, Brickognize 100. Image hosts `img.bricklink.com` and `cdn.rebrickable.com` need no key and have no budget.

---

## 0. Fresh container

`docker compose up` with an empty `data/`. `brickwork setup` creates **only the collection file**:

| Table | Rows |
|---|---|
| `meta` | `schema_version=4.0`, `install_id`, `created_at`; no `catalogue_id` yet |
| `source` | 11 providers, including `import` (the pipeline's job source) |
| `color` | **1** "[No Color/Any Color]" (born `rebrickable 9999`) and **2** "[Unknown]" (born `rebrickable -1`). These are fixed ids, so the collection can store "no colour" before any catalogue exists (CHECK in both files) |
| `wishlist` | `default` |
| `flag` | the three system flags (`system=1`, cannot be archived) |
| `setting` | `source_priority` defaults (picture order: parts `rebrickable_dump, bricklink, rebrickable_api`, others `bricklink, rebrickable_dump`); `import_order:<kind>`; `prefer_bricklink_inventory=false` |
| `event` | #1 `database/setup`, `via=cli` |

The user sees **Get started** (#83). Every Add path answers `catalogue_not_loaded`. This is the same offline and without keys.

---

## 1. Onboarding

### 1.1 Step 1: the catalogue (no account, no key)

**The user sees** *Download today's catalogue*, with the line "Rebrickable asks for at most one download a day" (Q14: tell, don't block). If files from today are already in `data/catalogue-src/rebrickable/`, the step offers *Build from today's files* first. Offline, the step offers *Use files I downloaded* and the link to `rebrickable.com/downloads/`. The user presses the button and sees one progress bar (download, build, mappings, index, activate), then "Catalogue of 22 Oct: 28,547 sets, 64,906 parts, 17,293 minifigures, 275 colours".

**Job:** `job(source=rebrickable_dump, kind=catalogue_import)` with steps `download → build → mappings → index → activate`. The download is 12 plain HTTPS GETs (17 MB). It uses no budget, and no `source_budget` row exists for it (Q14).

**The catalogue file, built as `catalogue.db.new` and renamed into place.** The build is seeded from the collection, which holds only colours 1 and 2, so everything else is numbered fresh.

| Table | Example rows | From |
|---|---|---|
| `meta` | `schema_version=catalogue-4.0`, `catalogue_id=<uuid>`, `item_high_water=110746`, `color_high_water=275` | minted |
| `build` | `id=1, kind=rebrickable_dump, seeded_from=collection, files_json=[{name:"sets.csv.gz", bytes:522275, sha256:…, rows:28547}, …]` | the files |
| `theme` | `199 Lion Knights, parent 186 Castle`; theme 501-style rows with `item_kind` from `theme_kinds.csv` | `themes.csv`, Rebrickable ids kept |
| `color` | `3 Black 05131D` (born `0`), `7 Red C91A09` (born `4`), `18 White FFFFFF` (born `15`) | `colors.csv` |
| `item` | `15011 set King's Mountain Fortress, 1990, num_parts 438, theme 199, kind_source=namespace, born rebrickable sets 6081-1, digest` | `sets.csv` |
| `item` | `44289 part Plate 1 x 2`, `37722 part Brick Arch 1 x 5 x 4`, `75973 part Hips and Black Legs` | `parts.csv` |
| `item` | `97969 minifigure Knight (Crusader Lion) - Black Legs`, `110744 minifigure Pizzaria Waiter, White Torso, Warm Pink Legs` | `minifigs.csv` |
| `item` | the 8,387 zero-part "sets", with kind from their theme (`gear`, `book`, …) and `kind_source=theme` (Q10) | `sets.csv` + `theme_kinds.csv` |
| `inventory` | for 6081-1: `item 15011, version 1, ordinal 1, is_latest 1, rb_inventory_id 2536, part_lines 123, figure_lines 6, digest 9db79baf…` (the row id, 1828 here, is internal) | `inventories.csv` |
| `inventory_part` | 123 lines for 6081-1, 3 of them spare, e.g. `(2339 [37722], Black [3], spare 0, qty 2)`, `(3023 [44289], Black, 4)`, `(3023, Light Gray, 1)`, `(3023, White, 1)`. Primary key `(inventory, item, colour, spare)`, `WITHOUT ROWID`, no line id | `inventory_parts.csv` |
| `inventory_figure` | 6081-1: `fig-004576 ×2`, `fig-006557`, `fig-006558`, `fig-006589`, `fig-006723 ×2`, `fig-006751` | `inventory_minifigs.csv` |
| `inventory_part` (figures) | fig-004576: `3626apr0001 Yellow`, `3844 Dark Gray`, `970c03 Red`, `973c28h01pr0138 Red`, one each | the figure's inventory |
| `element`, `picture_url` | `302301`, `6548261`, `6552100` for 3023 White; `(37722, Black) → …/parts/elements/4159140.jpg` | `elements.csv`, `inventory_parts.csv img_url` |

**The `mappings` step** (`build` 2, `kind=mapping`):

| Layer | Rows for this journey |
|---|---|
| shipped `colors.csv` | `color_link (White, bricklink "1", provider_name "White", matched)`, `(Red, "5")`, `(Black, "11")`, …; `inverse_preferred` on Pastel Blue for BrickLink 72 and Pearl Titanium for 77 |
| shipped `parts.csv` | `item_link (44289 [3023], P "3023", matched, external_ids, origin shipped)`; **no row for 2339** (no BrickLink id, spike) |
| rule: set number | `(15011 [6081-1], S "6081-1", inferred, set_number)` |
| rule: leg rule | `(75973 [970c03], colour 3 Black, P "970c00", matched, leg_rule, preferred)` and `(75973, colour NULL, P "970c11", matched, leg_rule, preferred)`. Black hips on black legs are BrickLink's one-colour `970c00`; any other hip colour on black legs is `970c11` (spike `figs.json`) |
| local `data/mappings/minifigs.csv` | **only on an install that has it** (Ulf's, from the BrickStore test, design § 3.4): `(97969 [fig-004576], M "<BrickLink id>", matched, composition_leg_rule, origin local)`. Nothing for fig-018222, which is newer than the BrickStore file |

**Collection file, `activate` step:**

- `catalogue_build` rows 1 and 2;
- `meta.catalogue_id` bound, and the high-water marks copied;
- the other 273 colours projected with their `color_link` rows;
- `event catalogue/activated`.

**Cost:** 11.6 s for the tables plus 0.3 s FTS on a Mac for this dump, giving a 129.7 MB file *(measured)*. Links and the Pi timing are still to be measured.

From here, steps 2 to 4 below work without a key and without the network.

### 1.2 Step 2: keys (optional)

| Action | Collection file | Call |
|---|---|---|
| Save the BrickLink key | `source_key(bricklink, <Fernet ciphertext>)`; `event source_key/save` (never the value) | none |
| Test BrickLink | `job(source=bricklink, kind=key_test, budget_used=1)`, `source_budget(bricklink, 2026-10-23, used=1)`, `source_record(bricklink, colors, …, payload=<raw reply>)` | `GET /colors/1`, 1 of 4,400 |
| Test Rebrickable, Brickset | the same shape | 1 of 1,000; Brickset `checkKey`, not charged |

Without `BW_SECRET_KEY`, key entry is disabled as today; keys from the environment still work.

### 1.3 Tools & Admin: the BrickLink item lists (optional)

The user drops the eight XML files into `data/catalogue-src/bricklink/` and presses *Load*. A seeded build writes a new catalogue file with:

- `bricklink_item` (all eight types);
- `6081-1`'s link upgraded `inferred/set_number` → `matched/bricklink_list`;
- `2339` gets `(37722, P "2339", to_check, same_number)` if `P 2339` exists in the list (decision 8: never `matched`);
- theme-guessed kinds corrected where BrickLink's type disagrees (Q10).

Then reconcile writes BrickLink names as `item_property(source=bricklink)` and mirrors the upgrades for projected items. Nothing is called and nothing is budgeted. It works offline.

### 1.4 Step 3: bring a collection in

Not walked. Rebrickable or Brickset sync, a BrickTracker import and BrickLink XML all land through the same projection and materialisation. A synced item whose kind is not `set` becomes `stock` of that kind (design § 3.5).

---

## 2. The first set: an owned copy of 6081-1

**The user** opens Manage → Add, types `6081`, and sees *6081-1 King's Mountain Fortress · 1990 · Lion Knights · 438 parts* from `catalogue.item_fts`. They pick it, choose *Owned*, condition *used*, and see the review table.

**The Part list picker (Q23).** 6081-1 has one Rebrickable version. Without a BrickLink key there is no choice, so no picker is shown. With a key, the picker shows *Rebrickable* and *BrickLink's list*, preselected from `set_preference` (none), then from `prefer_bricklink_inventory` (`false`), so *Rebrickable* (§ 2.1 shows the other case). Every part row has a picture source, so the review shows no picture warning.

The user presses *Confirm*.

**Collection file, one transaction (the Add receipt):**

| Table | Rows | From |
|---|---|---|
| `item` (projection) | 134 rows: the set `15011`, its 6 figures (`97969`, …) and the 127 distinct parts of the set and its figures, each with `origin=catalogue`, born key, `theme_name`, `category_name`, `num_parts`, `size_key`, `catalogue_build_id=1` and digest | `catalogue.item` (+ theme, category names) |
| `item_link` (projection) | the catalogue links of those items: `6081-1 → S 6081-1 inferred`, `3023 → P 3023 matched`, `970c03 → P 970c00 (Black only)` and `P 970c11 (other colours)`, and `fig-004576 → M …` where the local mapping exists | `catalogue.item_link` |
| `copy` | `id=<uuid>, item_id=15011, inventory_source=rebrickable, inventory_version=1, inventory_digest=9db79baf…, materialised_at, condition=used, completeness_source=derived, created_at` | user + `catalogue.inventory (15011, 1)` |
| `copy_figure` | 6 rows, e.g. `(copy, 97969, inventory_source=rebrickable, inventory_version=1, inventory_digest=<fig-004576's digest>, quantity=2)` | `catalogue.inventory_figure` + each figure's latest inventory (Q15) |
| `copy_part` | **154 rows**: 123 set lines (3 spare), e.g. `(copy, figure NULL, 37722 [2339], 3 [Black], spare 0, qty 2)`; 31 figure component lines, e.g. `(copy, <fig-004576 line>, 75973 [970c03], 7 [Red], qty 2 = 1 × figure quantity 2)`. No reference to a catalogue line: the line key is the provenance | `catalogue.inventory_part` of the set and of each figure |
| `event` | `add/receipt`, `copy/created`, `copy/inventory_materialised` | the write |
| `job` | `(source=import, kind=item, item_id=15011, state=queued, via=app)`, `job_step` × 6 in `import_order:set` | setting |

The copy can be checked the moment the transaction commits. Check Set Parts reads `copy_part`, `copy_figure` and the projected `item` (category and size for largest-first), without the catalogue.

**Jobs, in order:**

| Step | What it does | Writes | Call | No key / offline |
|---|---|---|---|---|
| `identity`, `inventory`, `matching` | already satisfied locally | `job_step` done | none | same |
| `pictures` | set photo by the picture order `bricklink, rebrickable_dump`: `img.bricklink.com/ItemImage/SN/0/6081-1.png` (the set link resolves), fallback `cdn.rebrickable.com/media/sets/6081-1.jpg`; parts by `rebrickable_dump, bricklink, rebrickable_api`: e.g. `(37722, Black) → …/elements/4159140.jpg` | `picture(item, colour, source, kind, local_path, url)` | plain downloads | offline: `source_error`, retried later |
| `metadata` | Brickset retail and availability | `item_property(source=brickset)`, `price_observation(guide=retail)` | Brickset `getSets`, 1 of 100 | no key: `source_not_configured` |
| `market_price` | BrickLink price guide, new and used | `price_observation(item 15011, used, sold, slot bricklink_used, eu, EUR, price, qty, sold, provider_key "S:6081-1")`, `price_current`, `price_watch`; the `inferred` set link becomes `matched/bricklink_api` from the reply | `GET /items/SET/6081-1/price` ×2 (up to 4), of 4,400 | no key: `source_not_configured` |

### 2.1 Variant: "prefer BrickLink's list" on, key present (Q13, Q23, decision F)

The user turns on *Prefer BrickLink's list when a key exists* in Settings (`setting prefer_bricklink_inventory=true`) and adds a second copy of 6081-1. The picker preselects *BrickLink's list*. No BrickLink list has been fetched for 6081-1 yet.

**One transaction:**

- `job(source=bricklink, kind=subsets, item 15011, queued)`;
- `copy(inventory_source=rebrickable, inventory_version=1, inventory_digest=9db79baf…, inventory_pending=bricklink, pending_job_id=<that job>)`, with Rebrickable's figure and part lines at once.

The copy page says "BrickLink list pending" and the copy can be checked offline.

**When the job succeeds** (1 call of 4,400), one transaction:

- `source_record(bricklink, subsets, S:6081-1, <raw reply>)`;
- `fetched_inventory(item 15011, source=bricklink, seq=1, is_latest=1, job, source_record)`;
- `fetched_inventory_part` lines, where BrickLink's `quantity − extra_quantity` is required and `extra_quantity` is spare (design § 4.2);
- `fetched_inventory_figure` lines.

Then the switch runs (design § 4.4). Lines with the same `(figure, item, colour, spare)` are **updated in place** with their check state carried and capped; new lines are inserted; vanished lines get `retired_at`. Then `copy.inventory_source=bricklink, fetched_inventory_id=…, inventory_digest=<BrickLink list digest>, inventory_pending=NULL, pending_job_id=NULL`. The receipt lists any marks that could not carry over.

In the replay, one Rebrickable line has no BrickLink counterpart and is retired, not deleted, and the copy gains one spare line. Figure parts stay on each figure's own Rebrickable list (Q15).

- **Out of budget or offline:** the job waits, the copy stays on Rebrickable's list with the note, and the user can cancel the pending switch.
- **Without a BrickLink key:** the picker never offers BrickLink and the switch has no effect.

A third copy added later takes the fetched BrickLink list at once, with no call.

---

## 3. Loose parts

**The user** opens Add → *Parts* and pastes `3023 x10`, `2339 x2`, `970c03 x1`. They choose colours (White, Black, Red), *Loose*, *used*, and storage *Box A* (created inline). Every row has a picture source:

- `3023` White and `2339` Black have `picture_url`;
- `970c03` Red has one too, since fig-004576 uses it.

So no warning shows. A part in a colour no inventory uses, with no BrickLink link and no Rebrickable key, would show "no picture known for this colour" (G5, Q17).

**Collection file (one Add receipt):**

| Table | Rows |
|---|---|
| `storage` | `(<uuid>, Box A, Box)` |
| `item`, `item_link` | already projected in § 2 |
| `stock` | `(kind=part, 44289 [3023], 18 [White], 10, used, Box A)`; `(…, 37722 [2339], 3 [Black], 2, …)`; `(…, 75973 [970c03], 7 [Red], 1, …)` |
| `event` | `add/receipt`, `stock/created` ×3, `storage/created` |
| `job` | per part: `matching`, `pictures`, `market_price` |

A second `3023 White used Box A` line is refused by `stock_merge_key`, whose generated keys see the NULL lot as equal. `stock.add_loose` merges it into the first row instead, as today (`stock.py:87-115`).

**Jobs:**

| Step | 3023 (1:1) | 2339 (no BrickLink id) | 970c03 in Red (colour-scoped) |
|---|---|---|---|
| `matching` | link exists: done | no link. Without a key: `item_provider_status(37722, bricklink, unmatched, no_match, {rebrickable: 2339})`. With a key: `GET /parts/2339/` (1 of 1,000) confirms empty `external_ids`; same row, raw reply in evidence | the resolution function (design § 3.2) picks `P 970c11` in Red: the Black-scoped `970c00` row does not apply to Red, and the unscoped row is preferred (G4, decision E) |
| `pictures` | `picture_url (44289, White)` → `…/elements/302301.jpg` | `…/elements/4159140.jpg` (Black) | the dump URL; BrickLink fallback `PN/5/970c11.png` |
| `market_price` | `GET /items/PART/3023/price?color_id=1` (2–4 of 4,400); `provider_key "P:3023/1"` | step ends `done` with `error_code=unidentified` (G9, Q21): the key exists, the BrickLink id does not | `GET /items/PART/970c11/price?color_id=5`; `provider_key "P:970c11/5"` |

Offline, all three rows exist and work in Part Picker, Matcher and Check Set Parts. 2339 Black is what 6081-1 needs twice, so the Matcher shows "2 in loose stock" on the copy.

---

## 4. Two loose minifigures

**The user** opens Add → *Minifigures*, types `fig-004576` and `fig-018222`, chooses *Loose*, *used*, *Box A*. Both rows open with their four parts. The waiter shows "No BrickLink id".

**Collection file (one Add receipt):**

| Table | Rows |
|---|---|
| `item` | the knight `97969` is already projected; the waiter `110744` is projected now with its four parts: `3277` Dark Brown, `3626cpr1966` Yellow, `970c84` Warm Pink, `973g27c01h01pr0007` White |
| `stock` | `(kind=minifigure, 97969, colour NULL, 1, used, Box A, missing 0, damaged 0, checked 0, inventory_source=rebrickable, inventory_version=1, inventory_digest=<fig-004576's digest>)`; the same for `110744` (G6, Q18: required for figures by CHECK). Each figure is its own row: `stock_merge_key` excludes figures |
| `stock_part` | four rows per figure from the figure's latest Rebrickable inventory, e.g. `(knight, 75973 [970c03], 7 [Red], 1)` |
| `event`, `job` | `add/receipt`; one item job per figure: `matching`, `pictures`, `market_price` |

**Jobs:**

| Step | fig-004576 | fig-018222 (newer than the mapping) |
|---|---|---|
| `matching` | **With the local mapping** (Ulf's install): the `M` link exists, so done; the item page says "matched by parts (local mapping, BrickStore test of <date>)". **Without it** (any other install until the public-flip decision): no link; the same choices as the waiter | no link and no API path: Rebrickable's `/minifigs/{num}/` carries no external ids, and BrickLink has no reverse lookup. `item_provider_status(110744, bricklink, unmatched, no_match)`. The figure page offers (Q19): *Identify with a photo*, where Brickognize `/predict/figs/` (1 of 100) writes `identification` plus `item_link(110744, brickognize, M, <candidate>, to_check, brickognize)`; or *Type the BrickLink id*, a `manual` link. No runtime composition match in 4.0 (G7) |
| `pictures` | order `bricklink, rebrickable_dump`: BrickLink `MN/0/<id>.png` when linked, else `cdn.rebrickable.com/media/sets/fig-004576.jpg` | Rebrickable only |
| `market_price` | `GET /items/MINIFIG/<id>/price` ×2 when linked; else `unidentified` | `unidentified`; its parts can be priced through their own links. Parts newer than the shipped mapping are counted in Tools & Admin's coverage, and the `same_number` pass proposes candidates when a BrickLink list is loaded (G8, Q20) |

Offline, both figures exist with their parts. "Check figure parts" works on `stock_part`.

---

## 5. What ran, in one table

| Moment | Network | Budgeted calls | Without any key | Offline |
|---|---|---|---|---|
| Setup | none | 0 | works | works |
| Catalogue import | 12 CDN downloads, 17 MB (once a day asked, not enforced) | 0 | works | works from files on disk |
| Keys | 3 test calls | BrickLink 1, Rebrickable 1, Brickset 0 | skipped | skipped |
| BrickLink lists | none (files) | 0 | works | works |
| Add 6081-1 | about 140 picture downloads | BrickLink 2–4, Brickset 1 | parts, figures and check work; prices `source_not_configured` | copy complete; pictures and prices later |
| … with "prefer BrickLink" | + 1 `subsets` | BrickLink +1 | not offered | copy on Rebrickable's list, BrickLink pending |
| Three loose parts | 3 picture downloads | BrickLink 2–4 per linked part; Rebrickable 0–1 | works; 2339 `unidentified` for prices | works |
| Two loose figures | 2 picture downloads | BrickLink 2 for a linked knight; Brickognize 0–1 | works; figures unlinked without the local mapping | works |

Every collection row carries its source:

- `catalogue_build_id`, the born key and the digest on items;
- `(set, version)` or `fetched_inventory_id` and the digest on copies, figure lines and loose figures;
- the line key on lines;
- `origin` and `catalogue_build_id` on links;
- `provider_key` on prices.

---

## 6. Gaps G1–G9: how each is closed

| Gap | Decision | Closed by |
|---|---|---|
| G1 dump download limit | Q14: tell, don't block | Button text states the once-a-day rule; *Build from today's files* is offered when they exist; no budget row (§ 1.1) |
| G2 figure parts and their provider | Q15: always the figure's own latest Rebrickable list | `copy_figure.inventory_source/version` or `fetched_inventory_id`; the copy page names it; `none` for a BrickLink-only figure, with the reason (§ 2, design § 4.5) |
| G3 figure part-list change | Q15 | `copy_figure.inventory_digest`, compared after a re-download (design § 4.4) |
| G4 several BrickLink ids for one part | Q16 as amended by E: preferred per part and colour | Colour-scoped links plus `preferred`; one resolution function (§ 3, design § 3.2) |
| G5 picture for a colour no set uses | Q17: BrickLink first, then the Rebrickable API with a key; order editable | `source_priority.pictures` with three sources; Add review warning (§ 3, design § 6.8) |
| G6 loose figures' part list | Q18 | `stock.inventory_source/version/fetched_inventory_id/digest`, required for figures (§ 4) |
| G7 a figure newer than the mapping | Q19: Brickognize or a typed id in 4.0 | Figure page choices; `item_provider_status`; `to_check` candidates (§ 4) |
| G8 dump newer than the mapping | Q20: coverage plus the `same_number` pass | Reconcile writes coverage per status; the pass runs with every build that has a BrickLink list (design § 6.4) |
| G9 a distinct error for "no provider id" | Q21 | `error_code='unidentified'` on `job` and `job_step` (CHECK) (§ 3) |
