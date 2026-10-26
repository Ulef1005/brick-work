# Standalone cutover (4.11j)

The v3 browser routes now live at the root. Old URLs return 404 with no redirect.
`/`, `/login`, `/logout`, `/manifest.webmanifest`, `/sw.js`, static assets and the current `/api/v1` keep their paths. The replaced upstream screens and both legacy API blueprints are removed.

| Methods | Old path | New path | Backing browser function (`web.views`) |
|---|---|---|---|
| GET | `/house/manage/tools` | `/manage/tools` | `bw_tools` |
| GET | `/house/manage/<page>` | `/manage/<page>` | `bw_admin` |
| POST | `/house/manage/<page>` | `/manage/<page>` | `bw_admin_write` |
| GET | `/house/manage/database/export` | `/manage/database/export` | `bw_export` |
| GET | `/house/manage/images/<int:image_id>` | `/manage/images/<int:image_id>` | `bw_image` |
| GET | `/house/manage/instructions/<int:identifier>/download` | `/manage/instructions/<int:identifier>/download` | `bw_instruction_download` |
| GET | `/house/manage/add` | `/manage/add` | `bw_add` |
| GET | `/house/manage/add/search` | `/manage/add/search` | `bw_add_search` |
| POST | `/house/manage/add/review` | `/manage/add/review` | `bw_add_review` |
| POST | `/house/manage/add/confirm` | `/manage/add/confirm` | `bw_add_confirm` |
| POST | `/house/manage/add/undo` | `/manage/add/undo` | `bw_add_undo` |
| GET | `/house/manage/add/jobs/<int:job>` | `/manage/add/jobs/<int:job>` | `bw_add_job` |
| POST | `/house/manage/add/jobs/<int:job>/retry` | `/manage/add/jobs/<int:job>/retry` | `bw_add_retry` |
| GET | `/house/workbench/check-parts` | `/workbench/check-parts` | `bw_check_parts` |
| GET | `/house/workbench/check-parts/<copy_id>` | `/workbench/check-parts/<copy_id>` | `bw_check_copy` |
| GET | `/house/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>` | `/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>` | `bw_check_figure` |
| GET | `/house/workbench/part-picker` | `/workbench/part-picker` | `bw_picker` |
| GET | `/house/workbench/matcher` | `/workbench/matcher` | `bw_matcher` |
| GET | `/house/workbench/match` | `/workbench/match` | `bw_matcher` |
| POST | `/house/workbench/check-parts/<copy_id>` | `/workbench/check-parts/<copy_id>` | `bw_check_write` |
| POST | `/house/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>` | `/workbench/check-parts/<copy_id>/figure/<minifig_type>/<minifig_no>` | `bw_check_figure_write` |
| POST | `/house/workbench/save/<action>` | `/workbench/save/<action>` | `bw_workbench_save` |
| GET | `/house/workbench/part-to-inventory` | `/workbench/part-to-inventory` | `bw_inventory` |
| GET | `/house/workbench/orders` | `/workbench/orders` | `bw_orders` |
| GET | `/house/workbench/orders/<int:order_id>` | `/workbench/orders/<int:order_id>` | `bw_order` |
| POST | `/house/workbench/part-to-inventory/detect` | `/workbench/part-to-inventory/detect` | `bw_inventory_detect` |
| POST | `/house/workbench/part-to-inventory/save` | `/workbench/part-to-inventory/save` | `bw_inventory_save` |
| POST | `/house/workbench/part-to-inventory/undo` | `/workbench/part-to-inventory/undo` | `bw_inventory_undo` |
| POST | `/house/workbench/orders/action/<action>` | `/workbench/orders/action/<action>` | `bw_orders_action` |
| GET | `/house/workbench/orders/<int:order_id>/short.xml` | `/workbench/orders/<int:order_id>/short.xml` | `bw_order_short` |
| GET | `/house/workbench/storage` | `/workbench/storage` | `bw_storages` |
| GET | `/house/workbench/storage/<identifier>` | `/workbench/storage/<identifier>` | `bw_storages` |
| POST | `/house/workbench/storage/action/<action>` | `/workbench/storage/action/<action>` | `bw_storage_action` |
| GET | `/house/collection/sets` | `/collection/sets` | `bw_sets` |
| GET | `/house/collection/<kind>` | `/collection/<kind>` | `bw_collection` |
| GET | `/house/collection/item/<int:item_id>` | `/collection/item/<int:item_id>` | `bw_collection_item` |
| GET | `/house/collection/item/<kind>/<path:number>` | `/collection/item/<kind>/<path:number>` | `bw_collection_item_by_number` |
| GET | `/house/collection/wishes` | `/collection/wishes` | `bw_collection_wishes` |
| GET | `/house/collection/wishes/<identifier>` | `/collection/wishes/<identifier>` | `bw_collection_wish` |
| GET | `/house/collection/lots/<identifier>` | `/collection/lots/<identifier>` | `bw_collection_lot` |
| GET | `/house/collection/purchase-places` | `/collection/purchase-places` | `bw_collection_places` |
| POST | `/house/collection/save/<action>` | `/collection/save/<action>` | `bw_collection_write` |
| GET | `/house/collection/jump` | `/collection/jump` | `bw_collection_jump` |
| GET | `/house/planning/<screen>` | `/planning/<screen>` | `bw_planning` |
| POST | `/house/planning/action/<action>` | `/planning/action/<action>` | `bw_planning_write` |

`GET, POST /manage/import-legacy` is new. `web.views.bw_import_legacy` calls `web.admin_ops.migrate`, then `core.importer.import_collection`. The CLI uses the same importer. Inputs are read-only, extras are optional (`--extras`), and the browser refuses an existing output. The established 3.2 mapping and proof remain unchanged; normal core connections perform the existing 3.3 upgrade.

No API endpoints or schema changes are introduced by this cutover. The old token setting and external refresh integration are removed. Browser defaults, Docker, API and MCP now use only the core store.

The naming allowlist retains only attribution, importer schemas/tests, historical schema/upgrade literals, the gate's own vocabulary, and this old-path table. Historical SQL names in release/design notes are described neutrally.

The standalone smoke test starts from an empty data directory, calls setup, blocks socket connection and DNS methods, imports a tiny eight-type synthetic XML catalogue, creates a storage and copy, edits a synthetic part line, records and undoes a manual price, checks event history and missing-key/disabled-source errors. The embedded drainer is disabled for deterministic offline execution; a price-only pipeline job is run explicitly. `scripts/check.sh` runs this test explicitly and as part of the full suite.
