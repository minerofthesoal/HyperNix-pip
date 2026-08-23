//  ModelDownloadView.swift
//  Paste a Hugging Face link — or two — and get a real download plan.
//
//  Two fields rather than one, because the two links carry different
//  information and neither is sufficient alone. The model page says
//  which repository and what is in it; the download-arrow link says
//  exactly which quantisation. The server merges them (see
//  hypernix/hyperlink/hfmerge.py) and answers with every file that has
//  to be fetched for the thing to actually load — split GGUF parts as a
//  set, and the vision projector a VLM needs to read images.

import SwiftUI
import UIKit

struct ModelDownloadView: View {
    @Environment(AppState.self) private var state
    @Environment(\.dismiss) private var dismiss

    @State private var pageURL = ""
    @State private var fileURL = ""
    @State private var prefer = "strict"
    @State private var resolved: ResolvedModel?
    @State private var error: String?
    @State private var isResolving = false

    private var canResolve: Bool {
        !(pageURL.trimmingCharacters(in: .whitespaces).isEmpty
            && fileURL.trimmingCharacters(in: .whitespaces).isEmpty)
            && !isResolving
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Model page") {
                    TextField("https://huggingface.co/owner/model-GGUF", text: $pageURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Text("The page you were reading. Also accepts owner/model, or owner/model:Q4_K_M.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Section("Direct download link") {
                    TextField("https://huggingface.co/…/resolve/main/model-Q4_K_M.gguf", text: $fileURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Text("The link behind the download arrow on the Files tab. This is what picks the quantisation.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                if !pageURL.isEmpty && !fileURL.isEmpty {
                    Section("If the two links disagree") {
                        Picker("Trust", selection: $prefer) {
                            Text("Ask me").tag("strict")
                            Text("The file link").tag("file")
                            Text("The page").tag("page")
                        }
                        .pickerStyle(.segmented)
                    }
                }

                if let error {
                    Section {
                        Label(error, systemImage: "exclamationmark.triangle")
                            .foregroundStyle(.red)
                            .font(.callout)
                    }
                }

                if let resolved {
                    planSection(resolved)
                }

                Section {
                    Button {
                        Task { await resolve() }
                    } label: {
                        HStack {
                            if isResolving { ProgressView().padding(.trailing, 6) }
                            Text(isResolving ? "Working it out…" : "Resolve")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .disabled(!canResolve)
                }
            }
            .navigationTitle("Add a model")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }
                }
            }
        }
    }

    @ViewBuilder
    private func planSection(_ model: ResolvedModel) -> some View {
        Section("Download plan") {
            LabeledContent("Repository", value: model.repoID)
            LabeledContent("Quantisation", value: model.quantization.isEmpty ? "unknown" : model.quantization)
            LabeledContent("Total size", value: model.totalSizeHuman)
            LabeledContent("Files", value: "\(model.fileCount)")
            if !model.license.isEmpty {
                LabeledContent("Licence", value: model.license)
            }
            if model.isSplit {
                Label("Split model — every part is included", systemImage: "square.stack.3d.up")
                    .font(.caption)
            }
            if model.hasVision {
                Label("Vision projector included", systemImage: "eye")
                    .font(.caption)
            }
            if model.gated {
                Label("Gated: accept the licence on the model page first", systemImage: "lock")
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }

        Section("Files") {
            ForEach(model.files) { file in
                VStack(alignment: .leading, spacing: 2) {
                    Text(file.filename)
                        .font(.system(.caption, design: .monospaced))
                        .lineLimit(2)
                    HStack(spacing: 6) {
                        Text(file.role)
                        if file.partTotal > 0 {
                            Text("· part \(file.partIndex) of \(file.partTotal)")
                        }
                        if file.sizeBytes > 0 {
                            Text("· \(ByteCountFormatter.string(fromByteCount: Int64(file.sizeBytes), countStyle: .binary))")
                        }
                    }
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
            }
        }

        if !model.warnings.isEmpty {
            Section("Worth knowing") {
                ForEach(model.warnings, id: \.self) { warning in
                    Text(warning).font(.caption)
                }
            }
        }

        Section {
            // Fetching many gigabytes over cellular onto a phone is not
            // what anyone wants: the model runs on the PC, so the PC is
            // what downloads it. The plan is handed to the operator to
            // run there.
            Button {
                UIPasteboard.general.string = downloadCommand(model)
            } label: {
                Label("Copy the command for your PC", systemImage: "doc.on.doc")
            }
        } footer: {
            Text("The model runs on your PC, so your PC downloads it. Paste this into a terminal there.")
        }
    }

    private func downloadCommand(_ model: ResolvedModel) -> String {
        let files = model.files.map(\.filename).joined(separator: " ")
        return "hnx fetch \(model.repoID) --revision \(model.revision) --files \(files)"
    }

    private func resolve() async {
        isResolving = true
        error = nil
        defer { isResolving = false }
        do {
            resolved = try await state.resolveModel(pageURL: pageURL, fileURL: fileURL, prefer: prefer)
        } catch {
            resolved = nil
            self.error = (error as? HyperLinkError)?.errorDescription ?? error.localizedDescription
        }
    }
}
