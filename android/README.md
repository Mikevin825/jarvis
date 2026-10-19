# JARVIS for Android

A real, installable APK. Built with the Android SDK tools directly — no Gradle,
no Android Studio, no network access at build time.

## Build it

```bash
cd ~/jarvis
./build-apk.sh
```

Output: `~/jarvis/JARVIS.apk` (~36 KB), signed and ready to install.

The build uses the toolchain already on this machine
(`~/Android/Sdk/build-tools/36.0.0`) and runs the four steps the SDK tools do:

| Step | Tool | Produces |
|---|---|---|
| compile resources | `aapt2 compile` | `res.zip` |
| link + R.java | `aapt2 link` | `base.apk`, `R.java` |
| compile Java | `javac` (against `android.jar`) | `.class` files |
| dex | `d8` | `classes.dex` |
| package | `zip` + `zipalign` | unsigned APK |
| sign | `apksigner` | `JARVIS.apk` |

The signing key is generated on first build and lives in
`build/jarvis.keystore` (password `jarvisdebug`). Keep it — Android refuses to
update an app whose signature changed, so a lost key means uninstall/reinstall.

## Install it

**Option A — over USB** (recommended):

```bash
# On the phone: Settings → About → tap Build number 7×, then
#               Developer options → USB debugging ON
adb install -r ~/jarvis/JARVIS.apk
```

**Option B — no cable:** copy `JARVIS.apk` to the phone (email it to yourself,
or serve it: `cd ~/jarvis && .venv/bin/python -m http.server 8080`), tap it in
the Files app, and allow "Install unknown apps" for whichever app opens it.

## Use it

1. On the computer: `./jarvis-mobile` — note the URL and token it prints.
2. Open the JARVIS app. If it cannot reach the server, **tap the screen** and
   enter the server address (e.g. `192.168.1.33:8794`).
3. Paste the pairing token when the app asks.
4. That's it — the token is remembered by the WebView.

The server address is also in the app's menu (⋮ → "Server address"), so you can
re-point the app whenever your computer's IP changes.

## What the APK actually is

A deliberately thin native shell around the same web app the PWA serves:

- a `WebView` with JavaScript and DOM storage on (so the pairing token persists),
- a microphone permission handler, so voice input works,
- a native "cannot reach JARVIS" screen with a tap-to-fix address dialog,
- a real launcher icon, at five densities, and a proper app entry.

**All conversation logic stays on the server.** The APK contains no brain, no
API keys, and no tool code — it is a window onto JARVIS, not a copy of it. That
keeps one brain serving the terminal, the desktop, the PWA and the phone.

## Rebuilding after a change

Only rebuild the APK when the *shell* changes (Java, manifest, icon). Changes to
JARVIS itself — prompts, tools, personality, config — need no rebuild; the app
picks them up the next time it talks to the server.
