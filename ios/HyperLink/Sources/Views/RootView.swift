//  RootView.swift
//  Pairing screen, or the app. Nothing in between.

import SwiftUI

struct RootView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        Group {
            if state.isPaired {
                MainTabView()
            } else {
                PairingView()
            }
        }
        // Animating the swap makes signing out and pairing read as one
        // app changing state rather than two screens fighting.
        .animation(.easeInOut(duration: 0.25), value: state.isPaired)
    }
}

struct MainTabView: View {
    @Environment(AppState.self) private var state

    var body: some View {
        TabView {
            // ChatListView brings its own NavigationStack — see the
            // comment on its `path`.
            ChatListView()
                .tabItem { Label("Chats", systemImage: "bubble.left.and.bubble.right") }

            NavigationStack {
                ModelsView()
            }
            .tabItem { Label("Models", systemImage: "cpu") }

            NavigationStack {
                SettingsView()
            }
            .tabItem { Label("Server", systemImage: "desktopcomputer") }
        }
        .task { await state.refreshAll() }
    }
}
