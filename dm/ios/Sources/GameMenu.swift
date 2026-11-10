// The in-game menu, opened by the gamepad's menu button at the top centre (DmGamepad.m): the controller layout, then the settings-screen settings the running game takes at once
// (front_ios.m dm_setting_live), grouped as on the settings screen but without its headings, one row each, so the menu stays short over the game (its text size is fixed: front_ios.m
// startGame). A pick is saved as Play saves it (LauncherModel.choose), so the settings screen shows it at the next start; a setting an env file fixes is shown, not changed. Settings
// that need the next start (language, pipelines, the frame rate and so on), and the sliders, stay on the settings screen, which the menu's title points to.
import UIKit

var gameMenuModel: LauncherModel?   // the settings screen's model (Launcher.swift); nil in an app without one: the menu has the layout only

@_cdecl("dm_game_menu")
public func dmGameMenu() -> UnsafeMutableRawPointer {
    let title = gameMenuModel != nil ? "More settings on the start screen" : ""
    let menu = UIMenu(title: title, children: [UIDeferredMenuElement.uncached { done in done(gameMenuItems()) }])   // built each time it opens, so it shows the current choices
    return Unmanaged.passRetained(menu).toOpaque()
}

private func gameMenuItems() -> [UIMenuElement] {
    let names = ["2D", "3D", "Tap", "Native"]
    let layouts = (0..<4).filter { dm_pad_layout_offered(Int32($0)) }.map { l in
        UIAction(title: names[l], state: dm_pad_layout() == l ? .on : .off) { _ in dm_pad_layout_set(Int32(l)) }
    }
    let layout = UIMenu(title: "Controller layout", options: .singleSelection, children: layouts)   // a choice's value shows in its submenu: a subtitle would make each row two lines
    var items: [UIMenuElement] = []
    var placed = false
    if let m = gameMenuModel {
        for section in m.sections {
            var rows: [UIMenuElement] = section == "Controls" ? [layout] : []
            if section == "Controls" { placed = true }
            for s in m.rows(in: section) where (s.kind == "choice" || s.kind == "toggle") && dm_setting_live(s.env, nil) { rows.append(gameMenuRow(m, s)) }
            if !rows.isEmpty { items.append(UIMenu(options: .displayInline, children: rows)) }
        }
    }
    if !placed { items.insert(UIMenu(options: .displayInline, children: [layout]), at: 0) }
    if let a = amiiboMenu() { items.insert(UIMenu(options: .displayInline, children: [a]), at: 0) }
    return items
}

// The amiibo on the reader: the app's romfs_overlay/amiibo.tsv lists the amiibo the game accepts (id, name, group); a pick writes its ID into the file DM_AMIIBO names
// (main.m: Documents/amiibo.txt), which the host reads at the game's next scan, so it changes while the game runs. None empties it: the reader finds nothing
private func amiiboMenu() -> UIMenuElement? {
    guard let ov = ProcessInfo.processInfo.environment["DM_ROMFS_OVERLAY"]?.split(separator: ":").first,
          let path = ProcessInfo.processInfo.environment["DM_AMIIBO"], path.hasPrefix("/"),
          let list = try? String(contentsOfFile: String(ov) + "/amiibo.tsv", encoding: .utf8) else { return nil }
    let rows = list.split(separator: "\n").filter { !$0.hasPrefix("#") }.map { $0.split(separator: "\t", omittingEmptySubsequences: false).map(String.init) }.filter { $0.count >= 2 }
    let now = ((try? String(contentsOfFile: path, encoding: .utf8)) ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    func put(_ id: String) { try? (id.isEmpty ? "" : id + "\n").write(toFile: path, atomically: true, encoding: .utf8) }
    var groups: [String: [UIMenuElement]] = [:], order: [String] = []
    for r in rows {
        let g = r.count > 2 ? r[2] : ""
        if groups[g] == nil { groups[g] = []; order.append(g) }
        groups[g]!.append(UIAction(title: r[1], state: r[0].lowercased() == now ? .on : .off) { _ in put(r[0]) })
    }
    var children: [UIMenuElement] = [UIAction(title: "None", state: now.isEmpty ? .on : .off) { _ in put("") }]
    // a real amiibo, read by the phone's NFC reader (AmiiboScan.swift); in an install that can't use the reader, the row says so and explains instead
    var names: [String: String] = [:]; for r in rows { names[r[0].lowercased()] = r[1] }
    children.insert(AmiiboScan.menuItem(path: path, names: names), at: 0)
    for g in order { children.append(UIMenu(title: g, options: g.isEmpty ? .displayInline : [], children: groups[g]!)) }
    let name = rows.first { $0[0].lowercased() == now }?[1]
    return UIMenu(title: "Amiibo", subtitle: name ?? (now.isEmpty ? "None" : now), children: children)
}

private func gameMenuRow(_ m: LauncherModel, _ s: Setting) -> UIMenuElement {
    let now = m.values[s.env] ?? s.def, fixed = m.fixed.contains(s.env)
    let attributes: UIMenuElement.Attributes = fixed ? .disabled : []
    func pick(_ v: String) { m.choose(s, v); _ = dm_setting_live(s.env, v) }
    if s.kind == "toggle" {
        let a = UIAction(title: s.label, attributes: attributes, state: now == s.onValue ? .on : .off) { _ in pick(now == s.onValue ? s.offValue : s.onValue) }
        if fixed { a.subtitle = "Set at launch" }
        return a
    }
    let options = s.options ?? []
    let current = options.first { $0[0] == now }?[1] ?? now
    let actions = options.map { o in UIAction(title: o[1], attributes: attributes, state: o[0] == now ? .on : .off) { _ in pick(o[0]) } }
    return UIMenu(title: s.label, subtitle: fixed ? "\(current), set at launch" : nil, options: .singleSelection, children: actions)
}
