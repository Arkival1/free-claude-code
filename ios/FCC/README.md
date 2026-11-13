# FCC for iPhone

FCC Phone as its own iPhone app: full screen, its own icon, not in Safari.
It opens FCC's site (https://arkival1.github.io/free-claude-code/phone/),
keeps it working offline, and saves its data in the app. Other sites open in
Safari; downloads (projects, zips, backups) are saved and can be shared or
put in Files; the camera and microphone work for photos and voice. FCC can
tell it is in the app (`window.fccApp`), which is where the FCC Engine (the
on-phone AI, like Ollama) plugs in next.

## Get it on your iPhone (free Apple ID)

1. On GitHub: Actions → **FCC iPhone app** → the newest green run →
   Artifacts → **FCC-iPhone-app**. Unzip it to get `FCC.ipa`.
2. On your Windows PC install **Sideloadly** (sideloadly.io) and iTunes
   (from Apple's site, not the Microsoft Store version) so Windows sees the
   iPhone. Plug the iPhone in with a cable and tap Trust.
3. Open Sideloadly, drop `FCC.ipa` in, type your Apple ID, Start.
4. On the iPhone: Settings → General → VPN & Device Management → your Apple
   ID → Trust. On iOS 16+ also turn on Settings → Privacy & Security →
   Developer Mode (the phone restarts).
5. Open **FCC**. With a free Apple ID it needs installing again every 7
   days (Sideloadly can refresh it); a paid Apple developer account makes it
   last a year.

## Your data

The app keeps its own copy of FCC's data, separate from Safari's. To bring
your chats, projects and settings across: in Safari, More → Settings →
Backup → **Save a backup** (keep the file in Files); in the app, More →
Settings → Backup → **Restore a backup** and pick that file.

## How it's built

`project.yml` is the Xcode project for XcodeGen; GitHub's Mac
(`.github/workflows/fcc-ios-app.yml`) generates it, builds FCC.app
unsigned and packs FCC.ipa. No Mac needed here. Code: `Sources/FCCApp.swift`
(the app) and `Sources/FCCWebView.swift` (the web view: offline, links,
downloads, camera and microphone, alerts).
