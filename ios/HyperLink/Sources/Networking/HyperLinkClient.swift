//  HyperLinkClient.swift
//  The one place that knows how to talk to a HyperNix T1 API server.
//
//  Two things here are not boilerplate and are worth reading before
//  changing anything:
//
//  1. **Endpoint failover.** A home server has several addresses — a LAN
//     IP that is fast at home and dead everywhere else, and a Tailscale
//     name that works anywhere and is a little slower. The phone cannot
//     know which network it is on (and asking iOS is unreliable and
//     racy), so the client simply tries the addresses in the order the
//     server ranked them and keeps the first that answers, re-testing
//     from the top when the current one fails. That is why `baseURL` is
//     a computed property over a *list* rather than a stored string.
//
//  2. **Errors are typed from the server's own envelope.** Every T1
//     failure carries a stable `code`; surfacing "MODEL_UNAVAILABLE"
//     as `.serverError(code:message:)` is what lets the chat view say
//     "your PC has no model loaded" instead of "something went wrong".

import Foundation

enum HyperLinkError: LocalizedError, Sendable {
    case notConfigured
    case noReachableEndpoint([String])
    case unauthorized(String)
    case serverError(code: String, message: String, status: Int)
    case transport(String)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "No server paired yet."
        case let .noReachableEndpoint(tried):
            return tried.isEmpty
                ? "No server address to try."
                : "Could not reach your PC at any known address (\(tried.joined(separator: ", "))). "
                    + "Check it is awake, and that Tailscale is on if you are away from home."
        case let .unauthorized(message):
            return message
        case let .serverError(_, message, _):
            return message
        case let .transport(message):
            return message
        case let .decoding(message):
            return "The server sent something this app could not read: \(message)"
        }
    }

    /// True when re-pairing is the only way forward — the app clears its
    /// stored token and returns to the pairing screen on this.
    var requiresRepairing: Bool {
        if case let .serverError(code, _, status) = self {
            return status == 401 && (code.hasPrefix("AUTH_") || code == "AUTH_REVOKED_KEY")
        }
        if case .unauthorized = self { return true }
        return false
    }
}

/// Immutable connection settings. Stored in UserDefaults; the token
/// itself lives in the Keychain and is injected at use.
struct ServerConnection: Codable, Equatable, Sendable {
    var endpoints: [String]
    var serverName: String
    var t1Version: String
    var deviceID: String
    var deviceName: String

    static let empty = ServerConnection(
        endpoints: [], serverName: "", t1Version: "", deviceID: "", deviceName: ""
    )

    var isConfigured: Bool { !endpoints.isEmpty && !deviceID.isEmpty }
}

