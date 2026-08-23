//  TokenStore.swift
//  The device token, in the Keychain.
//
//  The token is a bearer credential for someone's home machine: it goes
//  in the Keychain, not UserDefaults, and with
//  `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`.
//
//  Both halves of that constant are deliberate. *AfterFirstUnlock*
//  rather than *WhenUnlocked* because a notification-driven refresh can
//  run with the screen locked and would otherwise fail. *ThisDeviceOnly*
//  because the token identifies one physical device to the server: if
//  it rode an iCloud backup to a new phone, two devices would share one
//  identity and revoking either would revoke both.

import Foundation
import Security

enum TokenStore {
    private static let service = "com.hypernix.hyperlink.device-token"
    private static let account = "default"

    static func save(_ token: String) {
        let data = Data(token.utf8)
        // SecItemUpdate cannot create, and SecItemAdd cannot replace, so
        // delete-then-add is the standard shape for "upsert" here.
        delete()
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        SecItemAdd(query as CFDictionary, nil)
    }

    static func load() -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data,
              let token = String(data: data, encoding: .utf8),
              !token.isEmpty
        else { return nil }
        return token
    }

    static func delete() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
