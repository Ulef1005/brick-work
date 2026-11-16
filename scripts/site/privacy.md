<!-- Google paragraph added 16.11. (GTM + GA4, cookieless, no banner: Ulf's decision); wording approved by the owner, 16.11. -->
<!-- Copy approved by the owner, 13.11. Clarity paragraph added 14.11. at the owner's decision (no consent banner); wording approved by the owner, 14.11. -->
# Privacy

This website shows no consent banner. It uses three analytics services on the marketing pages, one of them with cookies. What it loads:

- **Cloudflare** serves this site and sees the traffic as a proxy.
- **Cloudflare Web Analytics**, cookieless, on the marketing pages only.
- **Microsoft Clarity** on the marketing pages, the not-found page and the redirect pages from old addresses: it sets the cookies `_clck` and `_clsk`, keeps identifiers in your browser's local storage and records how you use the page (clicks, scrolling, page views) as pseudonymised session replays and heatmaps, processed by Microsoft. See [Microsoft's privacy statement](https://privacy.microsoft.com/privacystatement). The documentation and the demo pages do not load it. To avoid it, block `clarity.ms` in your browser; deleting the cookies alone does not stop it.
- **Google Tag Manager and Google Analytics** on the same pages: the tag manager loads with every consent signal set to denied, so Google Analytics measures page views without setting cookies or storing identifiers in your browser. Google still receives the page address, your browser's user agent and your IP address, processed by Google; no advertising features are used. The documentation and the demo pages do not load it. To avoid it, block `googletagmanager.com` and `google-analytics.com` in your browser.
- **YouTube** loads only after you press play on the tour; its own cookies and policy apply after that.
- **Pictures** of the demo's sets come from Rebrickable and are served from this site, so your browser does not contact Rebrickable.

The Brick Work app itself has no telemetry and runs on your own machine.

Questions: open a [GitHub Discussion](https://github.com/{repository}/discussions) or an [issue](https://github.com/{repository}/issues).
