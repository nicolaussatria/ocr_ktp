import Foundation

enum CardDocumentType: String {
    case ktp
    case businessCard = "business_card"
    case auto
}

enum OCRDataValue: Decodable {
    case string(String)
    case strings([String])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else { self = .strings(try container.decode([String].self)) }
    }

    var string: String? {
        if case .string(let value) = self { return value }
        return nil
    }
}

struct OCRField: Decodable {
    let value: String?
    let candidate: String?
    let status: String
    let ocrScore: Double?
    let reasons: [String]
}

enum OCRFieldEntry: Decodable {
    case single(OCRField)
    case multiple([OCRField])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let field = try? container.decode(OCRField.self) { self = .single(field) }
        else { self = .multiple(try container.decode([OCRField].self)) }
    }
}

struct CardOCRResult: Decodable {
    let schemaVersion: String
    let requestId: String
    let documentType: String
    let needsReview: Bool
    let status: String
    let data: [String: OCRDataValue]
    let fields: [String: OCRFieldEntry]
    let reviewReasons: [String]
}

struct CardOCRErrorEnvelope: Decodable {
    struct Detail: Decodable { let code: String; let message: String }
    let error: Detail
}

enum CardOCRError: Error {
    case invalidImageSize
    case invalidPhoneRegion
    case invalidResponse
    case server(status: Int, code: String, message: String)
}

/// iOS 15+. UIImage.jpegData(compressionQuality: 0.92) provides compatible image bytes.
final class CardOCRClient {
    private let baseURL: URL
    private let session: URLSession
    private let headers: [String: String]

    init(baseURL: URL, headers: [String: String] = [:], session: URLSession = .shared) {
        self.baseURL = baseURL
        self.headers = headers
        self.session = session
    }

    func scan(jpegData: Data, type: CardDocumentType = .auto, phoneRegion: String? = nil) async throws -> CardOCRResult {
        guard !jpegData.isEmpty, jpegData.count <= 10 * 1024 * 1024 else {
            throw CardOCRError.invalidImageSize
        }
        if let phoneRegion, phoneRegion.count != 2 || phoneRegion.range(of: "^[A-Za-z]{2}$", options: .regularExpression) == nil {
            throw CardOCRError.invalidPhoneRegion
        }
        let boundary = "CardOCR-\(UUID().uuidString)"
        var body = Data()
        func append(_ value: String) { body.append(Data(value.utf8)) }
        var fields = [("mode", "accurate"), ("include_raw", "false")]
        if let phoneRegion { fields.append(("phone_region", phoneRegion.uppercased())) }
        for (key, value) in fields {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(key)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"card.jpg\"\r\n")
        append("Content-Type: image/jpeg\r\n\r\n")
        body.append(jpegData)
        append("\r\n--\(boundary)--\r\n")

        let url = baseURL.appendingPathComponent("v1/ocr").appendingPathComponent(type.rawValue)
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 90)
        request.httpMethod = "POST"
        for (name, value) in headers { request.setValue(value, forHTTPHeaderField: name) }
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.upload(for: request, from: body)
        guard let http = response as? HTTPURLResponse else { throw CardOCRError.invalidResponse }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard (200..<300).contains(http.statusCode) else {
            let error = try? decoder.decode(CardOCRErrorEnvelope.self, from: data)
            throw CardOCRError.server(status: http.statusCode, code: error?.error.code ?? "HTTP_ERROR",
                                      message: error?.error.message ?? "OCR request failed")
        }
        return try decoder.decode(CardOCRResult.self, from: data)
    }
}

// let client = CardOCRClient(baseURL: URL(string: "https://your-app-api.example.com")!)
// let result = try await client.scan(jpegData: bytes, type: .ktp)
// let nik = result.data["nik"]?.string
// if result.needsReview { /* Show candidates and require correction/confirmation */ }
// Call from Task; update your UI on MainActor. Cancel the Task to cancel the upload.
// The production app calls your authenticated gateway; don't embed a server-wide API key.
