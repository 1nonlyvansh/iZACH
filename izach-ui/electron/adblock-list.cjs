// Curated ad/tracker domain blocklist for the in-app Browser widget only.
// Matched by hostname suffix (e.g. "doubleclick.net" blocks "ad.doubleclick.net" too).
// This is intentionally scoped to the browser's own session partition — it never
// touches iZACH's own backend/API traffic (see main.cjs's 'persist:izach-browser').
module.exports = [
  // Google ads/analytics
  'doubleclick.net', 'googlesyndication.com', 'googleadservices.com',
  'google-analytics.com', 'googletagmanager.com', 'googletagservices.com',
  'adservice.google.com', 'pagead2.googlesyndication.com',
  // Facebook/Meta tracking
  'connect.facebook.net', 'facebook.com/tr',
  // Amazon ads
  'amazon-adsystem.com',
  // Analytics/tracking services
  'scorecardresearch.com', 'quantserve.com', 'hotjar.com', 'mixpanel.com',
  'segment.io', 'segment.com', 'mouseflow.com', 'crazyegg.com',
  'newrelic.com', 'nr-data.net', 'fullstory.com',
  // Ad networks
  'outbrain.com', 'taboola.com', 'criteo.com', 'criteo.net', 'adnxs.com',
  'moatads.com', 'adsrvr.org', 'rubiconproject.com', 'pubmatic.com',
  'openx.net', 'casalemedia.com', 'contextweb.com', 'bidswitch.net',
  'advertising.com', 'adform.net', 'media.net', 'yieldmo.com',
];
