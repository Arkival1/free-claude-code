import SwiftUI
import UIKit
import WebKit

/// The web view FCC Phone runs in. FCC's site is an app-bound domain, so its
/// service worker keeps it working offline and its data (chats, projects,
/// models) stays in the app. Other sites open in Safari, downloads are saved
/// and shared, and the camera and microphone work for photos and voice.
struct FCCWebView: UIViewRepresentable {
    static let home = URL(string: "https://arkival1.github.io/free-claude-code/phone/")!
    static let ownHosts: Set<String> = ["arkival1.github.io"]

    let start: URL

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.limitsNavigationsToAppBoundDomains = true
        config.websiteDataStore = .default()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        // FCC can tell it runs in the app (the FCC Engine plugs in here later).
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1"
        let hello = "window.fccApp = Object.freeze({ native: true, platform: 'ios', version: '\(version)' });"
        config.userContentController.addUserScript(
            WKUserScript(source: hello, injectionTime: .atDocumentStart, forMainFrameOnly: true)
        )

        let web = WKWebView(frame: .zero, configuration: config)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = false
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.isOpaque = false
        web.backgroundColor = .clear
        if #available(iOS 16.4, *) { web.isInspectable = true }
        context.coordinator.web = web
        web.load(URLRequest(url: start))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
        weak var web: WKWebView?
        private var saved: [WKDownload: URL] = [:]

        private static func isOwn(_ url: URL?) -> Bool {
            guard let url else { return false }
            if ["about", "blob", "data"].contains(url.scheme ?? "") { return true }
            return FCCWebView.ownHosts.contains(url.host ?? "")
        }

        // MARK: Navigation

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if action.shouldPerformDownload {
                decisionHandler(.download)
                return
            }
            let url = action.request.url
            // Frames inside FCC (previews, games) stay; other sites and app
            // links (shortcuts://, mailto:) go to Safari or their app.
            if Self.isOwn(url) || action.targetFrame?.isMainFrame == false {
                decisionHandler(.allow)
                return
            }
            if let url { UIApplication.shared.open(url) }
            decisionHandler(.cancel)
        }

        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                     decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            decisionHandler(response.canShowMIMEType ? .allow : .download)
        }

        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
            download.delegate = self
        }

        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
            download.delegate = self
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showOffline(webView, error)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            if (error as NSError).code != NSURLErrorCancelled { showOffline(webView, error) }
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            // iOS closed the page (usually memory): open FCC again.
            webView.load(URLRequest(url: FCCWebView.home))
        }

        private func showOffline(_ webView: WKWebView, _ error: Error) {
            let html = """
            <!doctype html><meta name="viewport" content="width=device-width, initial-scale=1">
            <body style="font-family:-apple-system;padding:48px 24px;background:#f6f4ef;color:#1b1a17">
            <h2>FCC couldn't open</h2><p>Connect to the internet once so FCC can keep itself on this phone.</p>
            <p style="color:#6b675e">\(error.localizedDescription)</p>
            <button style="font-size:17px;padding:12px 20px;border-radius:12px;border:0;background:#1b1a17;color:#fff"
             onclick="location.href='\(FCCWebView.home.absoluteString)'">Try again</button></body>
            """
            webView.loadHTMLString(html, baseURL: FCCWebView.home)
        }

        // MARK: Windows, dialogs, camera and microphone

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            // target="_blank": FCC's pages in this view, everything else in Safari.
            if let url = action.request.url {
                if Self.isOwn(url) { webView.load(action.request) } else { UIApplication.shared.open(url) }
            }
            return nil
        }

        func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin,
                     initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType,
                     decisionHandler: @escaping (WKPermissionDecision) -> Void) {
            decisionHandler(FCCWebView.ownHosts.contains(origin.host) ? .grant : .prompt)
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler() })
            present(alert, orElse: completionHandler)
        }

        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String,
                     initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
            let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(false) })
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in completionHandler(true) })
            present(alert) { completionHandler(false) }
        }

        func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String,
                     defaultText: String?, initiatedByFrame frame: WKFrameInfo,
                     completionHandler: @escaping (String?) -> Void) {
            let alert = UIAlertController(title: nil, message: prompt, preferredStyle: .alert)
            alert.addTextField { $0.text = defaultText }
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel) { _ in completionHandler(nil) })
            alert.addAction(UIAlertAction(title: "OK", style: .default) { _ in
                completionHandler(alert.textFields?.first?.text)
            })
            present(alert) { completionHandler(nil) }
        }

        private func present(_ controller: UIViewController, orElse fallback: @escaping () -> Void) {
            guard let top = Self.topController() else { fallback(); return }
            top.present(controller, animated: true)
        }

        private static func topController() -> UIViewController? {
            let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
            var top = scene?.windows.first(where: { $0.isKeyWindow })?.rootViewController
            while let next = top?.presentedViewController { top = next }
            return top
        }

        // MARK: Downloads (zips, projects, backups): saved, then shared

        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                      suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
            let folder = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            var target = folder.appendingPathComponent(suggestedFilename.isEmpty ? "download" : suggestedFilename)
            var n = 2
            while FileManager.default.fileExists(atPath: target.path) {
                let base = (suggestedFilename as NSString).deletingPathExtension
                let ext = (suggestedFilename as NSString).pathExtension
                target = folder.appendingPathComponent(ext.isEmpty ? "\(base) \(n)" : "\(base) \(n).\(ext)")
                n += 1
            }
            saved[download] = target
            completionHandler(target)
        }

        func downloadDidFinish(_ download: WKDownload) {
            guard let file = saved.removeValue(forKey: download) else { return }
            let share = UIActivityViewController(activityItems: [file], applicationActivities: nil)
            if let top = Self.topController() {
                share.popoverPresentationController?.sourceView = top.view
                top.present(share, animated: true)
            }
        }

        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            saved.removeValue(forKey: download)
        }
    }
}