actor HyperLinkClient {
    private var endpoints: [String]
    private var preferredIndex: Int = 0
    private var token: String?
    private let session: URLSession
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    /// The app's own version, sent as the User-Agent and recorded on the
    /// device record so `waiter hyperlink devices` can show which build
    /// a phone is running when something misbehaves.
    static let appVersion: String =
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "1.0.26"

    init(endpoints: [String] = [], token: String? = nil) {
        self.endpoints = endpoints
        self.token = token

        let config = URLSessionConfiguration.default
        // A home PC on a tailnet across cellular is slower than a CDN
        // and a 70B first token is slower still, so the resource timeout
        // is generous. The *request* timeout stays short: a dead address
        // must be ruled out quickly for failover to be worth having.
        config.timeoutIntervalForRequest = 20
        config.timeoutIntervalForResource = 600
        config.waitsForConnectivity = false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.allowsExpensiveNetworkAccess = true
        config.allowsConstrainedNetworkAccess = true
        self.session = URLSession(configuration: config)
    }

    // MARK: - Configuration

    func configure(endpoints: [String], token: String?) {
        self.endpoints = endpoints
        self.token = token
        self.preferredIndex = 0
    }

    func setToken(_ token: String?) { self.token = token }

    var currentEndpoint: String? {
        guard !endpoints.isEmpty else { return nil }
        return endpoints[min(preferredIndex, endpoints.count - 1)]
    }

    // MARK: - Request plumbing

    private func makeRequest(
        base: String,
        path: String,
        method: String,
        body: Data?,
        contentType: String?,
        authenticated: Bool,
        timeout: TimeInterval
    ) throws -> URLRequest {
        guard let url = URL(string: base.hasSuffix("/") ? String(base.dropLast()) + path : base + path) else {
            throw HyperLinkError.transport("Not a usable server address: \(base)")
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("HyperLink-iOS/\(Self.appVersion)", forHTTPHeaderField: "User-Agent")
        if let contentType {
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        if authenticated {
            guard let token, !token.isEmpty else { throw HyperLinkError.notConfigured }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    /// Run a request against each endpoint in turn until one answers.
    ///
    /// "Answers" means the HTTP layer completed — a 404 is an answer and
    /// stops failover, because the address is clearly a server and
    /// trying the next one would just produce the same 404 more slowly.
    /// Only a transport failure moves on.
    private func send(
        path: String,
        method: String = "GET",
        body: Data? = nil,
        contentType: String? = "application/json",
        authenticated: Bool = true,
        timeout: TimeInterval = 20
    ) async throws -> Data {
        guard !endpoints.isEmpty else { throw HyperLinkError.notConfigured }

        var tried: [String] = []
        var lastTransportError: Error?

        // Start at the endpoint that worked last time, then wrap around.
        let order = (0..<endpoints.count).map { (preferredIndex + $0) % endpoints.count }
        for index in order {
            let base = endpoints[index]
            tried.append(base)
            do {
                let request = try makeRequest(
                    base: base,
                    path: path,
                    method: method,
                    body: body,
                    contentType: contentType,
                    authenticated: authenticated,
                    timeout: timeout
                )
                let (data, response) = try await session.data(for: request)
                preferredIndex = index
                try Self.check(response: response, data: data)
                return data
            } catch let error as HyperLinkError {
                // A `.transport` failure means this address is not
                // usable (unparseable, wrong scheme) — that is exactly
                // what failover is for. Anything else is an answer from
                // a real server and trying the next address would just
                // produce the same answer more slowly.
                if case .transport = error {
                    lastTransportError = error
                    continue
                }
                throw error
            } catch {
                lastTransportError = error        // dead address; try the next
                continue
            }
        }
        if let lastTransportError, endpoints.count == 1 {
            throw HyperLinkError.transport(lastTransportError.localizedDescription)
        }
        throw HyperLinkError.noReachableEndpoint(tried)
    }

    private static func check(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard !(200..<300).contains(http.statusCode) else { return }
        if let envelope = try? JSONDecoder().decode(APIErrorEnvelope.self, from: data) {
            throw HyperLinkError.serverError(
                code: envelope.error.code,
                message: envelope.error.message,
                status: http.statusCode
            )
        }
        if http.statusCode == 401 || http.statusCode == 403 {
            throw HyperLinkError.unauthorized(
                "This device is no longer paired with that server. Pair it again."
            )
        }
        throw HyperLinkError.serverError(
            code: "HTTP_\(http.statusCode)",
            message: "The server returned HTTP \(http.statusCode).",
            status: http.statusCode
        )
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw HyperLinkError.decoding(String(describing: error))
        }
    }

    private func get<T: Decodable>(_ path: String, as type: T.Type, timeout: TimeInterval = 20) async throws -> T {
        try decode(type, from: await send(path: path, timeout: timeout))
    }

    private func post<T: Decodable>(
        _ path: String,
        body: some Encodable,
        as type: T.Type,
        authenticated: Bool = true,
        timeout: TimeInterval = 120
    ) async throws -> T {
        let data = try encoder.encode(body)
        return try decode(
            type,
            from: await send(
                path: path, method: "POST", body: data,
                authenticated: authenticated, timeout: timeout
            )
        )
    }

    // MARK: - Pairing (the only unauthenticated calls)

    /// Redeem a pairing code against one specific address.
    ///
    /// Deliberately not routed through `send`: at pairing time there is
    /// exactly one address — the one the user typed — and no token, so
    /// failover has nothing to fail over to and a confusing
    /// "tried 1 address" error would replace a precise one.
    static func pair(
        address: String,
        code: String,
        deviceName: String
    ) async throws -> (PairRedeemResponse, [ServerEndpoint]) {
        let base = normalize(address)
        let client = HyperLinkClient(endpoints: [base], token: nil)
        let payload = PairRedeemRequest(
            code: code.uppercased().filter { $0.isLetter || $0.isNumber },
            deviceName: deviceName,
            platform: "ios",
            appVersion: appVersion
        )
        let redeemed: PairRedeemResponse = try await client.post(
            "/hyperlink/pair/redeem", body: payload, as: PairRedeemResponse.self,
            authenticated: false, timeout: 20
        )
        // Now that there is a token, ask the server for its full address
        // list. This is what makes the app work away from home without
        // the user ever typing a Tailscale name.
        await client.setToken(redeemed.deviceToken)
        let discovered = (try? await client.endpoints())?.endpoints ?? []
        return (redeemed, discovered)
    }

    /// `desktop:8000` → `http://desktop:8000`, and strip a trailing slash.
    static func normalize(_ address: String) -> String {
        var text = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return text }
        if !text.contains("://") { text = "http://" + text }
        while text.hasSuffix("/") { text.removeLast() }
        // A bare host with no port almost always means the default the
        // server advertises; adding it beats a connection refused on 80.
        if let url = URL(string: text), url.port == nil, url.scheme == "http" {
            text += ":8000"
        }
        return text
    }

    // MARK: - Endpoints, status, identity

    func endpoints() async throws -> EndpointsResponse {
        try await get("/hyperlink/endpoints", as: EndpointsResponse.self, timeout: 10)
    }

    func status() async throws -> ServerStatus {
        try await get("/status", as: ServerStatus.self, timeout: 10)
    }

    func whoami() async throws -> DeviceSummary {
        try await get("/hyperlink/devices/me", as: DeviceResponse.self, timeout: 10).device
    }

    /// Sign out: revoke this device's own token, server-side.
    func unpairSelf(deviceID: String) async throws {
        _ = try await send(path: "/hyperlink/devices/\(deviceID)", method: "DELETE", timeout: 15)
    }

    // MARK: - Sessions

    func sessions() async throws -> [ChatSession] {
        try await get("/hyperlink/sessions?limit=100", as: SessionListResponse.self).sessions
    }

    func createSession(title: String = "", modelID: String = "", systemPrompt: String = "") async throws -> ChatSession {
        struct Body: Encodable {
            let title: String
            let model_id: String
            let system_prompt: String
        }
        return try await post(
            "/hyperlink/sessions",
            body: Body(title: title, model_id: modelID, system_prompt: systemPrompt),
            as: SessionResponse.self,
            timeout: 20
        ).session
    }

    func setModel(_ modelID: String, for sessionID: String) async throws -> ChatSession {
        struct Body: Encodable {
            let model_id: String
            let backend: String
        }
        let data = try encoder.encode(Body(model_id: modelID, backend: "lmstudio"))
        let response = try await send(
            path: "/hyperlink/sessions/\(sessionID)", method: "PATCH", body: data, timeout: 20
        )
        return try decode(SessionResponse.self, from: response).session
    }

    func deleteSession(_ sessionID: String) async throws {
        _ = try await send(path: "/hyperlink/sessions/\(sessionID)", method: "DELETE", timeout: 15)
    }

    func messages(in sessionID: String, afterSeq: Int = 0) async throws -> [ChatMessage] {
        try await get(
            "/hyperlink/sessions/\(sessionID)/messages?after_seq=\(afterSeq)",
            as: MessageListResponse.self
        ).messages
    }

    // MARK: - Chat

    func chat(
        sessionID: String,
        content: String,
        attachmentIDs: [String] = [],
        modelID: String? = nil
    ) async throws -> ChatTurnResponse {
        struct Body: Encodable {
            let content: String
            let attachment_ids: [String]
            let model_id: String?
        }
        return try await post(
            "/hyperlink/sessions/\(sessionID)/chat",
            body: Body(content: content, attachment_ids: attachmentIDs, model_id: modelID),
            as: ChatTurnResponse.self,
            timeout: 600
        )
    }

    /// Build the request for a streaming turn. The stream itself is
    /// driven by `SSEStream`, which needs the `URLRequest` rather than a
    /// decoded result — so this hands one back instead of doing the call.
    func streamingChatRequest(
        sessionID: String,
        content: String,
        attachmentIDs: [String],
        modelID: String?
    ) throws -> URLRequest {
        guard let base = currentEndpoint else { throw HyperLinkError.notConfigured }
        struct Body: Encodable {
            let content: String
            let attachment_ids: [String]
            let model_id: String?
            let stream: Bool
        }
        let body = try encoder.encode(
            Body(content: content, attachment_ids: attachmentIDs, model_id: modelID, stream: true)
        )
        var request = try makeRequest(
            base: base,
            path: "/hyperlink/sessions/\(sessionID)/chat/stream",
            method: "POST",
            body: body,
            contentType: "application/json",
            authenticated: true,
            timeout: 600
        )
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        return request
    }

    // MARK: - Attachments

    /// Multipart upload, built by hand.
    ///
    /// `URLSession` has no multipart builder and the body is small and
    /// well-specified, so hand-rolling it is less code than a dependency
    /// — but note the exact CRLFs: a `\n` where the spec says `\r\n`
    /// produces a 422 from Starlette that reads like a server bug.
    func upload(data: Data, filename: String, contentType: String, sessionID: String) async throws -> Attachment {
        let boundary = "hyperlink.\(UUID().uuidString)"
        var body = Data()
        func append(_ string: String) { body.append(Data(string.utf8)) }

        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"session_id\"\r\n\r\n")
        append("\(sessionID)\r\n")
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n")
        append("Content-Type: \(contentType)\r\n\r\n")
        body.append(data)
        append("\r\n--\(boundary)--\r\n")

        let response = try await send(
            path: "/hyperlink/files",
            method: "POST",
            body: body,
            contentType: "multipart/form-data; boundary=\(boundary)",
            timeout: 300
        )
        return try decode(AttachmentResponse.self, from: response).file
    }

    func attachmentData(_ fileID: String) async throws -> Data {
        try await send(path: "/hyperlink/files/\(fileID)", timeout: 120)
    }

    // MARK: - Models

    func bridgeModels() async throws -> BridgeModelsResponse {
        try await get("/bridge/lmstudio/models", as: BridgeModelsResponse.self, timeout: 30)
    }

    func resolveModel(pageURL: String, fileURL: String, prefer: String) async throws -> ResolvedModel {
        try await post(
            "/hyperlink/models/resolve",
            body: HFResolveRequest(
                pageURL: pageURL, fileURL: fileURL, prefer: prefer, includeVision: true
            ),
            as: ResolvedModel.self,
            timeout: 60
        )
    }
}
