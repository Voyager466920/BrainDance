import AppKit
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var backend: Process?
    var backendOutput: Pipe?
    var serverURL: URL?
    var quitting = false
    var startupTimer: Timer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        makeMenu()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 820),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "BrainDance"
        window.minSize = NSSize(width: 760, height: 570)
        window.delegate = self
        window.backgroundColor = NSColor(calibratedRed: 0.067, green: 0.075, blue: 0.086, alpha: 1)
        window.center()
        let label = NSTextField(labelWithString: "BrainDance를 시작하고 있습니다…")
        label.textColor = .secondaryLabelColor
        label.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(label)
        NSLayoutConstraint.activate([label.centerXAnchor.constraint(equalTo: window.contentView!.centerXAnchor),
                                     label.centerYAnchor.constraint(equalTo: window.contentView!.centerYAnchor)])
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        let health = URL(string: "http://127.0.0.1:8766/api/health")!
        var request = URLRequest(url: health)
        request.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: request) { data, _, _ in
            let result = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            DispatchQueue.main.async {
                if result?["app"] as? String == "BrainDance" {
                    self.showWorkspace(URL(string: "http://127.0.0.1:8766/")!)
                } else { self.startBackend() }
            }
        }.resume()
    }

    func makeMenu() {
        let menu = NSMenu()
        let appItem = NSMenuItem(); menu.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        appMenu.addItem(withTitle: "BrainDance 정보", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "BrainDance 종료", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let editItem = NSMenuItem(); menu.addItem(editItem)
        let edit = NSMenu(title: "편집"); editItem.submenu = edit
        for (title, action, key) in [("실행 취소", "undo:", "z"), ("잘라내기", "cut:", "x"),
                                     ("복사", "copy:", "c"), ("붙여넣기", "paste:", "v"), ("전체 선택", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(action), keyEquivalent: key)
        }
        let viewItem = NSMenuItem(); menu.addItem(viewItem)
        let view = NSMenu(title: "보기"); viewItem.submenu = view
        let reload = NSMenuItem(title: "새로고침", action: #selector(reloadWorkspace), keyEquivalent: "r")
        reload.target = self; view.addItem(reload)
        NSApp.mainMenu = menu
    }

    func startBackend() {
        guard let executable = Bundle.main.url(forResource: "BrainDanceServer", withExtension: nil) else {
            fail("앱의 서버 파일을 찾을 수 없습니다."); return
        }
        do {
            let process = Process(), output = Pipe()
            process.executableURL = executable
            process.arguments = ["--port", "8766"]
            process.standardOutput = output
            let folder = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/BrainDance")
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
            let log = folder.appendingPathComponent("desktop.log")
            if !FileManager.default.fileExists(atPath: log.path) { FileManager.default.createFile(atPath: log.path, contents: nil) }
            let errorLog = try FileHandle(forWritingTo: log); try errorLog.seekToEnd()
            process.standardError = errorLog
            process.terminationHandler = { process in
                DispatchQueue.main.async {
                    if !self.quitting { self.fail("연구 서버가 종료되었습니다. 앱을 다시 실행해 주세요. (코드 \(process.terminationStatus))") }
                }
            }
            self.backend = process; self.backendOutput = output
            try process.run()
            startupTimer = Timer.scheduledTimer(withTimeInterval: 35, repeats: false) { _ in
                if self.serverURL == nil { self.fail("서버 시작 시간이 초과되었습니다. 앱 데이터 폴더의 desktop.log를 확인하세요.") }
            }
            DispatchQueue.global(qos: .userInitiated).async {
                var buffer = Data()
                while true {
                    let chunk = output.fileHandleForReading.availableData
                    if chunk.isEmpty { break }
                    buffer.append(chunk)
                    while let end = buffer.firstIndex(of: 10) {
                        let line = buffer.prefix(upTo: end); buffer.removeSubrange(...end)
                        guard let json = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                              json["app"] as? String == "BrainDance", let address = json["url"] as? String,
                              let url = URL(string: address), url.host == "127.0.0.1", url.scheme == "http" else { continue }
                        DispatchQueue.main.async { self.showWorkspace(url) }
                    }
                }
            }
        } catch { fail("서버를 시작하지 못했습니다: \(error.localizedDescription)") }
    }

    func showWorkspace(_ url: URL) {
        guard serverURL == nil, !quitting else { return }
        startupTimer?.invalidate(); serverURL = url
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        webView = WKWebView(frame: window.contentView!.bounds, configuration: configuration)
        webView.navigationDelegate = self; webView.uiDelegate = self
        webView.autoresizingMask = [.width, .height]
        webView.underPageBackgroundColor = window.backgroundColor
        window.contentView = webView
        webView.load(URLRequest(url: url))
    }

    @objc func reloadWorkspace() { webView?.reload() }
    func fail(_ message: String) {
        guard !quitting else { return }
        startupTimer?.invalidate()
        let alert = NSAlert(); alert.messageText = "BrainDance"; alert.informativeText = message
        alert.addButton(withTitle: "종료"); alert.runModal(); NSApp.terminate(nil)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        quitting = true; startupTimer?.invalidate()
        if let process = backend, process.isRunning { process.terminate() }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "http", url.host == "127.0.0.1", url.port == serverURL?.port {
            decisionHandler(.allow)
        } else {
            if action.navigationType == .linkActivated, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        return nil
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.setActivationPolicy(.regular)
application.delegate = delegate
application.run()
