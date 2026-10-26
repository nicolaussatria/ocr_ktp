package com.example.cardocr

import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

enum class CardDocumentType(val path: String) {
    KTP("ktp"), BUSINESS_CARD("business_card"), AUTO("auto")
}

data class CardOCRResult(val json: JSONObject) {
    val needsReview: Boolean get() = json.getBoolean("needs_review")
    val data: JSONObject get() = json.getJSONObject("data")
    val fields: JSONObject get() = json.getJSONObject("fields")

    fun acceptedString(key: String): String? =
        if (data.isNull(key)) null else data.optString(key).takeIf { it.isNotEmpty() }
}

class CardOCRException(val status: Int, val code: String, message: String) : Exception(message)

/** Native Android client using the platform HTTP stack. Reuse this instance. */
class CardOCRClient(private val baseUrl: String, private val headers: Map<String, String> = emptyMap()) {
    suspend fun scan(jpegBytes: ByteArray, type: CardDocumentType = CardDocumentType.AUTO, phoneRegion: String? = null): CardOCRResult =
        withContext(Dispatchers.IO) {
            require(jpegBytes.isNotEmpty() && jpegBytes.size <= 10 * 1024 * 1024) {
                "Choose an image between 1 byte and 10 MB"
            }
            require(phoneRegion == null || Regex("[A-Za-z]{2}").matches(phoneRegion)) {
                "Phone region must have two letters, such as ID or US"
            }
            val boundary = "CardOCR-${UUID.randomUUID()}"
            val before = buildString {
                append("--$boundary\r\nContent-Disposition: form-data; name=\"mode\"\r\n\r\naccurate\r\n")
                append("--$boundary\r\nContent-Disposition: form-data; name=\"include_raw\"\r\n\r\nfalse\r\n")
                if (phoneRegion != null) {
                    append("--$boundary\r\nContent-Disposition: form-data; name=\"phone_region\"\r\n\r\n${phoneRegion.uppercase()}\r\n")
                }
                append("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"card.jpg\"\r\n")
                append("Content-Type: image/jpeg\r\n\r\n")
            }.toByteArray(Charsets.UTF_8)
            val after = "\r\n--$boundary--\r\n".toByteArray(Charsets.UTF_8)
            val url = URL("${baseUrl.trimEnd('/')}/v1/ocr/${type.path}")
            val connection = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                connectTimeout = 10_000
                readTimeout = 90_000
                doOutput = true
                useCaches = false
                instanceFollowRedirects = false
                headers.forEach { (name, value) -> setRequestProperty(name, value) }
                setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
                setFixedLengthStreamingMode(before.size + jpegBytes.size + after.size)
            }
            try {
                connection.outputStream.use { stream ->
                    stream.write(before)
                    stream.write(jpegBytes)
                    stream.write(after)
                }
                val status = connection.responseCode
                val stream = if (status in 200..299) connection.inputStream else connection.errorStream
                val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                val json = runCatching { JSONObject(body) }.getOrNull()
                if (status !in 200..299) {
                    val error = json?.optJSONObject("error")
                    throw CardOCRException(status, error?.optString("code") ?: "HTTP_ERROR",
                        error?.optString("message") ?: "OCR request failed")
                }
                CardOCRResult(json ?: throw CardOCRException(status, "INVALID_JSON", "Invalid OCR response"))
            } finally {
                connection.disconnect()
            }
        }
}

// Add <uses-permission android:name="android.permission.INTERNET" /> to AndroidManifest.xml.
// Add kotlinx-coroutines-android (or reuse the version already in your Android app).
// In viewModelScope.launch:
// val result = CardOCRClient("https://your-app-api.example.com").scan(bytes, CardDocumentType.KTP)
// val nik = result.acceptedString("nik")
// if (result.needsReview) { /* Show result.fields for correction */ }
// Bitmap.compress(JPEG, 92, outputStream) converts camera images to supported bytes.
// This uses bounded blocking I/O on Dispatchers.IO; timeout bounds a cancelled upload's I/O.
// Production: keep the server API key in your authenticated gateway, not the APK.
