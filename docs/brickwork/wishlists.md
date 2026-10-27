# Named wishlists and portable files

Planning → Wishlist has an All lists view and a picker for each active list, with live row counts. All lists labels each wish with its list name. Manage lists creates, renames, archives and restores lists. Archiving also archives the wishes that were live at that moment; restoring the list restores those wishes, leaving previously archived wishes archived. Names may repeat; use an id when a name is ambiguous in the CLI.

Select wishes to move or copy them in bulk, or use Move wish / Copy wish on wish detail. A target collision rejects the entire operation with no partial changes. Copy retains quantity, condition, maximum and currency, colour, note and item flags. Undo detaches the copied flags while keeping the original ones. List writes, transfers and their Undo use collection receipts in one transaction. Undo checks for intervening changes and archives newly created rows rather than deleting them. Restoring a wish or undoing a move into an archived list requires restoring that list first.

## Schema

`wishlist` (the lists) contains `id TEXT PRIMARY KEY`, `name`, `note`, `sort`, `archived_at`, `created_at`, and optional `bricklink_id`. The last field stores a BrickLink wanted list id, never an inferred one. The default list has id `default` and name `Wishlist`; a new list gets a uuid.

`wish` (the wishes) has a uuid `id`, `wishlist_id TEXT NOT NULL DEFAULT 'default' REFERENCES wishlist(id)`, a `kind` word, `item_id` and, for a part, `color_id`. The partial unique index `wish_live_key` is `(wishlist_id, item_id, color_key)` where `archived_at IS NULL`: wishes in different lists may share an item and colour. A maximum price and its currency are stored together or not at all (`max_price`, `max_price_currency`). A wish's flags are `wish_flag` rows. Nothing here is upgraded at run time: a 4.0 file has the tables from `setup` or the migration (`docs/data-model-4.0`).

## Import

Add → File supports BrickLink `INVENTORY` and `WANTEDLIST` XML and Rebrickable CSV. Choose the wishlist destination. With Use BrickLink wanted list ids enabled, an item's `WANTEDLISTID` selects a stored linked list. Unknown ids propose a new `BrickLink <id>` list in preview and create it only on confirmation. Disable the option or change the row's list to pick an existing target instead. Preview itself writes nothing. Unresolved catalogue identities and colour mappings remain in the unresolved preview.

BrickLink `MINQTY` (or inventory `QTY`) supplies quantity. `CONDITION` N/U/X maps to new/used/any; absent condition means any for wishes. `REMARKS` supplies the note. Non-negative `MAXPRICE` is a decimal string in the configured BrickLink currency, which is explicitly named in preview. Negative no-limit values are omitted. `QTYFILLED` is ignored with a preview note; it never becomes owned stock or invented progress. Repeated wishes are checked within their target list and require the existing add-to-quantity or skip decision.

CSV import accepts existing `set_num,quantity`, `part_num,color_id,quantity`, and `minifig_num,quantity` headers as well as exported `Set Number,Quantity` and `Part,Color,Quantity`. Rebrickable item and colour identities resolve to BrickLink through the existing resolver.

## Export formats

Export list / Export all lists offers BrickLink wanted list XML and Rebrickable CSV (sets or parts). The download summary lists skipped rows and omitted limits. Exports are read-only.

BrickLink example, without an XML declaration:

```xml
<INVENTORY><ITEM><ITEMTYPE>P</ITEMTYPE><ITEMID>3001</ITEMID><COLOR>4</COLOR><MINQTY>3</MINQTY><MAXPRICE>1.25</MAXPRICE><CONDITION>U</CONDITION><REMARKS>A &amp; B</REMARKS><NOTIFY>N</NOTIFY><WANTEDLISTID>1234</WANTEDLISTID></ITEM></INVENTORY>
```

Ids and colours are BrickLink canonical values, named through `core.items` (the preferred confirmed link, else a BrickLink-born number); a wish with no BrickLink number or colour is left out and listed in the summary. `MAXPRICE` appears only for a positive maximum in the configured BrickLink currency. A zero or a different currency omits the limit and adds a summary note. `CONDITION` is N/U for new/used; any omits it. Notes are XML escaped. `WANTEDLISTID` appears only when explicitly linked on the list; otherwise it is left out for the user to set after downloading. `QTYFILLED` is not exported.

