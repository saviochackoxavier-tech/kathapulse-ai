/* KathaPulse AI — camera capture with client-side EXIF scrubbing.
 *
 * Why this is safe
 * ----------------
 * A JPEG straight from a phone camera carries EXIF: GPS coordinates, a
 * timestamp with sub-second precision, the device serial, sometimes a
 * thumbnail of the surrounding room.  We never upload that file.
 *
 * Instead every captured frame is drawn onto a <canvas> and re-encoded with
 * canvas.toBlob().  A canvas holds *pixels only* — it has nowhere to store
 * EXIF, XMP, IPTC or comment segments — so the new JPEG contains nothing but
 * the image data.  The original File/Blob is dropped (and revoked if it came
 * from a Blob URL), and the object URL is released after encoding.
 *
 * The same path is used for gallery uploads, where phones routinely attach
 * GPS coordinates.  Orientation is baked into the pixels by createImageBitmap
 * (which applies EXIF orientation), so the strip is not rotated after
 * scrubbing.
 */

(function () {
  "use strict";

  const MAX_EDGE = 1600;      // long edge in px — enough for brand text, cheap to upload
  const JPEG_QUALITY = 0.85;  // sweet spot for OCR of printed labels
  const MAX_UPLOAD_BYTES = 6 * 1024 * 1024;

  let stream = null;
  let videoEl = null;
  let canvasEl = null;
  let lastScrubbed = null; // { blob, width, height, bytes, source }

  function fitDimensions(width, height, maxEdge) {
    const longEdge = Math.max(width, height);
    if (longEdge <= maxEdge) return { width, height };
    const scale = maxEdge / longEdge;
    return {
      width: Math.round(width * scale),
      height: Math.round(height * scale),
    };
  }

  /**
   * Draw any drawable source onto a canvas and return a fresh JPEG blob.
   * The returned blob has no metadata segments: it is produced by the
   * canvas encoder, not by copying the input file.
   */
  function encodeFromSource(source, sourceWidth, sourceHeight) {
    const { width, height } = fitDimensions(sourceWidth, sourceHeight, MAX_EDGE);

    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;

    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) throw new Error("Canvas 2D is not available on this device.");
    // White background: a transparent PNG re-encoded to JPEG would otherwise
    // turn black, which destroys OCR contrast.
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(source, 0, 0, width, height);

    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            reject(new Error("Could not encode the photo."));
            return;
          }
          if (blob.size > MAX_UPLOAD_BYTES) {
            reject(new Error("Photo is too large. Move a little closer and retry."));
            return;
          }
          resolve({ blob, width, height });
        },
        "image/jpeg",
        JPEG_QUALITY
      );
    });
  }

  /** Scrub a File from <input type=file> (gallery or camera roll). */
  async function scrubFile(file) {
    if (!file || !file.type || !file.type.startsWith("image/")) {
      throw new Error("Please choose an image file.");
    }

    // createImageBitmap applies EXIF orientation to the pixels for us.
    let bitmap;
    try {
      bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    } catch (err) {
      bitmap = await loadViaImageElement(file);
    }

    try {
      const { blob, width, height } = await encodeFromSource(
        bitmap,
        bitmap.width,
        bitmap.height
      );
      lastScrubbed = {
        blob,
        width,
        height,
        bytes: blob.size,
        source: "file",
        originalBytes: file.size,
      };
      return lastScrubbed;
    } finally {
      if (bitmap && typeof bitmap.close === "function") bitmap.close();
    }
  }

  function loadViaImageElement(file) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("This photo could not be opened."));
      };
      img.src = url;
    });
  }

  /** Grab the current video frame, scrub it through the canvas, return a Blob. */
  async function grabFrame() {
    if (!videoEl || !stream) throw new Error("The camera is not running yet.");
    if (!videoEl.videoWidth) throw new Error("The camera is still starting.");

    const { blob, width, height } = await encodeFromSource(
      videoEl,
      videoEl.videoWidth,
      videoEl.videoHeight
    );
    lastScrubbed = { blob, width, height, bytes: blob.size, source: "camera" };
    return lastScrubbed;
  }

  async function startCamera(video, canvas) {
    videoEl = video;
    canvasEl = canvas;

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("This browser cannot open the camera. Use 'Choose photo'.");
    }

    // Reuse a live stream. Retry must not open a second camera session:
    // Android hands back the first one and the viewfinder goes black.
    if (isRunning()) {
      video.srcObject = stream;
      video.hidden = false;
      await video.play().catch(() => {});
      return stream;
    }

    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 1920 },
        height: { ideal: 1440 },
      },
    });

    video.srcObject = stream;
    video.hidden = false;
    await video.play().catch(() => {});
    return stream;
  }

  function isRunning() {
    return (
      !!stream &&
      stream.getTracks().some((track) => track.readyState === "live")
    );
  }

  function stopCamera() {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
    if (videoEl) {
      videoEl.srcObject = null;
      videoEl.hidden = true;
    }
  }

  /** Show the scrubbed frame as a static preview (proof for the user). */
  function showPreview(canvas, scrubbed) {
    if (!canvas || !scrubbed) return;
    const ctx = canvas.getContext("2d");
    const url = URL.createObjectURL(scrubbed.blob);
    const img = new Image();
    img.onload = () => {
      canvas.width = scrubbed.width;
      canvas.height = scrubbed.height;
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.hidden = false;
    };
    img.src = url;
  }

  window.KathaPulseCapture = {
    startCamera,
    stopCamera,
    isRunning,
    grabFrame,
    scrubFile,
    showPreview,
    getLast: () => lastScrubbed,
    MAX_EDGE,
  };
})();
