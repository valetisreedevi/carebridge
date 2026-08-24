/*
 * Background notifications for a paired phone.
 *
 * A service worker is not part of the Vite bundle and cannot read
 * import.meta.env, so the page hands it the Firebase config in this file's
 * query string when it registers. A changed config means a changed URL, which
 * is what makes the browser fetch and install the new worker.
 *
 * Without firebase.messaging() initialised here, an arriving push is not
 * handled by anything and Chrome shows its own "site updated in the
 * background" notice instead of the medicine.
 */
importScripts("https://www.gstatic.com/firebasejs/12.18.0/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/12.18.0/firebase-messaging-compat.js");

const config = Object.fromEntries(new URL(self.location.href).searchParams);

if (config.apiKey && config.projectId && config.messagingSenderId && config.appId) {
  firebase.initializeApp(config);
  firebase.messaging();
}

/*
 * Tapping a reminder should land on the medicine, not open a second copy of
 * the app beside the one already sitting on the side table.
 */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clients) => {
        const open = clients.find((client) => client.url.includes("/elder"));
        if (open) return open.focus();
        return self.clients.openWindow("/elder");
      }),
  );
});