Rebrickable set-list CSV (CRLF records):

```csv
Set Number,Quantity
10305-1,2
```

Rebrickable part-list CSV (CRLF records):

```csv
Part,Color,Quantity
3001,4,3
```

The sample identifiers describe the format; actual identifiers are obtained only from unique stored Rebrickable mappings. Part numbers and colour ids are translated independently. Missing or ambiguous mappings and rows outside the chosen kind are listed in the summary and omitted. The exporter never assumes that the BrickLink and Rebrickable identifiers match. Archived lists and wishes are excluded. All lists preserves each active wish as a separate row; the target site's duplicate import behavior applies.

### Documentation verification, 2026-10-17

[BrickLink Wanted List, Mass Upload](https://www.bricklink.com/help.asp?helpID=207&viewType=shop) confirms INVENTORY/ITEM structure, canonical type/number/colour, positive MAXPRICE, MINQTY, QTYFILLED, N/U condition, escaped REMARKS, and optional WANTEDLISTID. Its example uses NOTIFY=N; [Importing items with XML](https://www.bricklink.com/help.asp?helpID=2567&viewType=shop) explicitly describes Y/N notifications. There are no unconfirmed emitted BrickLink tag names. BrickLink's XML documentation does not explicitly specify the currency context of MAXPRICE, so using the configured BrickLink currency is the application policy required by this task. X is accepted on input as requested but is not emitted because the wanted-list upload documentation only lists N/U.

Rebrickable's [Importing parts](https://rebrickable.com/help/importing-parts/) and [Importing sets](https://rebrickable.com/help/importing-sets/) pages could not be retrieved. The requested `Set Number,Quantity` and `Part,Color,Quantity` headers are implemented and tested locally, but their current site acceptance could not be independently confirmed. No authenticated upload to either site was performed.

## API, CLI and MCP

All API operations use the existing authentication, write/read-only policy and idempotency receipts:

- `GET /api/v1/wishlists` (`?archived=true` includes archived lists)
- `POST /api/v1/wishlists` with `name`, optional `note`, `sort`, `bricklink_id`
- `PATCH /api/v1/wishlists/{id}` with those fields
- `DELETE /api/v1/wishlists/{id}` archives the list and live wishes
- `POST /api/v1/wishlists/{id}/restore`
- `POST /api/v1/wishlists/{id}/transfer` with `{"ids":[1,2],"copy":false}`; `id` is the target list; use `copy:true` to copy
- Wishes expose `list_id`, accept it on create/patch, and filter with `GET /api/v1/wishes?list={id}`
- `GET /api/v1/wishlists/{id}/export.xml` or `.csv?kind=sets|parts`; `id=all` includes every active list
- Add `summary=true` to export for a JSON envelope with `content`, `summary`, `filename`, `mimetype`. A direct API download also supplies `X-Wishlist-Exported`, `X-Wishlist-Omitted`, and `X-Wishlist-Notes` counts.

```sh
brickwork wishlist list
brickwork wishlist create 'Holiday'
brickwork wishlist rename <id> 'Gifts'
brickwork wishlist archive <id>
brickwork wishlist restore <id>
brickwork wishlist move <target-id> 1 2
brickwork wishlist copy <target-id> 1 2
brickwork wishlist undo <event-id>
brickwork wishlist export 'Gifts' --format bricklink > wishlist.xml
brickwork wishlist export all --format rebrickable --kind sets > sets.csv
brickwork wishlist export all --format rebrickable --kind parts --json
```

CLI file content goes to stdout and its summary to stderr; `--json` returns both together. MCP tools are generated from OpenAPI: `get_wishlists`, `post_wishlists`, `patch_wishlists_id`, `delete_wishlists_id`, `post_wishlists_id_restore`, `post_wishlists_id_transfer`, `export_wishlist_xml`, and `export_wishlist_csv`. Existing wish tools gain list fields. Use `summary:true` on export tools to receive both file content and omissions.
