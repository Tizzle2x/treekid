// A real amiibo, read by the phone's own NFC reader (Core NFC): the Amiibo menu's "Scan an amiibo" opens the system scan sheet, the figure is held to the top of the phone's back,
// and its amiibo ID (8 bytes at NTAG215 page 0x15, stored unencrypted on every amiibo) is written into the file DM_AMIIBO names, exactly as a pick from the list is. The host
// reads it at the game's next scan (hle_sdk16.c StartDetection). Only the ID is read: no dump, no keys, nothing is written to the figure.
// iOS lets an app use the reader only when its signature carries com.apple.developer.nfc.readersession.formats (TAG) and its Info.plist has NFCReaderUsageDescription (project.yml).
// Both belong to the process's own app: inside LiveContainer that is LiveContainer, not the game. A session started without the usage text kills the app, so unavailableReason
// checks both first and the menu explains instead of scanning; a session iOS still refuses ends in the same explanation (docs/playing.md: amiibo, the Shortcuts way without NFC).
import CoreNFC
import UIKit
import MachO

final class AmiiboScan: NSObject, NFCTagReaderSessionDelegate {
    private static var current: AmiiboScan?   // the session's delegate is weak: kept alive here until the sheet closes
    private let path: String, names: [String: String]
    private var session: NFCTagReaderSession?
    private var done = false   // this side ended the session (read, or a message on the sheet): its invalidation is not an error

    static let notCompatible = "This copy of the game can't use the iPhone's NFC reader"
    static let otherWays = "Pick the amiibo from the Amiibo list instead, or set up an NFC automation in the Shortcuts app (docs/playing.md, amiibo)."

    // nil when a scan can start; else why not, for the menu and its message
    static let unavailableReason: String? = {
        guard NFCTagReaderSession.readingAvailable else { return "this iPhone has no NFC reader, or NFC is turned off" }
        // The running app's own Info.plist (the main executable's folder; Bundle.main may be the game's under LiveContainer): without the usage text, iOS ends the app at the scan
        if let image = _dyld_get_image_name(0) {
            let info = NSDictionary(contentsOf: URL(fileURLWithPath: String(cString: image)).deletingLastPathComponent().appendingPathComponent("Info.plist"))
            if info?["NFCReaderUsageDescription"] == nil { return "the app it runs in (LiveContainer, for one) has no NFC permission text in its Info.plist" }
        }
        // The running app's signature: SecTask (Security.framework, not in the iOS headers, so looked up). Counted as missing only when the lookup itself worked
        typealias Create = @convention(c) (CFAllocator?) -> Unmanaged<AnyObject>?
        typealias Copy = @convention(c) (AnyObject, CFString, UnsafeMutablePointer<Unmanaged<CFError>?>?) -> Unmanaged<AnyObject>?
        let rtld = UnsafeMutableRawPointer(bitPattern: -2)   // RTLD_DEFAULT
        if let c = dlsym(rtld, "SecTaskCreateFromSelf"), let v = dlsym(rtld, "SecTaskCopyValueForEntitlement"),
           let task = unsafeBitCast(c, to: Create.self)(nil)?.takeRetainedValue() {
            var err: Unmanaged<CFError>?
            let value = unsafeBitCast(v, to: Copy.self)(task, "com.apple.developer.nfc.readersession.formats" as CFString, &err)?.takeRetainedValue()
            if err == nil, !((value as? [String])?.contains("TAG") ?? false) { return "the app it runs in isn't signed with the NFC tag reading permission" }
            err?.release()
        }
        return nil
    }()

    // The Amiibo menu's row (GameMenu.swift): a scan, or the reason there is none
    static func menuItem(path: String, names: [String: String]) -> UIAction {
        let reason = unavailableReason
        return UIAction(title: "Scan an amiibo", subtitle: reason == nil ? "Hold a real amiibo to the phone" : "Not available in this install", image: UIImage(systemName: "wave.3.right")) { _ in
            if let r = reason { tell(notCompatible, r.prefix(1).uppercased() + r.dropFirst() + ".\n\n" + otherWays) } else { start(path: path, names: names) }
        }
    }

    static func start(path: String, names: [String: String]) {
        guard current == nil else { return }
        let s = AmiiboScan(path: path, names: names)
        guard let session = NFCTagReaderSession(pollingOption: .iso14443, delegate: s, queue: nil) else { tell(notCompatible, otherWays); return }
        s.session = session; current = s
        session.alertMessage = "Hold an amiibo to the top of the back of your iPhone."
        session.begin()
    }

    private init(path: String, names: [String: String]) { self.path = path; self.names = names }

    // A message over the game (on the main thread, from the top view controller)
    static func tell(_ title: String, _ message: String) {
        DispatchQueue.main.async {
            guard var vc = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow }).first?.rootViewController else { return }
            while let p = vc.presentedViewController { vc = p }
            let a = UIAlertController(title: title, message: message, preferredStyle: .alert)
            a.addAction(UIAlertAction(title: "OK", style: .default))
            vc.present(a, animated: true)
        }
    }

    private func end(_ s: NFCTagReaderSession, _ message: String? = nil) { done = true; if let m = message { s.invalidate(errorMessage: m) } else { s.invalidate() } }

    func tagReaderSessionDidBecomeActive(_ session: NFCTagReaderSession) {}
    func tagReaderSession(_ session: NFCTagReaderSession, didInvalidateWithError error: Error) {
        AmiiboScan.current = nil
        guard !done, let e = error as? NFCReaderError else { return }
        switch e.code {
        case .readerSessionInvalidationErrorUserCanceled, .readerSessionInvalidationErrorSessionTimeout: return   // closed, or nothing held to the phone
        case .readerErrorUnsupportedFeature, .readerErrorSecurityViolation: AmiiboScan.tell(AmiiboScan.notCompatible, AmiiboScan.otherWays)   // no NFC permission in this install
        default: AmiiboScan.tell("The scan stopped", e.localizedDescription)
        }
    }

    func tagReaderSession(_ session: NFCTagReaderSession, didDetect tags: [NFCTag]) {
        guard let tag = tags.first, case let .miFare(m) = tag else {
            session.alertMessage = "That isn't an amiibo. Try another."; session.restartPolling(); return
        }
        session.connect(to: tag) { err in
            if err != nil { self.end(session, "Lost the amiibo. Try again and hold it still."); return }
            m.sendMiFareCommand(commandPacket: Data([0x30, 0x15])) { data, err in   // READ: pages 0x15-0x18; the first 8 bytes are the amiibo ID
                let id = [UInt8](data.prefix(8))
                guard err == nil, id.count == 8, id[7] == 0x02 else { self.end(session, "That tag isn't an amiibo."); return }   // every amiibo ID ends in 02 (figure, card and yarn alike)
                let hex = id.map { String(format: "%02x", $0) }.joined()
                do { try (hex + "\n").write(toFile: self.path, atomically: true, encoding: .utf8) }
                catch { self.end(session, "Couldn't save the amiibo."); return }
                session.alertMessage = "\(self.names[hex] ?? "amiibo \(hex)") is ready. Use amiibo in the game."
                self.end(session)
            }
        }
    }
}
