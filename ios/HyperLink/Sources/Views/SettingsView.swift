//  SettingsView.swift
//  Which PC this phone is talking to, and how to stop.

import SwiftUI

struct SettingsView: View {
    @Environment(AppState.self) private var state
    @State private var confirmingUnpair = false

    var body: some View {
        List {
            Section("Paired with") {
                LabeledContent("Server", value: state.connection.serverName.isEmpty ? "—" : state.connection.serverName)
                LabeledContent("This device", value: state.connection.deviceName)
                LabeledContent("T1 API", value: state.connection.t1Version.isEmpty ? "—" : "v" + state.connection.t1Version)
                if let status = state.serverStatus {
                    LabeledContent("HyperNix", value: status.hypernixVersion)
                    LabeledContent("Models registered", value: "\(status.modelCount)")
                    LabeledContent(
                        "LM Studio bridge",
                        value: status.lmstudioBridgeEnabled ? "on" : "off"
                    )
                }
            }

            Section {
                ForEach(state.connection.endpoints, id: \.self) { endpoint in
                    HStack {
                        Text(endpoint)
                            .font(.system(.caption, design: .monospaced))
                            .lineLimit(1)
                        Spacer()
                        if endpoint.contains(".ts.net") || endpoint.contains("://100.") {
                            Image(systemName: "globe")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .accessibilityLabel("works away from home")
                        }
                    }
                }
            } header: {
                Text("Addresses tried, in order")
            } footer: {
                Text("The app uses whichever answers first. A globe marks the ones that keep working when you leave the house.")
            }

            if let error = state.connectionError {
                Section {
                    Label(error, systemImage: "wifi.exclamationmark")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }
            }

            Section {
                Button {
                    Task { await state.refreshAll() }
                } label: {
                    Label("Check the connection", systemImage: "arrow.clockwise")
                }
                Button(role: .destructive) {
                    confirmingUnpair = true
                } label: {
                    Label("Unpair this device", systemImage: "minus.circle")
                }
            }
        }
        .navigationTitle("Server")
        .confirmationDialog(
            "Unpair this device?",
            isPresented: $confirmingUnpair,
            titleVisibility: .visible
        ) {
            Button("Unpair", role: .destructive) { Task { await state.unpair() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your conversations stay on the PC. You will need a new pairing code to connect again.")
        }
    }
}
