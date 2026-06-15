import AppKit

private let projectRootResourceName = "project-root"

enum GatewayMode: String {
    case openai
    case hybrid
    case forward
    case unknown

    var displayName: String {
        switch self {
        case .openai: return "OpenAI 代理"
        case .hybrid: return "混合模式"
        case .forward: return "官方直连"
        case .unknown: return "未知"
        }
    }

    var statusSymbolName: String {
        switch self {
        case .openai: return "arrow.triangle.2.circlepath.circle.fill"
        case .hybrid: return "arrow.triangle.branch"
        case .forward: return "bolt.circle.fill"
        case .unknown: return "questionmark.circle.fill"
        }
    }
}

final class KiroGatewayMenuApp: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem?
    private let menu = NSMenu()
    private var currentMode: GatewayMode = .unknown
    private var dockerStatus: String = "unknown"
    private var statusText: String = "读取中..."

    private var projectPath: String {
        if let saved = UserDefaults.standard.string(forKey: "projectPath"), !saved.isEmpty {
            return NSString(string: saved).expandingTildeInPath
        }
        if let bundled = bundledProjectPath() {
            return bundled
        }
        if let inferred = inferredProjectPathFromBundle() {
            return inferred
        }
        return FileManager.default.currentDirectoryPath
    }

    private func bundledProjectPath() -> String? {
        guard let url = Bundle.main.url(forResource: projectRootResourceName, withExtension: "txt"),
              let text = try? String(contentsOf: url, encoding: .utf8) else {
            return nil
        }
        let path = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if path.isEmpty {
            return nil
        }
        return NSString(string: path).expandingTildeInPath
    }

    private func inferredProjectPathFromBundle() -> String? {
        var url = Bundle.main.bundleURL
        for _ in 0..<4 {
            url.deleteLastPathComponent()
        }
        let statusScript = url.appendingPathComponent("scripts/gateway-status.sh").path
        if FileManager.default.fileExists(atPath: statusScript) {
            return url.path
        }
        return nil
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        NSApp.disableRelaunchOnLogin()
        createStatusItem()
        rebuildMenu()
        refreshStatus(nil)
    }

    private func createStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem = item
        item.isVisible = true
        item.menu = menu
        setMenuBarIcon(symbolName: "bolt.horizontal.circle.fill", tooltip: "Kiro Gateway 模式切换")
    }

    private func rebuildMenu() {
        menu.removeAllItems()

        let statusMenuItem = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        menu.addItem(statusMenuItem)
        menu.addItem(NSMenuItem.separator())

        let modeItem = NSMenuItem(title: "模式", action: nil, keyEquivalent: "")
        let modeSubmenu = NSMenu(title: "模式")
        modeSubmenu.addItem(makeModeItem(title: "OpenAI 代理", mode: .openai, action: #selector(useOpenAIProxy)))
        modeSubmenu.addItem(makeModeItem(title: "混合模式", mode: .hybrid, action: #selector(useHybridMode)))
        modeSubmenu.addItem(makeModeItem(title: "官方直连", mode: .forward, action: #selector(useForwardMode)))
        modeItem.submenu = modeSubmenu
        menu.addItem(modeItem)

        menu.addItem(NSMenuItem(title: "重启 Docker 服务", action: #selector(restartDocker), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())

        menu.addItem(NSMenuItem(title: "刷新状态", action: #selector(refreshStatus), keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())

        let pathItem = NSMenuItem(title: "项目: \(projectPath)", action: nil, keyEquivalent: "")
        pathItem.isEnabled = false
        menu.addItem(pathItem)
        menu.addItem(NSMenuItem(title: "退出", action: #selector(quit), keyEquivalent: "q"))
    }

    private func makeModeItem(title: String, mode: GatewayMode, action: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        item.state = currentMode == mode ? .on : .off
        return item
    }

    @objc private func useOpenAIProxy() {
        runProjectScript("./scripts/mode-openai.sh && ./scripts/restart-docker.sh", successTitle: "已切换到 OpenAI 代理模式")
    }

    @objc private func useHybridMode() {
        runProjectScript("./scripts/mode-hybrid.sh && ./scripts/restart-docker.sh", successTitle: "已切换到混合模式")
    }

    @objc private func useForwardMode() {
        runProjectScript("./scripts/mode-forward.sh && ./scripts/restart-docker.sh", successTitle: "已切换到官方直连模式")
    }

    @objc private func restartDocker() {
        runProjectScript("./scripts/restart-docker.sh", successTitle: "Docker 服务已重启")
    }

    @objc private func refreshStatus(_ sender: Any?) {
        let result = Shell.run("cd \(Shell.quote(projectPath)) && ./scripts/gateway-status.sh")
        if result.exitCode == 0 {
            let parsed = parseStatus(result.output)
            currentMode = GatewayMode(rawValue: parsed["MODE"] ?? "") ?? .unknown
            dockerStatus = parsed["DOCKER"] ?? "unknown"
            statusText = "当前模式: \(currentMode.displayName) / Docker: \(dockerStatus)"
            setMenuBarIcon(symbolName: currentMode.statusSymbolName, tooltip: statusText)
        } else {
            currentMode = .unknown
            statusText = "状态读取失败"
            setMenuBarIcon(symbolName: "exclamationmark.triangle.fill", tooltip: "Kiro Gateway 状态读取失败")
        }
        rebuildMenu()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func runProjectScript(_ command: String, successTitle: String) {
        setMenuBarIcon(symbolName: "hourglass", tooltip: "Kiro Gateway 正在切换模式")
        let result = Shell.run("cd \(Shell.quote(projectPath)) && \(command)")
        if result.exitCode != 0 {
            showAlert(title: "操作失败", message: tail(result.output + "\n" + result.error))
        }
        refreshStatus(nil)
    }

    private func setMenuBarIcon(symbolName: String, tooltip: String) {
        guard let button = statusItem?.button else { return }
        button.title = ""
        button.toolTip = tooltip
        if let image = NSImage(systemSymbolName: symbolName, accessibilityDescription: tooltip) {
            image.isTemplate = true
            image.size = NSSize(width: 18, height: 18)
            button.image = image
            button.imagePosition = .imageOnly
        }
    }

    private func parseStatus(_ text: String) -> [String: String] {
        var values: [String: String] = [:]
        for line in text.split(separator: "\n") {
            let parts = line.split(separator: "=", maxSplits: 1).map(String.init)
            if parts.count == 2 {
                values[parts[0]] = parts[1]
            }
        }
        return values
    }

    private func tail(_ text: String, maxLength: Int = 1600) -> String {
        if text.count <= maxLength { return text.trimmingCharacters(in: .whitespacesAndNewlines) }
        return String(text.suffix(maxLength)).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func showAlert(title: String, message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = title
            alert.informativeText = message.isEmpty ? "完成" : message
            alert.alertStyle = title.contains("失败") ? .warning : .informational
            alert.runModal()
        }
    }

}

struct ShellResult {
    let exitCode: Int32
    let output: String
    let error: String
}

enum Shell {
    static func run(_ command: String) -> ShellResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = ["-lc", command]

        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        do {
            try process.run()
            process.waitUntilExit()
            let output = String(data: outputPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            let error = String(data: errorPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            return ShellResult(exitCode: process.terminationStatus, output: output, error: error)
        } catch {
            return ShellResult(exitCode: 1, output: "", error: error.localizedDescription)
        }
    }

    static func quote(_ text: String) -> String {
        "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

let application = NSApplication.shared
let applicationDelegate = KiroGatewayMenuApp()
application.delegate = applicationDelegate
application.setActivationPolicy(.accessory)
application.run()
