/** Browser/Node fetch client. Pass an image File or Blob; OCR runs on the server. */
export class CardOCRClient {
  constructor(baseUrl, headers = {}) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    // Local testing: {"X-API-Key": "..."}. Production: use your authenticated app gateway.
    this.headers = headers;
  }

  async scan(image, documentType = "auto", { mode = "accurate", phoneRegion, signal } = {}) {
    if (!["ktp", "business_card", "auto"].includes(documentType)) {
      throw new Error("Unknown document type");
    }
    if (!(image instanceof Blob) || image.size === 0 || image.size > 10 * 1024 * 1024) {
      throw new Error("Choose an image between 1 byte and 10 MB");
    }
    const form = new FormData();
    form.append("file", image, "card-upload.jpg");
    form.append("mode", mode);
    form.append("include_raw", "false");
    if (phoneRegion) form.append("phone_region", phoneRegion);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 90000);
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    try {
      const response = await fetch(`${this.baseUrl}/v1/ocr/${documentType}`, {
        method: "POST",
        // Let fetch add the multipart boundary; don't manually set Content-Type.
        headers: this.headers,
        body: form,
        signal: controller.signal,
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        const error = new Error(result.error?.message ?? `OCR failed (${response.status})`);
        error.code = result.error?.code;
        error.status = response.status;
        throw error;
      }
      return result;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
  }
}

// const client = new CardOCRClient("https://your-app-api.example.com");
// const result = await client.scan(fileInput.files[0], "ktp");
// nameInput.value = result.data.full_name ?? "";
// if (result.needs_review) showReviewScreen(result.fields, result.review_reasons);
// Render all OCR text with textContent/value, never innerHTML.
