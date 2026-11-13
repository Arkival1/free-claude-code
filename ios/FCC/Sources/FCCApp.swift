import SwiftUI

/// FCC for iPhone: FCC Phone in its own app, full screen, not in Safari.
/// The page itself handles the notch and home bar (viewport-fit=cover).
@main
struct FCCApp: App {
    var body: some Scene {
        WindowGroup {
            FCCWebView(start: FCCWebView.home)
                .ignoresSafeArea()
                .background(Color(red: 0.965, green: 0.957, blue: 0.937))
        }
    }
}
