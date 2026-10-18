
<section class="layout-115">
<span class="layout-19">Use cases</span>
<h1 class="layout-116">Eight moments a collector knows.</h1>
<p class="layout-117">Each case says what you have in front of you, what you do, and which part of the app does it.</p>
<div class="layout-118">
<a class="layout-119" href="#uc-table">At the table<span class="layout-120">3</span></a>
<a class="layout-119" href="#uc-plan">Planning and keeping<span class="layout-120">3</span></a>
<a class="layout-119" href="#uc-scripts">Scripts and assistants<span class="layout-120">2</span></a>
</div>
</section>
<section class="at-the-table layout-121" id="uc-table">
<div class="layout-122">
<h2 class="layout-105">At the table</h2>
<span class="layout-55">Sets, parts and bags in front of you.</span>
</div>
<div class="layout-123">
<article class="layout-124">
<div class="layout-125">
<picture class="layout-126"><source media="(prefers-color-scheme: dark)" srcset="../assets/img/3e-finish-gaps-phone-390-dark.png"/><img alt="Finish the set you started" decoding="async" height="1688" loading="lazy" src="../assets/img/3e-finish-gaps-phone-390-light.png" width="780"/></picture>
</div>
<div class="layout-127">
<h3 class="layout-39">Finish the set you started</h3>
<p class="layout-128">You built half a set years ago and do not know what is missing.</p>
<p class="layout-129">Open the copy and run Check Set Parts against its inventory. The shortfall becomes a list you can act on, with a count of how far along the copy is.</p>
<div class="layout-130">
<span class="layout-49">Check Set Parts</span>
</div>
<a class="layout-131" href="../workflows/#check-set-parts">Walk through Check Set Parts</a>
</div>
</article>
<article class="layout-124">
<div class="layout-125">
<picture class="layout-126"><source media="(prefers-color-scheme: dark)" srcset="../assets/img/3c-picker-sets-phone-390-dark.png"/><img alt="Build from your bulk" decoding="async" height="1688" loading="lazy" src="../assets/img/3c-picker-sets-phone-390-light.png" width="780"/></picture>
</div>
<div class="layout-127">
<h3 class="layout-39">Build from your bulk</h3>
<p class="layout-128">Boxes of sorted loose parts, and several unfinished sets.</p>
<p class="layout-129">Part Picker lists the missing parts you can pull for the sets you tick, in your sort order, so one pass through the drawers serves many sets. Matcher shows which copies your stock finishes outright.</p>
<div class="layout-130">
<span class="layout-49">Part Picker</span>
<span class="layout-49">Matcher</span>
</div>
<a class="layout-131" href="../workflows/#part-picker">Walk through Part Picker</a>
</div>
</article>
<article class="layout-124">

<div class="layout-127">
<h3 class="layout-39">Receive a parts order</h3>
<p class="layout-128">A BrickLink order arrives.</p>
<p class="layout-129">Import it from your account, paste the confirmation email or upload the order XML; a line already imported is never added twice. Count what comes out of the bag and allocate it to the sets that need it.</p>
<div class="layout-130">
<span class="layout-49">Orders</span>
</div>
</div>
</article>
</div>
</section>
<section class="planning-and-keeping layout-121" id="uc-plan">
<div class="layout-122">
<h2 class="layout-105">Planning and keeping</h2>
<span class="layout-55">What to buy, and one place for everything.</span>
</div>
<div class="layout-123">
<article class="layout-124">
<div class="layout-125">
<picture class="layout-126"><source media="(prefers-color-scheme: dark)" srcset="../assets/img/4c-complete-sets-phone-390-dark.png"/><img alt="Decide what to buy" decoding="async" height="1688" loading="lazy" src="../assets/img/4c-complete-sets-phone-390-light.png" width="780"/></picture>
</div>
<div class="layout-127">
<h3 class="layout-39">Decide what to buy</h3>
<p class="layout-128">Several sets are short. Which are worth finishing?</p>
<p class="layout-129">Wishlist, Prices and Complete sets rank repairs by value gained per euro. Part-out values show only when at least 90% of a set’s lines have a price; one action fetches the missing prices.</p>
<div class="layout-130">
<span class="layout-49">Wishlist</span>
<span class="layout-49">Prices</span>
<span class="layout-49">Complete sets</span>
</div>
</div>
</article>
<article class="layout-124">
<div class="layout-125">
<picture class="layout-132"><source media="(prefers-color-scheme: dark)" srcset="../assets/img/12c-list-and-detail-desktop-1440-dark.png"/><img alt="Know where everything is" decoding="async" height="900" loading="lazy" src="../assets/img/12c-list-and-detail-desktop-1440-light.png" width="1440"/></picture>
</div>
<div class="layout-127">
<h3 class="layout-39">Know where everything is</h3>
<p class="layout-128">A set is broken down into bags. Which box is it in?</p>
<p class="layout-129">Every set, copy, part and box has a storage location. Look up a part and see how many you have and where they are.</p>
<div class="layout-130">
<span class="layout-49">Storage</span>
</div>
</div>
</article>
<article class="layout-124">
<div class="layout-125">
<pre class="layout-133">$ brickwork migrate

