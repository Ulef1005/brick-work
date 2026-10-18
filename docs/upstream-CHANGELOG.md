# Upstream BrickTracker changelog

Release history of the upstream BrickTracker project (releases 1.4.2 and older), preserved from the Brick Work fork.

## 1.4.2

### Bug Fixes

- **Fixed instructions downloads failing with "No instructions found on Rebrickable or Peeron"** (#171): Rebrickable now blocks scraping behind a Cloudflare challenge, so instructions are fetched from LEGO's own official building-instructions page instead
- **Fixed instructions never linking to sets with alphanumeric ids** (#166): Instructions for "Pick a Brick" / promotional builds whose set id begins with letters (e.g. `EG00029-1`) were orphaned and never associated with the set; the matching now handles alphanumeric set ids

## 1.4.1

### Enhancements

- **Added per-column header filters to the Parts table on the set details page**: The main Parts table now has an always-visible filter row under the column headers
  - Name: case-insensitive substring search
  - Color: dropdown populated from the colors present in the current results
  - Missing / Damaged: All / With / Without dropdowns
  - Checked: All / Checked / Unchecked
  - Filters combine (AND) and re-evaluate live as missing/damaged values or checkboxes change. Bulk actions (mark all missing, check all, etc.) only affect the rows visible under the active filter. Scoped to the main Parts table only; per-minifigure tables stay sort-only
- **"Reset to Defaults" confirmation now uses a Bootstrap modal instead of a browser dialog**: Replaced the native browser `confirm()` popup with a consistent Bootstrap modal matching the style of BrickTracker

### Bug Fixes

- **Fixed prices on the Statistics page being rounded to whole numbers** (Issue #146): All price values now display with two decimal places (`%.2f`) instead of being rounded to whole numbers (`%.0f`)

- **Fixed "Reset to Defaults" blanking all settings instead of restoring them** (Issue #149a, branch `bugfix/issue-149a`): "Reset to Defaults" was clearing all fields to empty/false instead of populating them with their actual default values
  - `resetToDefaults()` now reads from `window.DEFAULT_CONFIG` and restores each field to its proper default, matching the same logic used on initial page load
- **Fixed `BK_INSTRUCTIONS_ALLOWED_EXTENSIONS` being treated as a string instead of a list** (Issue #149b, branch `bugfix/issue-149b`): When this setting was saved via the admin panel, it was stored and cast as a plain string rather than a list, causing it to be iterated character by character (e.g. `['.', 'p', 'd', 'f']` instead of `['.pdf']`)
  - Added `allowed_extensions` to the list-type keyword detection in `_cast_value()`, matching the existing pattern used for `badge_order` settings
- **Fixed crash when importing sets containing minifigures or parts with no image on Rebrickable** (Issue #149c, branch `bugfix/issue-149c`): Adding or refreshing a set would fail entirely if any minifigure or part had no image URL, with error `Invalid URL '': No scheme supplied`
  - Rebrickable returns an empty string (not `None`) for missing images; normalize empty strings to `None` at the point of ingestion in `rebrickable_minifigure.py` and `individual_minifigure.py`, matching the existing pattern in `rebrickable_set.py`
  - Updated `rebrickable_image.py` to treat empty strings the same as `None` throughout, falling back to the configured nil placeholder image
  - Note: the originally reported sets could no longer reproduce the crash (images may have since been added on Rebrickable), so this fix is based on assumptions only
- **Fixed previously added set being re-added when adding an individual minifigure** (Issue #150, branch `bugfix/issue-150`): After adding a set, entering a `fig-` ID and confirming would add the previous set again instead of the minifigure, if user did not reload inbetween. 
  - `add.js` was creating a second `BrickMinifigureSocket` with its own listeners on the same button and input as `BrickSetSocket`, causing duplicate socket events and cross-socket state confusion
- **Fixed purchase date, price, and notes not being saved when adding an individual minifigure** (Issue #151, branch `bugfix/issue-151`): Filling in purchase date, price, or notes before clicking Add had no effect, only purchase location was saved
  - `BrickMinifigureSocket` was missing references to `#add-purchase-date`, `#add-purchase-price`, and `#add-description`, so those fields were never read or included in the socket emit
  - The backend already supported all three fields. This was just a frontend error
- **Fixed purchase date and price not being converted when adding an individual minifigure** (Issue #151 follow-up): Purchase date was stored as a raw `YYYY/MM/DD` string and price as a raw string instead of a Unix epoch float and float respectively, causing them to be silently dropped from statistics aggregations
  - `IndividualMinifigure.download()` now mirrors the conversion logic already present in `BrickSet.download()`: date parsed via `datetime.strptime` to timestamp, price cast to `float`
- **Fixed a price of 0 being treated as no price** (Issue #153): Setting a purchase price of `0` on sets, individual minifigures, or parts was indistinguishable from having no price set at all
  - Replaced truthiness checks (`if price`, `price or ''`) with explicit `None` checks throughout badge display, management input fields, and inline price update endpoints
- **Fixed deleting a wish with an owner assigned** (Issue #152, branch `bugfix/issue-152`): Resolved foreign key constraint error when removing a set from the wishlist that had an owner assigned
  - Wish owners are now deleted before the wish itself, respecting the FK constraint

## 1.4

### Bug Fixes

- **Fixed client-side table sorting corruption** (Issue #136): Resolved data corruption when using sort buttons with DataTables header sorting in client-side pagination mode
  - Sort buttons now trigger actual table header clicks instead of using separate `columns.sort()`
  - Header clicks sync button states to match current sort
  - Prevents misaligned images, colors, and links when mixing sorting methods
- **Fixed storage deletion error handling**: Added proper validation and user-friendly error messages when attempting to delete storage locations that are still in use
  - Shows detailed count of items using the storage (sets, individual minifigures, individual parts, part lots)
  - Provides clickable link to storage details page for easy navigation
  - Prevents accidental deletion of storage locations with referenced items
- **Fixed bulk parts redirect**: Corrected endpoint reference from `individual_part.list_all` to `individual_part.list` after route function rename
- **Fixed purchase location templates**: Created missing template files for purchase location pages
- **Fixed set refresh functionality**: Resolved issues with refreshing sets from Rebrickable
  - Fixed foreign key constraint errors during refresh by reusing existing set IDs instead of generating new UUIDs
  - Implemented UPDATE-then-INSERT pattern to properly update existing parts while preserving user tracking data
  - Part quantities now correctly sync with Rebrickable during refresh
  - User tracking data (`checked`, `missing`, `damaged`) is preserved across refreshes
  - New parts from Rebrickable are added to local inventory during refresh
  - Orphaned parts (parts no longer in Rebrickable's inventory) are now properly removed during refresh
  - Refresh now works correctly for both set parts and minifigure parts
  - Uses temporary tracking table to identify which parts are still valid before cleanup
- **Fixed Socket.IO connections behind reverse proxies**: Resolved WebSocket disconnection issues when using Traefik, Nginx, or other reverse proxies
  - Root cause: Setting `BK_DOMAIN_NAME` enables strict CORS checking that fails with reverse proxies
  - Solution: Leave `BK_DOMAIN_NAME` empty for reverse proxy deployments (allows all origins by default)
  - Added debug logging for Socket.IO connections to help troubleshoot proxy issues
- **Fixed bulk import hanging on empty set numbers**: Resolved issue where trailing commas in bulk import input would cause infinite loops
  - Empty strings from trailing commas (e.g., `"10312, 21348, "`) are now filtered out before processing
  - Prevents "Set number cannot be empty" errors from blocking the bulk import queue
- **Added notes display toggles**: Added configuration options to show/hide notes on grid and detail views
  - New `BK_SHOW_NOTES_GRID` setting (default: `false`) - controls whether notes appear on grid view cards
  - New `BK_SHOW_NOTES_DETAIL` setting (default: `true`) - controls whether notes appear on set detail pages
  - Notes display as an info alert box below badges when enabled
  - Both settings can be toggled in Admin -> Live Settings panel without container restart
  - Fixed consolidated SQL query to include description field for proper notes display in server-side pagination
- **Fixed permission denied when running as non-root user** (Issue #138): Resolved container startup failure when using `user:` directive in docker-compose
  - Added `chmod -R a+rX /app` to Dockerfile to ensure all files are readable regardless of build environment
  - Added commented `user:` example in `compose.yaml` to document non-root support

### Breaking Changes

- **Parts default order column names changed**: The `BK_PARTS_DEFAULT_ORDER` environment variable now uses `"combined"` instead of `"bricktracker_parts"` for column references
  - If you have a custom `BK_PARTS_DEFAULT_ORDER` setting, update column references:
    - `"bricktracker_parts"."spare"` → `"combined"."spare"`
    - `"bricktracker_parts"."part"` → `"combined"."part"`
    - `"bricktracker_parts"."quantity"` → `"combined"."quantity"`
  - Or remove the custom setting to use the new defaults
  - See `.env.sample` for the full list of available column names

### New Features

- **Sortable Checked column** (Issue #137): The "Checked" column in set inventory tables can now be sorted
  - Click the "Checked" header to sort by checked/unchecked status
  - Works in both parts table and part lots table

- **Quick-add individual parts toggle**: New `BK_HIDE_QUICK_ADD_INDIVIDUAL_PARTS` setting to hide the quick-add menu in set parts tables
  - Hides the "Add to individual parts" option in the row menu dropdown
  - Useful when you want individual parts tracking enabled but don't need quick-add from set inventory

- **Individual Minifigures Tracking**
  - Track loose/individual minifigures outside of sets
  - Part-level tracking for individual minifigures with problem states (missing/damaged/checked)
  - Complete metadata support (owners, tags, statuses, storage, purchase info)
  - Purchase tracking with date, location, and price
  - Quick navigation from set minifigures to individual instances
  - Filter and search capabilities
  - Feature flags:
    - `BK_HIDE_INDIVIDUAL_MINIFIGURES`: Hides individual minifigures UI elements (navbar menu item, links from minifigure detail pages)
    - `BK_DISABLE_INDIVIDUAL_MINIFIGURES`: Enables read-only mode - all individual minifigure pages remain accessible but with all editing fields disabled (quantity, parts table, metadata inputs), delete buttons hidden, and write operations blocked.

- **Individual Parts Tracking**
  - Track loose parts outside of sets and minifigures
  - Quick-add functionality from set parts tables
  - Complete metadata support (owners, tags, storage, purchase info)
  - Problem tracking (missing/damaged/checked states)
  - Purchase tracking with date, location, and price
  - Bulk part addition interface
  - Feature flags:
    - `BK_HIDE_INDIVIDUAL_PARTS`: Hides individual parts UI elements (navbar menu item, "Add Parts" button, links from part detail pages)
    - `BK_DISABLE_INDIVIDUAL_PARTS`: Enables read-only mode - all individual parts and lot pages remain accessible but with all editing fields disabled (quantity, missing/damaged, parts table, metadata inputs), delete buttons hidden, "Add Parts" menu item removed, and write operations blocked. The /add/ page also hides the "Adding individual parts?" section.

- **Part Lots System**
  - Organize individual parts into logical lots/collections
  - Lot-level metadata (name, description, created date)
  - Shared metadata across lot (storage, purchase info)
  - View all parts in a lot with filtering

- **Purchase Location Management**
  - Centralized purchase location tracking for sets, individual minifigures, parts, and lots
  - New purchase location management page (`/purchase-locations/`)
  - Track which items were purchased from each location
  - Integrated with existing storage and owner metadata systems

- **Rebrickable Color Database**
  - Caches color information from Rebrickable API
  - Provides BrickLink color ID mapping
  - Reduces repeated API calls for color data
  - Supports export functionality with correct color IDs

- **Export Functionality**
  - Added export system in admin panel for sets, parts, and problem parts
  - Export accordion in `/admin/` with three main categories:
    - **Export Sets**: Rebrickable CSV format for collection tracking
    - **Export All Parts**: Three formats available:
      - Rebrickable CSV (Part, Color, Quantity)
      - LEGO Pick-a-Brick CSV (elementId, quantity)
      - BrickLink XML (wanted list format)
    - **Export Missing/Damaged Parts**: Same three formats as parts exports
  - All exports aggregate quantities automatically (parts by part+color, LEGO by element ID)
  - BrickLink exports use proper BrickLink part numbers and color IDs when available
  - Format information displayed in UI for user guidance
- **Badge Order Customization**
  - Added customizable badge ordering for set cards and detail pages
  - Separate configurations for Grid view (`/sets/` cards) and Detail view (individual set pages)
  - Configure via environment variables in `.env` file:
    - `BK_BADGE_ORDER_GRID`: Comma-separated badge keys for grid view (default: theme,year,parts,total_minifigures,owner)
    - `BK_BADGE_ORDER_DETAIL`: Comma-separated badge keys for detail view (default: all 16 badges)
  - Can also be configured via Live Settings page in admin panel under "Default Ordering & Formatting"
  - Changes apply immediately without restart when edited via admin panel
  - 16 available badge types: theme, tag, year, parts, instance_count, total_minifigures, total_missing, total_damaged, owner, storage, purchase_date, purchase_location, purchase_price, instructions, rebrickable, bricklink
- **Front Page Parts Display**
  - Added latest/random parts section to the front page alongside sets and minifigures
  - Shows 6 parts with quantity badges and other relevant information
  - Respects `BK_RANDOM` configuration (random selection when enabled, latest when disabled)
  - Respects `BK_HIDE_SPARE_PARTS` configuration
  - Respects `BK_HIDE_ALL_PARTS` configuration for "All parts" button visibility
- **NOT Filter Toggle Buttons**
  - Added toggle buttons next to all filter dropdowns to switch between "equals" and "not equals" modes
  - Visual feedback: Button displays red with "not equals" icon (≠) when in NOT mode
  - Works with all filter types: Status, Theme, Owner, Storage, Purchase Location, Tag, and Year
  - Supports both client-side and server-side pagination modes
  - Filter chains persist NOT states across page reloads via URL parameters (e.g., `?theme=-frozen&status=-has-missing`)
  - Clear filters button resets all toggle states to equals mode
  - Enables complex filter combinations like "Show me 2025 sets that are NOT Frozen theme AND have missing pieces"
- **Notes/Comments Field**
  - Added general notes field to set details for storing custom notes and comments
  - Accessible via Management -> Notes accordion section on set detail pages
  - Auto-save functionality with visual feedback (save icon updates on change)
  - Notes display prominently below badges on set cards when populated
  - Supports multi-line text input with configurable row height
  - Clear button to quickly remove notes
- **Bulk Set Refresh**
  - Added batch refresh functionality for updating multiple sets at once
  - New "Bulk Refresh" button appears on Admin -> Sets needing refresh page
  - Pre-populates text-area with comma-separated list of all sets needing refresh
  - Follows same pattern as bulk add with progress tracking and set card preview
  - Shows real-time progress with current set being processed
  - Failed sets remain in input field for easy retry

### Database Improvements

- **Standardized ON DELETE Behavior**: Unified foreign key deletion handling across all metadata tables
  - All metadata foreign keys now use RESTRICT (prevent deletion if referenced)
  - Prevents accidental deletion of storage locations or purchase locations that are in use
- **Performance Indexes Added**: New composite indexes for common query patterns
  - `idx_individual_parts_lot_id_part_color` - Optimizes listing parts within a lot
  - `idx_individual_parts_missing_damaged` - Optimizes finding parts with problems
  - `idx_individual_minifigure_parts_checked` - Optimizes finding unchecked parts in minifigures
- **Consolidated Metadata Tables**: Migration 0027 removes foreign key constraints from metadata junction tables
  - `bricktracker_set_owners`, `bricktracker_set_tags`, `bricktracker_set_statuses` now accept any entity type
  - Enables reusing metadata tables for sets, individual minifigures, individual parts, and lots
- **Fixed Schema Drop Script**: Resolved foreign key constraint errors during database reset
  - Added proper table drop ordering (children before parents)
  - Implemented `PRAGMA foreign_keys OFF/ON` wrapping
  - Includes all new tables from migrations 0021-0027


### Configuration & Environment Variables

- **New Configuration Options**:
  - `BK_HIDE_INDIVIDUAL_MINIFIGURES` - Hide individual minifigures UI elements in navigation
  - `BK_DISABLE_INDIVIDUAL_MINIFIGURES` - Block write operations for individual minifigures (view-only mode)
  - `BK_HIDE_INDIVIDUAL_PARTS` - Hide individual parts UI elements in navigation
  - `BK_DISABLE_INDIVIDUAL_PARTS` - Block write operations for individual parts (view-only mode)
  - `BK_BADGE_ORDER_GRID` - Customize badge order on set cards in grid view (comma-separated list)
  - `BK_BADGE_ORDER_DETAIL` - Customize badge order on set detail pages (comma-separated list)
  - `BK_SHOW_NOTES_GRID` - Show notes on set cards in grid view (default: false)
  - `BK_SHOW_NOTES_DETAIL` - Show notes on set detail pages (default: true)
  - All new settings support live configuration updates via Admin panel

### Technical Improvements

- **Route Protection Decorators**: New decorator pattern for feature flag enforcement
  - `@require_individual_minifigures_write` - Blocks writes when feature is disabled
  - `@require_individual_parts_write` - Blocks writes when feature is disabled
  - Allows viewing existing data while preventing new additions
- **SQL Query Organization**: New query directory structure for individual features
  - `bricktracker/sql/individual_minifigure/` - All individual minifigure queries
  - `bricktracker/sql/individual_part/` - All individual part queries
  - `bricktracker/sql/individual_part_lot/` - All part lot queries
  - `bricktracker/sql/rebrickable_colors/` - Color reference queries
  - `bricktracker/sql/rebrickable_parts/` - Part reference queries
- **Database Migrations**: 7 new migrations (0021-0027)
  - 0021: Individual minifigures and parts tables
  - 0022: Individual part lots system with proper foreign keys
  - 0023: Performance indexes for individual features
  - 0024: Rebrickable colors cache table
  - 0025: Additional composite indexes for query optimization
  - 0026: Standardized ON DELETE behavior across metadata tables
  - 0027: Consolidated metadata tables (remove FK constraints)


## 1.3.1

### New Functionality

- **Database Integrity Check and Cleanup**
  - Added database integrity scanner to detect orphaned records and foreign key violations
  - New "Check Database Integrity" button in admin panel scans for issues
  - Detects orphaned sets, parts, and parts with missing set references
  - Warning prompts users to backup database before cleanup
  - Cleanup removes all orphaned records in one operation
  - Detailed scan results show affected records with counts and descriptions
- **Database Optimization**
  - Added "Optimize Database" button to re-create performance indexes
  - Safe to run after database imports or restores
  - Re-creates all indexes from migration #19 using `CREATE INDEX IF NOT EXISTS`
  - Runs `ANALYZE` to rebuild query statistics
  - Runs `PRAGMA optimize` for additional query plan optimization
  - Helpful after importing backup databases that may lack performance optimizations

### Bug Fixes

- **Fixed foreign key constraint errors during set imports**: Resolved `FOREIGN KEY constraint failed` errors when importing sets with parts and minifigures
  - Fixed insertion order in `bricktracker/part.py`: Parent records (`rebrickable_parts`) now inserted before child records (`bricktracker_parts`)
  - Fixed insertion order in `bricktracker/minifigure.py`: Parent records (`rebrickable_minifigures`) now inserted before child records (`bricktracker_minifigures`)
  - Ensures foreign key references are valid when SQLite checks constraints
  
- **Fixed set metadata updates**: Owner, status, and tag checkboxes now properly persist changes on set details page
  - Fixed `update_set_state()` method to commit database transactions (was using deferred execution without commit)
  - All metadata updates (owner, status, tags, storage, purchase info) now work consistently
- **Fixed nil image downloads**: Placeholder images for parts and minifigures without images now download correctly
  - Removed early returns that prevented nil image downloads
  - Nil images now properly saved to configured folders (e.g., `/app/data/parts/nil.jpg`)
- **Fixed error logging for missing files**: File not found errors now show actual configured folder paths instead of just URL paths
  - Added detailed logging showing both file path and configured folder for easier debugging
- **Fixed minifigure filters in client-side pagination mode**: Owner and other filters now work correctly when server-side pagination is disabled
  - Aligned filter behavior with parts page (applies filters server-side, then loads filtered data for client-side search)

## 1.3

### Breaking Changes 

#### Data Folder Consolidation

> **Warning** 
> **BREAKING CHANGE**: Version 1.3 consolidates all user data into a single `data/` folder for easier backup and volume mapping.

- **Path handling**: All relative paths are now resolved relative to the application root (`/app` in Docker)
  - Example: `data/app.db` → `/app/data/app.db`

- **New default paths** (automatically used for new installations):
  - Database: `data/app.db` (was: `app.db` in root)
  - Configuration: `data/.env` (was: `.env` in root) - *optional, backward compatible*
  - CSV files: `data/*.csv` (was: `*.csv` in root)
  - Images/PDFs: `data/{sets,parts,minifigures,instructions}/` (was: `static/*`)

- **Configuration file (.env) location**:
  - New recommended location: `data/.env` (included in data volume, settings persist)
  - Backward compatible: `.env` in root still works (requires volume mount for admin panel persistence)
  - Priority: `data/.env` > `.env` (automatic detection, no migration required)

- **Migration options**:
  1. **Migrate to new structure** (recommended - single volume for all data including .env)
  2. **Keep current setup** (backward compatible - old paths continue to work)

See [Migration Guide](docs/migration_guide.md) for detailed instructions

#### Default Minifigures Folder Change

> **Warning**
> **BREAKING CHANGE**: Default minifigures folder path changed from `minifigs` to `minifigures`

- **Impact**: Users who relied on the default `BK_MINIFIGURES_FOLDER` value (without explicitly setting it) will need to either:
  1. Set `BK_MINIFIGURES_FOLDER=minifigs` in their environment to maintain existing behavior, or
  2. Rename their existing `minifigs` folder to `minifigures`
- **No impact**: Users who already have `BK_MINIFIGURES_FOLDER` explicitly configured
- Improved consistency across documentation and Docker configurations

### New Features

- **Live Settings changes**
  - Added live environment variable configuration management system
    - Configuration Management interface in admin panel with live preview and badge system
    - **Live settings**: Can be changed without application restart (menu visibility, table display, pagination, features)
    - **Static settings**: Require restart but can be edited and saved to .env file (authentication, server, database, API keys)
    - Advanced badge system showing value status: True/False for booleans, Set/Default/Unset for other values, Changed indicator
    - Live API endpoints: `/admin/api/config/update` for immediate changes, `/admin/api/config/update-static` for .env updates
    - Form pre-population with current values and automatic page reload after successful live updates
  - Fixed environment variable lock detection in admin configuration panel
    - Resolved bug where all variables appeared "locked" after saving live settings
    - Lock detection now correctly identifies only Docker environment variables set before .env loading
    - Variables set via Docker's `environment:` directive remain properly locked
    - Variables from data/.env or root .env are correctly shown as editable
  - Added configuration persistence warning in admin panel
    - Warning banner shows when using .env in root (non-persistent)
    - Success banner shows when using data/.env (persistent)
    - Provides migration instructions directly in the UI
- **Spare Parts**
  - Added spare parts control options
    - `BK_SKIP_SPARE_PARTS`: Skip importing spare parts when downloading sets from Rebrickable (parts not saved to database)
    - `BK_HIDE_SPARE_PARTS`: Hide spare parts from all parts lists (parts must still be in database)
    - Both options are live-changeable in admin configuration panel
    - Options can be used independently or together for flexible spare parts management
    - Affects all parts displays: /parts page, set details accordion, minifigure parts, and problem parts
- **Pagination**
  - Added individual pagination control system per entity type
    - `BK_SETS_SERVER_SIDE_PAGINATION`: Enable/disable pagination for sets
    - `BK_PARTS_SERVER_SIDE_PAGINATION`: Enable/disable pagination for parts
    - `BK_MINIFIGURES_SERVER_SIDE_PAGINATION`: Enable/disable pagination for minifigures
    - Device-specific pagination sizes (desktop/mobile) for each entity type
    - Supports search, filtering, and sorting in both server-side and client-side modes
- **Peeron Instructions**
  - Added Peeron instructions integration
    - Full image caching system with automatic thumbnail generation
    - Optimized HTTP calls by downloading full images once and generating thumbnails locally
    - Automatic cache cleanup after PDF generation to save disk space
- **Parts checkmark**
  - Added parts checking/inventory system
    - New "Checked" column in parts tables for tracking inventory progress
    - Checkboxes to mark parts as verified during set walkthrough
    - `BK_HIDE_TABLE_CHECKED_PARTS`: Environment variable to hide checked column
- **Set Consolidation**
  - Added set consolidation/grouping functionality
    - Automatic grouping of duplicate sets on main sets page
    - Shows instance count with stack icon badge (e.g., "3 copies")
    - Expandable drawer interface to view all set copies individually
    - Full set cards for each instance with all badges, statuses, and functionality
    - `BK_SETS_CONSOLIDATION`: Environment variable to enable/disable consolidation (default: false)
    - Backwards compatible - when disabled, behaves exactly like original individual view
    - Improved theme filtering: handles duplicate theme names correctly
    - Fixed set number sorting: proper numeric sorting in both ascending and descending order
    - Mixed status indicators for consolidated sets: three-state checkboxes (unchecked/partial/checked) with count badges
      - Template logic handles three states: none (0/2), all (2/2), partial (1/2) with visual indicators
      - Purple overlay styling for partial states, disabled checkboxes for read-only consolidated status display
      - Individual sets maintain full interactive checkbox functionality
- **Statistics**
  - Added comprehensive statistics system (#91)
    - New Statistics page with collection analytics
    - Financial overview: total cost, average price, price range, investment tracking
    - Collection metrics: total sets, unique sets, parts count, minifigures count
    - Theme distribution statistics with clickable drill-down to filtered sets
    - Storage location statistics showing sets per location with value calculations
    - Purchase location analytics with spending patterns and date ranges
    - Problem tracking: missing and damaged parts statistics
    - Clickable numbers throughout statistics that filter to relevant sets
    - `BK_HIDE_STATISTICS`: Environment variable to hide statistics menu item
    - Year-based analytics: Sets by release year and purchases by year
      - Sets by Release Year: Shows collection distribution across LEGO release years
      - Purchases by Year: Tracks spending patterns and acquisition timeline
      - Year summary with peak collection/spending years and timeline insights
    - Enhanced statistics interface and functionality
      - Collapsible sections: All statistics sections have clickable headers to expand/collapse
      - Collection growth charts: Line charts showing sets, parts, and minifigures over time
      - Configuration options: `BK_STATISTICS_SHOW_CHARTS` and `BK_STATISTICS_DEFAULT_EXPANDED` environment variables
- **Admin Page Section Expansion**
  - Added configurable admin page section expansion
    - `BK_ADMIN_DEFAULT_EXPANDED_SECTIONS`: Environment variable to specify which sections expand by default
    - Accepts comma-separated list of section names (e.g., "database,theme,instructions")
    - Valid sections: authentication, instructions, image, theme, retired, metadata, owner, purchase_location, status, storage, tag, database
    - URL parameters take priority over configuration (e.g., `?open_database=1`)
    - Database section expanded by default to maintain original behavior
    - Smart metadata handling: sub-section expansion automatically expands parent metadata section
- **Duplicate Sets filter**
  - Added duplicate sets filter functionality
    - New filter button on Sets page to show only duplicate/consolidated sets
    - `BK_SHOW_SETS_DUPLICATE_FILTER`: Environment variable to show/hide the filter button (default: true)
    - Works with both server-side and client-side pagination modes
    - Consolidated mode: Shows sets that have multiple instances
    - Non-consolidated mode: Shows sets that appear multiple times in collection
- **Bricklink Links**
  - Added BrickLink links for sets
    - BrickLink badge links now appear on set cards and set details pages alongside Rebrickable links
    - `BK_BRICKLINK_LINK_SET_PATTERN`: New environment variable for BrickLink set URL pattern (default: https://www.bricklink.com/v2/catalog/catalogitem.page?S={set_num})
    - Controlled by existing `BK_BRICKLINK_LINKS` environment variable
- **Dark Mode** 
  - Added dark mode support
    - `BK_DARK_MODE`: Environment variable to enable dark mode theme (default: false)
    - Uses Bootstrap 5.3's native dark mode with `data-bs-theme` attribute
    - Live-changeable via Admin > Live Settings
    - Setting persists across sessions via .env file
- **Alphanumetic Set Number**
  - Added alphanumeric set number support
    - Database schema change: Set number column changed from INTEGER to TEXT
    - Supports LEGO promotional and special edition sets with letters in their numbers
    - Examples: "McDR6US-1", "COMCON035-1", "EG00021-1"
    
### Improvements 

- Improved WebSocket/Socket.IO reliability for mobile devices
  - Changed connection strategy to polling-first with automatic WebSocket upgrade
  - Increased connection timeout to 30 seconds for slow mobile networks
  - Added ping/pong keepalive settings (30s timeout, 25s interval)
  - Improved server-side connection logging with user agent and transport details
- Fixed dynamic sort icons across all pages
  - Sort icons now properly toggle between ascending/descending states
- Improved DataTable integration
  - Disabled column header sorting when server-side pagination is enabled
  - Prevents conflicting sort mechanisms between DataTable and server-side sorting
- Enhanced color dropdown functionality
  - Automatic merging of duplicate color entries with same color_id
  - Keeps entries with valid RGB data, removes entries with None/empty RGB
  - Preserves selection state during dropdown consolidation
  - Consistent search behavior (instant for client-side, Enter key for server-side)
  - Mobile-friendly pagination navigation
- Added performance optimization
  - SQLite WAL Mode:
    - Increased cache size to 10,000 pages (~40MB) for faster query execution
    - Set temp_store to memory for accelerated temporary operations
    - Enabled foreign key constraints and optimized synchronous mode
    - Added ANALYZE for improved query planning and statistics
  - Database Indexes (Migration 0019):
    - High-impact composite index for problem parts aggregation (`idx_bricktracker_parts_id_missing_damaged`)
    - Parts lookup optimization (`idx_bricktracker_parts_part_color_spare`)
    - Set storage filtering (`idx_bricktracker_sets_set_storage`)
    - Search optimization with case-insensitive indexes (`idx_rebrickable_sets_name_lower`, `idx_rebrickable_parts_name_lower`)
    - Year and theme filtering optimization (`idx_rebrickable_sets_year`, `idx_rebrickable_sets_theme_id`)
    - Additional indexes for purchase dates, quantities, sorting, and minifigures aggregation
  - Statistics Query Optimization:
    - Replaced separate subqueries with efficient CTEs (Common Table Expressions)
    - Consolidated aggregations for set, part, minifigure, and financial statistics
  - Added default image handling for sets without images
    - Sets with null/missing images from Rebrickable API now display placeholder image
    - Automatic fallback to nil.png from parts folder for set previews
    - Copy of nil placeholder saved as set image for consistent display across all routes
    - Prevents errors when downloading sets that have no set_img_url in API response
  - Fixed instructions download from Rebrickable
    - Replaced cloudscraper with standard requests library
    - Resolves 403 Forbidden errors when downloading instruction PDFs
  - Fixed instructions display and URL generation
    - Fixed "Open PDF" button links to use correct data route
    - Corrected path resolution for data/instructions folder
    - Fixed instruction listing page to scan correct folder location
    - Fixed Peeron PDF creation to use correct data folder path
  - Fixed foreign key constraint error when adding sets
    - Rebrickable set is now inserted before BrickTracker set to satisfy FK constraints
    - Resolves "FOREIGN KEY constraint failed" error when adding sets
  - Fixed atomic transaction handling for set downloads
    - All database operations during set addition now use deferred execution
    - Ensures all-or-nothing behavior: if any part fails (set info, parts, minifigs), nothing is committed
    - Prevents partial set additions that would leave the database in an inconsistent state
    - Metadata updates (owners, tags) now defer until final commit
    
## 1.2.4

> **Warning**
> To use the new BrickLink color parameter in URLs, update your `.env` file:
> `BK_BRICKLINK_LINK_PART_PATTERN=https://www.bricklink.com/v2/catalog/catalogitem.page?P={part}&C={color}`

- Add BrickLink color and part number support for accurate BrickLink URLs
  - Database migrations to store BrickLink color ID, color name, and part number
  - Updated Rebrickable API integration to extract BrickLink data from external_ids
  - Enhanced BrickLink URL generation with proper part number fallback
  - Extended admin set refresh to detect and track missing BrickLink data

## 1.2.3

Added search/filter/sort options to `parts` and `minifigures`.

## 1.2.2

Fix legibility of "Damaged" and "Missing" fields for tiny screen by reducing horizontal padding
Fixed instructions download from Rebrickable

## 1.2.2:

This release fixes a bug where orphaned parts in the `inventory` table are blocking the database upgrade.

## 1.2.1:

This release fixes a bug where you could not add a set if no metadata was configured.

## 1.2.0:

> **Warning**
> "Missing" part has been renamed to "Problems" to accomodate for missing and damaged parts.
> The associated environment variables have changed named (the old names are still valid)

### Environment

- Renamed: `BK_HIDE_MISSING_PARTS` -> `BK_HIDE_ALL_PROBLEMS_PARTS`
- Added: `BK_HIDE_TABLE_MISSING_PARTS`, hide the Missing column in all tables
- Added: `BK_HIDE_TABLE_DAMAGED_PARTS`, hide the Damaged column in all tables
- Added: `BK_SHOW_GRID_SORT`, show the sort options on the grid by default
- Added: `BK_SHOW_GRID_FILTERS`, show the filter options on the grid by default
- Added: `BK_HIDE_ALL_STORAGES`, hide the "Storages" menu entry
- Added: `BK_STORAGE_DEFAULT_ORDER`, ordering of storages
- Added: `BK_PURCHASE_LOCATION_DEFAULT_ORDER`, ordering of purchase locations
- Added: `BK_PURCHASE_CURRENCY`, currency to display for purchase prices
- Added: `BK_PURCHASE_DATE_FORMAT`, date format for purchase dates
- Documented: `BK_FILE_DATETIME_FORMAT`, date format for files on disk (instructions, theme)

### Code

- Changer
    - Revert the checked state of a checkbox if an error occured

- Form
    - Migrate missing input fields to BrickChanger

- General cleanup

- Metadata
    - Underlying class to implement more metadata-like features

- Minifigure
    - Deduplicate
    - Compute number of parts

- Parts
    - Damaged parts

- Sets
    - Refresh data from Rebrickable
    - Fix missing @login_required for set deletion
    - Ownership
    - Tags
    - Storage
    - Purchase location, date, price

- Storage
    - Storage content and list

- Socket
    - Add decorator for rebrickable, authenticated and threaded socket actions

- SQL
    - Allow for advanced migration scenarios through companion python files
    - Add a bunch of the requested fields into the database for future implementation

- Wish
    - Requester

### UI

- Add
    - Allow adding or bulk adding by pressing Enter in the input field

- Admin
    - Grey out legacy tables in the database view
    - Checkboxes renamed to Set statuses
    - List of sets that may need to be refreshed

- Cards
    - Use macros for badge in the card header

- Form
    - Add a clear button for dynamic text inputs
    - Add error message in a tooltip for dynamic inputs

- Minifigure
    - Display number of parts

- Parts
    - Use Rebrickable URL if stored (+ color code)
    - Display color and transparency
    - Display if print of another part
    - Display prints using the same base
    - Damaged parts
    - Display same parts using a different color

- Sets
    - Add a flag to hide instructions in a set
    - Make checkbox clickable on the whole width of the card
    - Management
        - Ownership
        - Tags
        - Refresh
        - Storage
        - Purchase location, date, price

- Sets grid
    - Collapsible controls depending on screen size
    - Manually collapsible filters (with configuration variable for default state)
    - Manually collapsible sort (with configuration variable for default state)
    - Clear search bar

- Storage
    - Storage list
    - Storage content

- Wish
    - Requester

## 1.1.1: PDF Instructions Download

### Instructions

- Added buttons for instructions download from Rebrickable


## 1.1.0: Deduped sets, custom checkboxes and database upgrade

### Database

- Sets
    - Deduplicating rebrickable sets (unique) and bricktracker sets (can be n bricktracker sets for one rebrickable set)

### Docs

- Removed extra `<br>` to accomodate Gitea Markdown
- Add an organized DOCS.md documentation page
- Database upgrade/migration
- Checkboxes

### Code

- Admin
    - Split the views before admin because an unmanageable monster view

- Checkboxes
    - Customizable checkboxes for set (amount and names, displayed on the grid or not)
    - Replaced the 3 original routes to update the status with a generic route to accomodate any custom status

- Instructions
    - Base instructions on RebrickableSet (the generic one) rather than BrickSet (the specific one)
    - Refine set number detection in file name by making sure each first items is an integer

- Python
    - Make stricter function definition with no "arg_or_keyword" parameters

- Records
    - Consolidate the select() -> not None or Exception -> ingest() process duplicated in every child class

- SQL
    - Forward-only migration mechanism
    - Check for database too far in version
    - Inject the database version in the file when downloading it
    - Quote all indentifiers as best practice
    - Allow insert query to be overriden
    - Allow insert query to force not being deferred even if not committed
    - Allow select query to push context in BrickRecord and BrickRecordList
    - Make SQL record counters failsafe as they are used in the admin and it should always work
    - Remove BrickSQL.initialize() as it is replaced by upgrade()

- Sets
    - Now that it is deduplicated, adding the same set more than once will not pull it fully from the Rebrickable API (minifigures and parts)
    - Make RebrickableSet extend BrickRecord since it is now an item in database
    - Make BrickSet extend RebrickableSet now that RebrickableSet is a proper database item

### UI

- Checkboxes
    - Possibility to hide the checkbox in the grid ("Sets") but sill have all them in the set details
    - Management

- Database
    - Migration tool

- Javascript
    - Generic BrickChanger class to handle quick modification through a JSON request with a visual feedback indicator
    - Simplify the way javascript scripts are loaded and instantiated

- Set grid
    - Filter by checkboxes and NOT checkboxes

- Tables
    - Fix table search looking inside links pills

- Wishlist
    - Add Rebrickable link badge for sets (@matthew)

## 1.0.0: New Year revamp

### Code

- Authentication
    - Basic authentication mechanism with ONE password to protect admin and writes
- CSV
    - Remove dependencies to numpy and panda for simpler built-in csv
- Code
    - Refactored the Python code
    - Modularity (more functions, splitting files)
    - Type hinting whenever possible
    - Flake8 linter
    - Retained most of the original behaviour (with its quirks)
- Colors
    - Remove dependency on color.csv
- Configuration
    - Moved all the hard-coded parameters into configuration variables
    - Most of the variables are configuration through environment variables
    - Force instruction, sets, etc path to be relative to static
- Docker
    - Added an entrypoint to grab PORT / HOST from the environment if set
    - Remove the need to seed the container with files (*.csv, nil files)
- Flask
    - Fix improper socketio.run(app.run()) call which lead to hard crash on ^C
    - Make use of url_for to create URLs
    - Use blueprints to implement routes
    - Move views into their own files
    - Split GET and POST methods into two different routes for clarity
- Images
    - Add an option to use remote images from the Rebrickable CDN rather than downloading everything locally
    - Handle nil.png and nil_mf.jpg as true images in /static/sets/ so that they are downloaded whenever necessary when importing a se with missing images
- Instructions
    - Scan the files once for the whole app, and re-use the data
    - Refresh the instructions from the admin
    - More lenient set number detection
    - Update when uploading a new one
    - Basic file management
- Logs
    - Added log lines for change actions (add, check, missing, delete) so that the server is not silent when DEBUG=false
- Minifigures
    - Added a variable to control default ordering
- Part(s)
    - Added a variable to control default ordering of listing
- Retired sets
    - Open the themes once for the whole app, and re-use the data
    - Do not hard fail if themes.csv is missing, simply display the IDs
    - Light management: resync, download
- Set(s)
    - Reworked the set checkboxes with a dedicated route per status
    - Switch from homemade ID generator to proven UUID4 for sets ID
        - Does not interfere with previously created sets
    - Do not rely on sets.csv to check if the set exists
    - When adding, commit the set to database only once everything has been processed
    - Added a bulk add page
    - Keep spare parts when importing
    - Added a variable to control default ordering of listing
- Socket
    - Make use of socket.io rooms to avoid broadcasting messages to all clients
- SQLite
    - Do not hard fail if the database is not present or not initialized
    - Open the database once for the context, and re-use the connection
    - Move queries to .sql files and load them as Jinja templates
    - Use named arguments rather than sets for SQLite queries
    - Allow execute() to be deferred to the commit() call to avoid locking the database for long period while importing (locked while downloading images)
- Themes
    - Open the themes once for the whole app, and re-use the data
    - Do not hard fail if themes.csv is missing, simply display the IDs
    - Light management: resync, download

### UI

- Admin
    - Initialize the database from the web interface
    - Reset the database
    - Delete the database
    - Download the database
    - Import the database
    - Display the configuration variables
    - Many things
- Accordions
    - Added a flag to make the accordion items independent
- Branding:
    - Add a brick as a logo (CC0 image from: https://iconduck.com/icons/71631/brick)
- Global
    - Redesign of the whole app
    - Sticky menu bar on top of the page
    - Execution time and SQL stats for fun
- Libraries
    - Switch from Bulma to Bootstrap, arbitrarily :D
    - Use of baguettebox for images (https://github.com/feimosi/baguetteBox.js)
    - Use of tinysort to sort and filter the grid (https://github.com/Sjeiti/TinySort)
    - Use of sortable for set card tables (https://github.com/tofsjonas/sortable)
    - Use of simple-datatables for big tables (https://github.com/fiduswriter/simple-datatables)
- Minifigures
    - Added a detail view for a minifigure
    - Display which sets are using a minifigure
    - Display which sets are missing a minifigure
- Parts
    - Added a detail view for a part
    - Display which sets are using a part
    - Display which sets are missing a part
- Templates
    - Use a common base template
    - Use HTML fragments/macros for repeted or parametrics items
    - a 404 page for wrong URLs
    - an error page for expected error messages
    - an exception page for unexpected error messages
- Set add
    - Two-tiered (with override) import where you see what you will import before importing it
    - Add a visual indicator that the socket is connected
- Set card
    - Badges to display info like theme, year, parts, etc
    - Set image on top of the card, filling the space
    - Trick to have a blurry background image fill the void in the card
    - Save missing parts on input change rather than by clicking
        - Visual feedback of success
    - Parts and minifigure in accordions
    - Instructions file list
- Set grid
    - 4-2-1 card distribution depending on screen size
    - Display the index with no set added, rather than redirecting
    - Keep last sort in a cookie, and trigger it on page load (can be cleared)
