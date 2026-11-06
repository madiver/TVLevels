import AppKit

struct Config: Decodable { let root: String; let python: String; let nodeDirectory: String; let mcpRoot: String }
struct Category: Decodable { let kind: String; let title: String; let label: String; let explanation: String; let appearance: String }
struct CategoryGroup: Decodable { let id: String; let title: String; let levels: [Category] }
struct StyleLegend: Decodable { let title: String; let explanation: String; let colors: [String]; let linestyle: Int }
struct Catalog: Decodable { let groups: [CategoryGroup]; let legend: [StyleLegend]; let lightColors: [String: String] }
struct LevelItem {
    let id: String, label: String, explanation: String, color: String
    let price: Double
    let linestyle: Int
    init?(_ json: [String: Any]) {
        guard let price = json["price"] as? Double, let label = json["label"] as? String else { return nil }
        self.price = price; self.label = label; self.linestyle = json["linestyle"] as? Int ?? 2
        id = json["entity_id"] as? String ?? ""
        explanation = json["explanation"] as? String ?? "Click Draw to load this level’s explanation."
        color = json["color"] as? String ?? "#888888"
    }
}
final class LineSample: NSView {
    let colors: [NSColor], linestyle: Int
    init(frame: NSRect, colors: [NSColor], linestyle: Int) {
        self.colors = colors; self.linestyle = linestyle; super.init(frame: frame)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func draw(_ dirtyRect: NSRect) {
        let span = bounds.width / CGFloat(max(colors.count, 1))
        for (index, color) in colors.enumerated() {
            color.setStroke(); let line = NSBezierPath(); line.lineWidth = 1
            if linestyle == 1 { line.setLineDash([1, 3], count: 2, phase: 0) }
            if linestyle == 2 { line.setLineDash([4, 3], count: 2, phase: 0) }
            line.move(to: NSPoint(x: CGFloat(index) * span + 1, y: bounds.midY))
            line.line(to: NSPoint(x: CGFloat(index + 1) * span - 2, y: bounds.midY)); line.stroke()
        }
    }
}
final class FloatingPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}
final class LevelPanel: NSObject, NSApplicationDelegate, NSWindowDelegate, NSTableViewDataSource, NSTableViewDelegate {
    var panel: FloatingPanel!
    var draw: NSButton!, clear: NSButton!, status: NSTextField!, contextLabel: NSTextField!
    var themeButton: NSButton!
    var themeCards: [NSBox] = []
    var tabs: NSSegmentedControl!, filters: NSView!, inspector: NSView!, table: NSTableView!
    var detailTitle: NSTextField!, detailText: NSTextView!
    var optionButtons: [(category: Category, button: NSButton)] = []
    var helpButtons: [NSButton] = []
    var levels: [LevelItem] = [], scope: String?, lastSelectedID: String?
    var availability: [String: String] = [:]
    var lastThemeAttempt: String?
    var busy = false, shuttingDown = false, updatingTable = false
    var config: Config!, catalog: Catalog!, observer: Process?, popover: NSPopover?
    let defaults = UserDefaults.standard
    let preferenceKey = "enabledLevelCategories"
    let themePreferenceKey = "panelTheme"
    var lightTheme: Bool { defaults.string(forKey: themePreferenceKey) == "light" }
    let priceFormatter: NumberFormatter = {
        let f = NumberFormatter(); f.numberStyle = .currency; f.currencySymbol = "$"
        f.minimumFractionDigits = 2; f.maximumFractionDigits = 6; f.locale = Locale(identifier: "en_US")
        return f
    }()
    func font(_ size: CGFloat, bold: Bool = false) -> NSFont {
        NSFont(name: bold ? "AvenirNext-DemiBold" : "AvenirNext-Regular", size: size) ?? .systemFont(ofSize: size, weight: bold ? .semibold : .regular)
    }
    func label(_ text: String, _ frame: NSRect, size: CGFloat = 12, bold: Bool = false) -> NSTextField {
        let field = NSTextField(labelWithString: text); field.frame = frame; field.font = font(size, bold: bold)
        field.lineBreakMode = .byTruncatingTail; return field
    }
    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            config = try JSONDecoder().decode(Config.self, from: Data(contentsOf: Bundle.main.url(forResource: "runtime", withExtension: "json")!))
            catalog = try JSONDecoder().decode(Catalog.self, from: Data(contentsOf: Bundle.main.url(forResource: "categories", withExtension: "json")!))
        } catch { NSLog("Daily Levels configuration: %@", error.localizedDescription); NSApp.terminate(nil); return }
        panel = FloatingPanel(contentRect: NSRect(x: 0, y: 0, width: 384, height: 550),
            styleMask: [.titled, .closable, .utilityWindow, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Daily Levels"; panel.level = .floating; panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false; panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.delegate = self
        let content = panel.contentView!
        content.addSubview(label("Chart levels", NSRect(x: 16, y: 512, width: 190, height: 26), size: 20, bold: true))
        themeButton = NSButton(title: "Light", target: self, action: #selector(toggleTheme))
        themeButton.bezelStyle = .rounded; themeButton.font = font(11)
        themeButton.frame = NSRect(x: 222, y: 514, width: 64, height: 24)
        content.addSubview(themeButton)
        let legend = NSButton(title: "Legend", target: self, action: #selector(showLegend(_:)))
        legend.bezelStyle = .rounded; legend.font = font(11)
        legend.frame = NSRect(x: 292, y: 514, width: 78, height: 24)
        legend.setAccessibilityLabel("Line style legend"); content.addSubview(legend)
        contextLabel = label("Connecting to TradingView…", NSRect(x: 16, y: 487, width: 352, height: 20), size: 11)
        contextLabel.textColor = .secondaryLabelColor; content.addSubview(contextLabel)
        tabs = NSSegmentedControl(labels: ["Categories", "Levels"], trackingMode: .selectOne, target: self, action: #selector(changeTab))
        tabs.frame = NSRect(x: 16, y: 452, width: 352, height: 28); tabs.selectedSegment = 0
        tabs.setAccessibilityLabel("Panel view"); content.addSubview(tabs)
        filters = NSView(frame: NSRect(x: 16, y: 99, width: 352, height: 346)); content.addSubview(filters)
        inspector = NSView(frame: filters.frame); content.addSubview(inspector)
        createFilters(); createInspector()
        for (index, button) in [NSButton(title: "Draw levels", target: self, action: #selector(drawLevels)), NSButton(title: "Clear levels", target: self, action: #selector(clearLevels))].enumerated() {
            button.bezelStyle = .rounded; button.font = font(13, bold: index == 0)
            button.frame = NSRect(x: 12 + index * 180, y: 54, width: 180, height: 34)
            if index == 0 { draw = button } else { clear = button }
            content.addSubview(button)
        }
        status = NSTextField(wrappingLabelWithString: "Choose categories, then Draw on the selected chart.")
        status.frame = NSRect(x: 16, y: 10, width: 352, height: 36); status.font = font(11)
        status.textColor = .secondaryLabelColor; content.addSubview(status)
        panel.setFrameAutosaveName("DailyLevelsPanel")
        if !panel.setFrameUsingName("DailyLevelsPanel"), let screen = NSScreen.main {
            let area = screen.visibleFrame
            panel.setFrameTopLeftPoint(NSPoint(x: area.maxX - 404, y: area.maxY - 60))
        }
        draw.isEnabled = optionButtons.contains { $0.button.state == .on }
        applyTheme(); changeTab(); panel.orderFrontRegardless(); startObserver()
    }
    @objc func toggleTheme() {
        guard !busy else { return }
        defaults.set(lightTheme ? "dark" : "light", forKey: themePreferenceKey)
        lastThemeAttempt = nil; applyTheme(); syncDrawingTheme()
    }
    func applyTheme() {
        popover?.close()
        let appearance = NSAppearance(named: lightTheme ? .aqua : .darkAqua)
        NSApp.appearance = appearance; panel.appearance = appearance
        themeButton.title = lightTheme ? "Dark" : "Light"
        let action = lightTheme ? "Switch to dark theme" : "Switch to light theme"
        themeButton.toolTip = action; themeButton.setAccessibilityLabel(action)
        for card in themeCards {
            card.borderColor = NSColor(calibratedWhite: lightTheme ? 0.80 : 0.24, alpha: 1)
            card.fillColor = NSColor(calibratedWhite: lightTheme ? 0.98 : 0.13, alpha: 1)
        }
        table.backgroundColor = .controlBackgroundColor
        detailText.backgroundColor = .textBackgroundColor
        detailText.textColor = .labelColor
        let selected = table.selectedRow
        updatingTable = true; table.reloadData()
        if selected >= 0 && selected < levels.count { table.selectRowIndexes(IndexSet(integer: selected), byExtendingSelection: false) }
        updatingTable = false
        panel.contentView?.needsDisplay = true
        do {
            let directory = URL(fileURLWithPath: config.root + "/.local/panel", isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try JSONSerialization.data(withJSONObject: ["theme": lightTheme ? "light" : "dark"]).write(to: directory.appendingPathComponent("theme.json"), options: .atomic)
        } catch { status.stringValue = "Could not save the drawing theme: " + error.localizedDescription }
    }
    func syncDrawingTheme() {
        guard !busy, let scope = scope, !levels.isEmpty else { return }
        let theme = lightTheme ? "light" : "dark", key = scope + "|" + (lightTheme ? "light" : "dark")
        guard lastThemeAttempt != key else { return }
        lastThemeAttempt = key
        busy = true; draw.isEnabled = false; clear.isEnabled = false; themeButton.isEnabled = false
        optionButtons.forEach { $0.button.isEnabled = false }
        status.textColor = .secondaryLabelColor; status.stringValue = "Updating drawing colors…"
        let p = process("level_theme.py", ["--theme", theme, "--scope", scope])
        DispatchQueue.global(qos: .userInitiated).async {
            let output = Pipe(), errors = Pipe(); p.standardOutput = output; p.standardError = errors
            var message = "", failed = false
            do {
                try p.run()
                final class ErrorData: @unchecked Sendable { var data = Data() }
                let errorData = ErrorData(), drain = DispatchGroup(); drain.enter()
                DispatchQueue.global().async { errorData.data = errors.fileHandleForReading.readDataToEndOfFile(); drain.leave() }
                let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit(); drain.wait()
                if p.terminationStatus != 0 {
                    failed = true
                    message = (String(data: errorData.data, encoding: .utf8) ?? "Theme update failed").split(separator: "\n").last.map(String.init) ?? "Theme update failed"
                    if message.hasPrefix("RuntimeError: ") { message = String(message.dropFirst(14)) }
                } else {
                    let result = try JSONSerialization.jsonObject(with: data) as? [String: Any]
                    message = "\(result?["symbol"] as? String ?? "Chart"): \(theme) drawing colors applied."
                }
            } catch { failed = true; message = error.localizedDescription }
            let finalMessage = message, finalFailed = failed
            DispatchQueue.main.async {
                self.status.stringValue = finalMessage; self.status.textColor = finalFailed ? .systemRed : .secondaryLabelColor
                self.busy = false; self.draw.isEnabled = self.optionButtons.contains { $0.button.state == .on }
                self.clear.isEnabled = true; self.themeButton.isEnabled = true
                self.optionButtons.forEach { $0.button.isEnabled = true }
            }
        }
    }
    func createFilters() {
        let stored = defaults.dictionary(forKey: preferenceKey) as? [String: Bool] ?? [:]
        let height = max(CGFloat(346), catalog.groups.reduce(CGFloat(40)) { total, group in
            let columns = ["trendlines", "events"].contains(group.id) ? 1 : 2
            return total + CGFloat(38 + ((group.levels.count + columns - 1) / columns) * 26 + 10)
        })
        let scroll = NSScrollView(frame: filters.bounds)
        scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
        let document = NSView(frame: NSRect(x: 0, y: 0, width: 334, height: height))
        scroll.documentView = document; filters.addSubview(scroll)
        var top: CGFloat = height
        var tag = 0
        for group in catalog.groups {
            let columns = ["trendlines", "events"].contains(group.id) ? 1 : 2
            let buttonWidth: CGFloat = columns == 1 ? 296 : 132
            let height = CGFloat(38 + ((group.levels.count + columns - 1) / columns) * 26)
            top -= height
            let card = NSBox(frame: NSRect(x: 0, y: top, width: 334, height: height))
            card.boxType = .custom; card.borderWidth = 1; card.cornerRadius = 8
            card.borderColor = NSColor(calibratedWhite: 0.24, alpha: 1)
            card.fillColor = NSColor(calibratedWhite: 0.13, alpha: 1); card.contentViewMargins = .zero
            themeCards.append(card)
            let inside = NSView(frame: NSRect(x: 0, y: 0, width: 334, height: height)); card.contentView = inside
            let heading = label(group.title, NSRect(x: 12, y: height - 26, width: 260, height: 16), size: 10, bold: true)
            heading.textColor = .secondaryLabelColor; inside.addSubview(heading)
            for (i, category) in group.levels.enumerated() {
                let x = CGFloat(12 + (i % columns) * 164), y = height - 51 - CGFloat(i / columns) * 26
                let button = NSButton(checkboxWithTitle: category.title, target: self, action: #selector(selectionChanged))
                button.frame = NSRect(x: x, y: y, width: buttonWidth, height: 24); button.font = font(11)
                button.state = (stored[category.kind] ?? true) ? .on : .off
                button.toolTip = category.explanation; inside.addSubview(button)
                optionButtons.append((category, button))
                let help = NSButton(image: NSImage(systemSymbolName: "info.circle", accessibilityDescription: "Explain \(category.title)")!, target: self, action: #selector(showCategoryHelp(_:)))
                help.tag = tag; help.frame = NSRect(x: x + buttonWidth + 1, y: y + 4, width: 18, height: 18)
                help.isBordered = false; help.contentTintColor = .secondaryLabelColor
                help.setAccessibilityLabel("Explain \(category.title)"); inside.addSubview(help); helpButtons.append(help)
                tag += 1
            }
            document.addSubview(card); top -= 10
        }
        let hint = NSTextField(wrappingLabelWithString: "ⓘ Definitions · Checkbox choices are saved.")
        hint.frame = NSRect(x: 12, y: 12, width: 328, height: 22); hint.font = font(11)
        hint.textColor = .secondaryLabelColor; document.addSubview(hint)
        scroll.contentView.scroll(to: NSPoint(x: 0, y: height - filters.bounds.height))
        scroll.reflectScrolledClipView(scroll.contentView)
    }
    func createInspector() {
        let hint = label("Click a level here or select its drawing on the chart.", NSRect(x: 0, y: 326, width: 352, height: 18), size: 11)
        hint.textColor = .secondaryLabelColor; inspector.addSubview(hint)
        table = NSTableView(); table.rowHeight = 36; table.intercellSpacing = NSSize(width: 4, height: 2)
        table.dataSource = self; table.delegate = self; table.usesAlternatingRowBackgroundColors = true
        table.allowsMultipleSelection = false; table.setAccessibilityLabel("Drawn levels")
        for (id, title, width) in [("color", "", CGFloat(18)), ("price", "Price", CGFloat(84)), ("label", "Reference", CGFloat(234))] {
            let column = NSTableColumn(identifier: NSUserInterfaceItemIdentifier(id)); column.title = title; column.width = width
            column.resizingMask = id == "label" ? .autoresizingMask : []
            table.addTableColumn(column)
        }
        let list = NSScrollView(frame: NSRect(x: 0, y: 163, width: 352, height: 158))
        list.documentView = table; list.hasVerticalScroller = true; list.borderType = .bezelBorder; inspector.addSubview(list)
        detailTitle = label("Select a level", NSRect(x: 0, y: 136, width: 352, height: 22), size: 12, bold: true)
        inspector.addSubview(detailTitle)
        let details = NSScrollView(frame: NSRect(x: 0, y: 0, width: 352, height: 132))
        details.hasVerticalScroller = true; details.borderType = .bezelBorder
        detailText = NSTextView(frame: NSRect(x: 0, y: 0, width: 330, height: 132))
        detailText.isEditable = false; detailText.isSelectable = true; detailText.font = font(12)
        detailText.textColor = .labelColor; detailText.textContainerInset = NSSize(width: 9, height: 9)
        detailText.isVerticallyResizable = true; detailText.isHorizontallyResizable = false
        detailText.autoresizingMask = [.width]; detailText.minSize = .zero
        detailText.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        detailText.textContainer?.containerSize = NSSize(width: 330, height: CGFloat.greatestFiniteMagnitude)
        detailText.textContainer?.widthTracksTextView = true
        detailText.string = "Select one of the drawn levels to see what it represents, where it came from, and why nearby references share a line."
        detailText.setAccessibilityLabel("Level explanation")
        details.documentView = detailText; inspector.addSubview(details)
    }
    @objc func changeTab() { filters.isHidden = tabs.selectedSegment != 0; inspector.isHidden = tabs.selectedSegment != 1 }
    @objc func showCategoryHelp(_ sender: NSButton) {
        let category = optionButtons[sender.tag].category
        popover?.close()
        let controller = NSViewController(); controller.view = NSView(frame: NSRect(x: 0, y: 0, width: 316, height: 234))
        controller.view.addSubview(label(category.title, NSRect(x: 14, y: 199, width: 288, height: 23), size: 15, bold: true))
        var text = category.explanation + "\n\nAppearance: " + category.appearance
        if let reason = availability[category.kind] { text += "\n\nLast Draw: " + reason }
        let scroll = NSScrollView(frame: NSRect(x: 14, y: 13, width: 288, height: 176))
        scroll.hasVerticalScroller = true; scroll.autohidesScrollers = true
        scroll.drawsBackground = false
        let field = NSTextView(frame: NSRect(x: 0, y: 0, width: 272, height: 176))
        field.font = font(12); field.string = text; field.isEditable = false; field.isSelectable = true
        field.drawsBackground = false; field.textColor = .labelColor
        field.isVerticallyResizable = true; field.isHorizontallyResizable = false
        field.autoresizingMask = [.width]
        field.textContainer?.widthTracksTextView = true
        field.textContainer?.containerSize = NSSize(width: 272, height: CGFloat.greatestFiniteMagnitude)
        scroll.documentView = field; controller.view.addSubview(scroll)
        let help = NSPopover(); help.behavior = .transient; help.contentViewController = controller
        help.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minX); popover = help
    }
    @objc func showLegend(_ sender: NSButton) {
        popover?.close()
        let height = CGFloat(140 + catalog.legend.count * 52)
        let controller = NSViewController(); controller.view = NSView(frame: NSRect(x: 0, y: 0, width: 360, height: height))
        controller.view.addSubview(label("Drawing styles", NSRect(x: 14, y: height - 34, width: 332, height: 24), size: 16, bold: true))
        for (index, entry) in catalog.legend.enumerated() {
            let y = height - 96 - CGFloat(index * 52)
            let sample = LineSample(frame: NSRect(x: 14, y: y + 18, width: 60, height: 16), colors: entry.colors.map { color($0) }, linestyle: entry.linestyle)
            sample.setAccessibilityLabel(entry.explanation); controller.view.addSubview(sample)
            controller.view.addSubview(label(entry.title, NSRect(x: 88, y: y + 30, width: 258, height: 18), size: 12, bold: true))
            let detail = NSTextField(wrappingLabelWithString: entry.explanation); detail.font = font(11)
            detail.textColor = .secondaryLabelColor; detail.frame = NSRect(x: 88, y: y, width: 258, height: 30)
            controller.view.addSubview(detail)
        }
        let footer = NSTextField(wrappingLabelWithString: "All lines: 1 pixel. Green/orange uses the Draw quote.\n\nMerged lines: premarket styling, then daily/Prior.\nLabels keep all sources.")
        footer.font = font(11); footer.frame = NSRect(x: 14, y: 12, width: 332, height: 70)
        footer.textColor = .secondaryLabelColor; controller.view.addSubview(footer)
        let help = NSPopover(); help.behavior = .transient; help.contentViewController = controller
        help.show(relativeTo: NSRect(x: 16, y: 514, width: 352, height: 24), of: panel.contentView!, preferredEdge: .minY); popover = help
    }
    @objc func selectionChanged() {
        defaults.set(Dictionary(uniqueKeysWithValues: optionButtons.map { ($0.category.kind, $0.button.state == .on) }), forKey: preferenceKey)
        draw.isEnabled = !busy && optionButtons.contains { $0.button.state == .on }
        status.textColor = .secondaryLabelColor
        status.stringValue = draw.isEnabled ? "Click Draw to apply your categories." : "Select at least one category."
    }
    func numberOfRows(in tableView: NSTableView) -> Int { levels.count }
    func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        let item = levels[row], id = tableColumn!.identifier.rawValue
        if id == "color" {
            let sample = LineSample(frame: NSRect(x: 0, y: 9, width: tableColumn!.width - 4, height: 18), colors: [color(item.color)], linestyle: item.linestyle)
            sample.setAccessibilityLabel("Line sample, " + ([0: "solid", 1: "dotted", 2: "dashed"][item.linestyle] ?? "dashed"))
            let cell = NSTableCellView(); cell.addSubview(sample); return cell
        }
        let field = NSTextField(labelWithString: id == "price" ? money(item.price) : item.label)
        field.font = id == "price" ? .monospacedDigitSystemFont(ofSize: 12, weight: .medium) : font(11)
        field.lineBreakMode = .byTruncatingTail
        if id == "color" { field.textColor = color(item.color) }
        if id == "label" { field.toolTip = item.label }
        field.setAccessibilityLabel(id == "color" ? "Line color" : field.stringValue)
        let cell = NSTableCellView(); field.frame = NSRect(x: 0, y: 9, width: tableColumn!.width - 4, height: 18)
        field.autoresizingMask = [.width]; cell.addSubview(field); cell.textField = field; return cell
    }
    func tableViewSelectionDidChange(_ notification: Notification) {
        guard !updatingTable, table.selectedRow >= 0, table.selectedRow < levels.count else { return }
        showLevel(levels[table.selectedRow])
    }
    func showLevel(_ item: LevelItem) {
        detailTitle.stringValue = money(item.price) + " · " + item.label
        detailTitle.toolTip = detailTitle.stringValue; detailText.string = item.explanation
        detailText.scrollRangeToVisible(NSRange(location: 0, length: 0))
    }
    func money(_ price: Double) -> String { priceFormatter.string(from: NSNumber(value: price)) ?? String(price) }
    func color(_ hex: String) -> NSColor {
        let themed = lightTheme ? (catalog.lightColors[hex.lowercased()] ?? hex) : hex
        let value = Int(themed.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0x888888
        return NSColor(srgbRed: CGFloat((value >> 16) & 255) / 255, green: CGFloat((value >> 8) & 255) / 255, blue: CGFloat(value & 255) / 255, alpha: 1)
    }
    func applySnapshot(_ json: [String: Any], fromDraw: Bool = false) {
        guard !shuttingDown else { return }
        if json["connected"] as? Bool == false {
            lastThemeAttempt = nil
            contextLabel.stringValue = "TradingView unavailable · last view retained"
            contextLabel.toolTip = json["error"] as? String; return
        }
        let nextScope = json["scope"] as? String, chartChanged = scope != nextScope
        let symbol = json["symbol"] as? String ?? "Chart"
        let pane = (json["pane"] as? [String: Any])?["pane_id"] as? String ?? ""
        var caption = symbol.replacingOccurrences(of: "NASDAQ:", with: "").replacingOccurrences(of: "AMEX:", with: "") + " · chart " + pane
        if let timestamp = json["drawn_at"] as? Double {
            let f = DateFormatter(); f.dateFormat = "HH:mm"; f.timeZone = TimeZone(identifier: "America/New_York")
            caption += " · drawn " + f.string(from: Date(timeIntervalSince1970: timestamp)) + " ET"
        }
        contextLabel.stringValue = caption
        contextLabel.toolTip = "Levels for the selected chart in the visible TradingView tab."
        let oldID = table.selectedRow >= 0 && table.selectedRow < levels.count ? levels[table.selectedRow].id : nil
        let previousRows = levels.map { "\($0.id)|\($0.price)|\($0.label)|\($0.explanation)|\($0.color)|\($0.linestyle)" }
        let nextLevels = (json["levels"] as? [[String: Any]] ?? []).compactMap(LevelItem.init).sorted { $0.price > $1.price }
        scope = nextScope; levels = nextLevels; availability = json["availability"] as? [String: String] ?? [:]
        if chartChanged || fromDraw || previousRows != levels.map({ "\($0.id)|\($0.price)|\($0.label)|\($0.explanation)|\($0.color)|\($0.linestyle)" }) {
            updatingTable = true; table.reloadData(); table.deselectAll(nil); updatingTable = false
            if !chartChanged, let oldID = oldID, let row = levels.firstIndex(where: { $0.id == oldID }) { table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false) }
            else { detailTitle.stringValue = levels.isEmpty ? "No levels on this chart" : "Select a level"; detailText.string = levels.isEmpty ? "Click Draw to add your selected level categories to this chart." : "Click a row to see its source prices, dates and explanation." }
        }
        let selectedID = json["selected_id"] as? String
        if chartChanged { lastSelectedID = nil }
        if let id = selectedID, (id != lastSelectedID || chartChanged), let row = levels.firstIndex(where: { $0.id == id }) {
            tabs.selectedSegment = 1; changeTab(); table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false)
            table.scrollRowToVisible(row); showLevel(levels[row])
        }
        lastSelectedID = selectedID
        if fromDraw {
            tabs.selectedSegment = 1; changeTab()
            if let quote = (json["reference"] as? [String: Any])?["price"] as? Double,
               let row = levels.indices.min(by: { abs(levels[$0].price - quote) < abs(levels[$1].price - quote) }) {
                table.selectRowIndexes(IndexSet(integer: row), byExtendingSelection: false); table.scrollRowToVisible(row); showLevel(levels[row])
            }
        }
        if (json["drawing_theme"] as? String ?? "dark") == (lightTheme ? "light" : "dark") { lastThemeAttempt = nil }
        if json["has_theme_sources"] as? Bool == true && (json["drawing_theme"] as? String ?? "dark") != (lightTheme ? "light" : "dark") {
            syncDrawingTheme()
        }
    }
    @objc func drawLevels() { perform(clear: false) }
    @objc func clearLevels() { perform(clear: true) }
    func process(_ file: String, _ arguments: [String]) -> Process {
        let p = Process(); p.executableURL = URL(fileURLWithPath: config.python)
        p.arguments = [config.root + "/python/" + file] + arguments
        p.currentDirectoryURL = URL(fileURLWithPath: config.root)
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = config.nodeDirectory + ":" + (environment["PATH"] ?? "/usr/bin:/bin")
        environment["TVLEVELS_MCP_ROOT"] = config.mcpRoot
        p.environment = environment; return p
    }
    func perform(clear clearing: Bool) {
        guard !busy else { return }
        let selected = optionButtons.filter { $0.button.state == .on }.map { $0.category.kind }
        guard clearing || !selected.isEmpty else { selectionChanged(); return }
        busy = true; draw.isEnabled = false; clear.isEnabled = false; themeButton.isEnabled = false; popover?.close()
        optionButtons.forEach { $0.button.isEnabled = false }
        status.textColor = .secondaryLabelColor; status.stringValue = clearing ? "Clearing this chart’s levels…" : "Drawing on the selected chart…"
        let p = process("daily_levels.py", clearing ? ["--clear"] : ["--theme", lightTheme ? "light" : "dark", "--level-types"] + selected)
        DispatchQueue.global(qos: .userInitiated).async {
            let output = Pipe(), errors = Pipe(); p.standardOutput = output; p.standardError = errors
            var message = "", failed = false, payload: [String: Any]?
            do {
                try p.run()
                final class ErrorData: @unchecked Sendable { var data = Data() }
                let errorData = ErrorData(), drain = DispatchGroup(); drain.enter()
                DispatchQueue.global().async { errorData.data = errors.fileHandleForReading.readDataToEndOfFile(); drain.leave() }
                let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit(); drain.wait()
                if p.terminationStatus != 0 {
                    failed = true
                    message = (String(data: errorData.data, encoding: .utf8) ?? "Action failed").split(separator: "\n").last.map(String.init) ?? "Action failed"
                    if message.hasPrefix("RuntimeError: ") { message = String(message.dropFirst(14)) }
                } else {
                    guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw CocoaError(.fileReadCorruptFile) }
                    payload = json
                    let symbol = json["symbol"] as? String ?? "Chart"
                    let count = clearing ? (json["removed"] as? Int ?? 0) : ((json["levels"] as? [Any])?.count ?? 0)
                    message = "Last \(clearing ? "Clear" : "Draw"): \(symbol) · \(count) levels."
                    if !clearing, let omitted = json["availability"] as? [String: String], !omitted.isEmpty { message += " Some references are outside range or unavailable; see category help." }
                }
            } catch { failed = true; message = error.localizedDescription }
            let finalMessage = message, finalFailed = failed, finalPayload = payload
            DispatchQueue.main.async {
                if let json = finalPayload {
                    if clearing {
                        self.applySnapshot(["connected": true, "symbol": json["symbol"] ?? "Chart", "pane": json["pane"] ?? [:], "scope": json["scope"] ?? "", "levels": []])
                    } else { self.applySnapshot(json, fromDraw: true) }
                }
                self.status.stringValue = finalMessage; self.status.toolTip = finalMessage
                self.status.textColor = finalFailed ? .systemRed : .secondaryLabelColor
                self.busy = false; self.draw.isEnabled = self.optionButtons.contains { $0.button.state == .on }; self.clear.isEnabled = true
                self.themeButton.isEnabled = true
                self.optionButtons.forEach { $0.button.isEnabled = true }
            }
        }
    }
    func startObserver() {
        guard !shuttingDown else { return }
        let p = process("level_inspector.py", ["--watch"]), output = Pipe(), errors = Pipe()
        p.standardOutput = output; p.standardError = errors; observer = p
        do { try p.run() } catch { contextLabel.stringValue = "Could not connect level explanations"; return }
        DispatchQueue.global(qos: .utility).async { _ = errors.fileHandleForReading.readDataToEndOfFile() }
        DispatchQueue.global(qos: .utility).async {
            var pending = Data()
            while true {
                let chunk = output.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                pending.append(chunk)
                while let newline = pending.firstIndex(of: 10) {
                    let line = Data(pending[..<newline]); pending.removeSubrange(...newline)
                    if let json = try? JSONSerialization.jsonObject(with: line) as? [String: Any] {
                        DispatchQueue.main.async { if !self.busy { self.applySnapshot(json) } }
                    }
                }
            }
            DispatchQueue.main.async {
                if !self.shuttingDown { DispatchQueue.main.asyncAfter(deadline: .now() + 3) { self.startObserver() } }
            }
        }
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if busy { status.stringValue = "Finishing chart changes…"; return false }
        shuttingDown = true; if observer?.isRunning == true { observer?.terminate() }
        NSApp.terminate(nil); return true
    }
    func applicationWillTerminate(_ notification: Notification) {
        shuttingDown = true; if observer?.isRunning == true { observer?.terminate() }
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = LevelPanel(); app.delegate = delegate; app.run()