Read-only import
Row counts and checksums match
Old database unchanged</pre>
</div>
<div class="layout-127">
<h3 class="layout-39">Bring your old collection over</h3>
<p class="layout-128">Your collection lives in another tracker.</p>
<p class="layout-129">Run the read-only importer on the old database, review the row-count and checksum proof, then point Brick Work at the new database. The old one is never changed.</p>
<div class="layout-130">
<span class="layout-49">CLI</span>
</div>
<a class="layout-131" href="../docs/">Migration guide</a>
</div>
</article>
</div>
</section>
<section class="scripts-and-assistants layout-121" id="uc-scripts">
<div class="layout-122">
<h2 class="layout-105">Scripts and assistants</h2>
<span class="layout-55">The same collection, from code or a conversation.</span>
</div>
<div class="layout-123">
<article class="layout-124">
<div class="layout-125">
<div class="layout-134">
<div class="layout-64">What is stored in box 3?</div>
<div class="layout-135">Box 3 holds two instructions and the box of 2260-1 Ice Dragon Attack.</div>
<span class="layout-67">Read-only token · illustrative</span>
</div>
</div>
<div class="layout-127">
<h3 class="layout-39">Ask an assistant about your collection</h3>
<p class="layout-128">You want an answer without opening the app.</p>
<p class="layout-129">Connect an assistant over MCP and ask which sets are closest to complete or what is stored in a box. It reads with a read-only token; write tools stay off unless you enable them, and every change gets an Undo link.</p>
<div class="layout-130">
<span class="layout-49">MCP</span>
</div>
<a class="layout-131" href="../mcp/">MCP guide</a>
</div>
</article>
<article class="layout-124">
<div class="layout-125">
<pre class="layout-133">$ docker compose exec brickwork \
    brickwork token create \
    --name export --scope read</pre>
</div>
<div class="layout-127">
<h3 class="layout-39">Script your collection</h3>
<p class="layout-128">You want a spreadsheet export, or sets added from a script.</p>
<p class="layout-129">Hook the collection into your own tools with the versioned REST API. Creates need an idempotency key, so a retried request cannot add twice.</p>
<div class="layout-130">
<span class="layout-49">REST API</span>
<span class="layout-49">OpenAPI</span>
</div>
<a class="layout-131" href="../api/">API reference</a>
</div>
</article>
</div>
</section>
<section class="not-here-yet layout-69">
<div class="layout-136">
<div class="layout-137">
<span class="layout-113">Planned</span>
<span class="layout-32">Buildable sets, collection sync with Rebrickable, BrickLink and Brickset, and a pile check by photo are planned and not built.</span>
</div>
<a class="layout-138" href="https://github.com/users/Ulef1005/projects/3">Public roadmap</a>
</div>
</section>
