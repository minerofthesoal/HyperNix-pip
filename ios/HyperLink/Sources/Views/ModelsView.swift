//  ModelsView.swift
//  What is loaded on the PC, and how to get more of it.

import SwiftUI

struct ModelsView: View {
    @Environment(AppState.self) private var state
    @State private var showingDownload = false

    var body: some View {
        List {
            Section("Loaded on your PC") {
                if state.availableModels.isEmpty {
                    ContentUnavailableView {
                        Label("No models", systemImage: "cpu")
                    } description: {
                        Text(
                            "Open LM Studio on your PC, load a model, and pull to refresh. "
                            + "The bridge borrows whatever is loaded — it cannot load one for you."
                        )
                    }
                }
                ForEach(state.availableModels) { model in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(shortModelName(model.modelID)).lineLimit(1)
                            HStack(spacing: 6) {
                                if !model.quantization.isEmpty { Text(model.quantization) }
                                if model.maxContextLength > 0 {
                                    Text("·")
                                    Text("\(model.maxContextLength / 1024)k ctx")
                                }
                                if model.supportsVision {
                                    Text("·")
                                    Label("vision", systemImage: "eye").labelStyle(.titleOnly)
                                }
                            }
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        }
                        Spacer()
                        if model.loaded {
                            Image(systemName: "circle.fill")
                                .font(.caption2)
                                .foregroundStyle(.green)
                                .accessibilityLabel("loaded")
                        }
                    }
                }
            }

            Section {
                Button {
                    showingDownload = true
                } label: {
                    Label("Add a model from Hugging Face", systemImage: "arrow.down.circle")
                }
            } footer: {
                Text("Paste a model page link, a direct download link, or both — HyperNix works out which files are actually needed.")
            }
        }
        .navigationTitle("Models")
        .refreshable { await state.refreshModels() }
        .sheet(isPresented: $showingDownload) { ModelDownloadView() }
    }
}

struct ModelPickerSheet: View {
    let sessionID: String
    let currentModel: String
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if state.availableModels.isEmpty {
                    Text("No models loaded on your PC. Load one in LM Studio and pull to refresh.")
                        .foregroundStyle(.secondary)
                }
                ForEach(state.availableModels) { model in
                    Button {
                        Task {
                            await state.setModel(model.modelID, for: sessionID)
                            dismiss()
                        }
                    } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(shortModelName(model.modelID))
                                    .lineLimit(1)
                                    .foregroundStyle(.primary)
                                if !model.loaded {
                                    Text("not loaded — LM Studio will have to load it first")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            if model.modelID == currentModel {
                                Image(systemName: "checkmark").foregroundStyle(.tint)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Model")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .task { await state.refreshModels() }
        }
    }
}
