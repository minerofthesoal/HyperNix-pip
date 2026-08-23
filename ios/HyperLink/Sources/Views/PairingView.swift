//  PairingView.swift
//  Two fields: where the PC is, and the six characters it showed you.

import SwiftUI
import UIKit

struct PairingView: View {
    @Environment(AppState.self) private var state

    @State private var address = ""
    @State private var code = ""
    @State private var deviceName = UIDevice.current.name
    @State private var isPairing = false

    private var codeIsPlausible: Bool {
        code.filter { $0.isLetter || $0.isNumber }.count == 6
    }

    private var canPair: Bool {
        !address.trimmingCharacters(in: .whitespaces).isEmpty
            && codeIsPlausible
            && !deviceName.trimmingCharacters(in: .whitespaces).isEmpty
            && !isPairing
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Connect to your PC")
                            .font(.title2.weight(.semibold))
                        Text(
                            "On the computer running HyperNix, run `waiter hyperlink pair`. "
                            + "It prints an address and a six-character code."
                        )
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }

                Section("Server address") {
                    TextField("desktop.tailnet.ts.net:8000", text: $address)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .submitLabel(.next)
                    Text("A Tailscale name keeps working when you leave the house. A 192.168.x.y address only works at home.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Pairing code") {
                    TextField("ABC 123", text: $code)
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        // The alphabet excludes 0/O/1/I/L, so the code is
                        // unambiguous when read off a screen.
                        .font(.system(.title3, design: .monospaced))
                        .submitLabel(.done)
                    if !code.isEmpty && !codeIsPlausible {
                        Text("A pairing code is six characters.")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }

                Section("This device") {
                    TextField("iPhone", text: $deviceName)
                    Text("Shown on the PC in `waiter hyperlink devices`, so you can tell your devices apart later.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if let error = state.connectionError {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                            .font(.callout)
                    }
                }

                Section {
                    Button {
                        Task {
                            isPairing = true
                            _ = await state.pair(address: address, code: code, deviceName: deviceName)
                            isPairing = false
                        }
                    } label: {
                        HStack {
                            if isPairing { ProgressView().padding(.trailing, 6) }
                            Text(isPairing ? "Pairing…" : "Pair")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .disabled(!canPair)
                }
            }
            .navigationTitle("HyperLink")
        }
    }
}
