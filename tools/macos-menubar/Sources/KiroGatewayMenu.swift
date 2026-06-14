import AppKit

private let defaultProjectPath = "~/CliProject/kiro-reversed-gateway"

@main
final class KiroGatewayMenuApp: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private var projectPath: String {
        let saved = UserDefaults.standard.string(forKey: "projectPath") ?? defaultProjectPath
        return NSString(string: saved).expandingTildeInPath
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "Kiro"
        statusItem.menu = menu
        rebuildMenu(statusText: "读取中…")
        refreshStatus(nil)
    }

    private func rebuildMenu(statusText: String) {
        menu.removeAllItems()

        let statusItem = NSMenuItem(title: statusText, action: nil, keyEquivalent: "")
        statusItem.isEnabled = false
        menu.addItem(statusItem)
        menu.addItem(NSMenuItem.separator())

        menu.addItem(NSMenuItem(title: "切换到 OpenAI 代理模式", action: #selector(useOpenAIProxy), keyEquivalent: "o"))
        menu.addItem(NSMenuItem(title: "切换到官方直连模式", action: #selector(useForwardMode), keyEquivalent: "f"))
        menu.addItem(NSMenuItem(title: "重启 Docker 服务", action: #selector(restartDocker), keyEquivalent: "r"))
        menu.addItem(NSMenuItem.separator())

        menu.addItem(NSMenuItem(title: "刷新状态", action: #selector(refreshStatus), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "打开项目目录", action: #selector(openProject), keyEquivalent: ""))
        menu.addItem(NSMenuItem(title: "查看 Docker 日志", action: #selector(openDockerLogs), keyEquivalent: "l"))
        menu.addItem(NSMenuItem.separator())

        let pathItem = NSMenuItem(title: "项目: \(projectPath)", action: nil, keyEquivalent: "")
        pathItem.isEnabled = false
        menu.addItem(pathItem)
        menu.addItem(NSMenuItem(title: "退出", action: #selector(quit), keyEquivalent: "q"))
    }

    @objc private func useOpenAIProxy() {
        runProjectScript("./scripts/mode-openai.sh && ./scripts/restart-docker.sh", successTitle: "已切换到 OpenAI 代理模式")
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
            let mode = parsed["MODE"] ?? "unknown"
            let docker = parsed["DOCKER"] ?? "unknown"
            let modeLabel = mode == "forward" ? "官方直连" : (mode == "openai" ? "OpenAI 代理" : mode)
            let statusText = "当前: \(modeLabel) / Docker: \(docker)"
            statusItem.button?.title = mode == "forward" ? "官方直连" : "OpenAI代理"
            rebuildMenu(statusText: statusText)
        } else {
            statusItem.button?.title = "Kiro异常"

            rebuildMenu(statusText: "状态读取失败")
        }
    }

    @objc private func openProject() {
        NSWorkspace.shared.open(URL(fileURLWithPath: projectPath))
    }

    @objc private func openDockerLogs() {
        let command = "cd \(Shell.quote(projectPath)) && docker compose logs -f"
        let script = "tell application \"Terminal\" to do script \"\(escapeAppleScript(command))\""
        _ = Shell.run("osascript -e \(Shell.quote(script))")
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func runProjectScript(_ command: String, successTitle: String) {
        statusItem.button?.title = "切换中…"

        let result = Shell.run("cd \(Shell.quote(projectPath)) && \(command)")
        if result.exitCode == 0 {
            showAlert(title: successTitle, message: tail(result.output))
        } else {
            showAlert(title: "操作失败", message: tail(result.output + "\n" + result.error))
        }
        refreshStatus(nil)
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

    private func escapeAppleScript(_ text: String) -> String {
        text.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
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
