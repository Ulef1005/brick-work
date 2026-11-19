/* Register only on the Toni track, on secure origins (localhost included). */
(() => {
 const manifest = document.querySelector('link[rel=manifest]');
 if (!manifest) return;
 function themeManifest() {
  const dark = window.adminTheme.mode === 'dark' || (window.adminTheme.mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  document.querySelectorAll('meta[name="theme-color"]').forEach(meta => {
   meta.content = window.adminTheme.mode === 'system' ? (meta.media.includes('dark') ? '#1F2322' : '#F8F8F6') : (dark ? '#1F2322' : '#F8F8F6');
  });
  manifest.href = '/manifest.webmanifest' + (dark ? '?theme=dark' : '');
 }
 document.addEventListener('admin-theme', themeManifest); themeManifest();
 if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js', {scope:'/'}).catch(() => {});
})();
