"""Preview-kind taxonomy shared by the worker (artifact manifest) and the
preview API (conversion dispatch).

``Artifact.preview_kind`` is persisted by the worker when a run's workspace
diff is registered and is returned by ``GET /api/v1/runs/{id}/artifacts``.
The web app only offers the preview affordance when it is non-null, and the
preview service uses the same classification to pick a converter — so both
sides MUST use :func:`preview_kind_for` instead of re-deriving the kind from
scratch. Never let the manifest and the job disagree about what a file is.

Policy (UI-2026-10-22 §07 API-PREVIEW-01/02, extended for "preview every
deliverable"):

- ``frontend_static`` — HTML documents and text-family files (markdown, logs,
  CSV/TSV, JSON, YAML/TOML/XML, source code, diffs…). HTML is served as-is;
  text is HTML-escaped into a ``<pre>`` page.
- ``image`` — ``image/*`` (png/jpg/gif/webp/bmp/ico/avif/tiff/svg): original
  bytes are streamed, the browser renders them.
- ``pdf`` — rendered server-side to page images inside a sandboxed HTML page.
- ``office`` — docx/xlsx/pptx plus ODF (odt/ods/odp): extracted to HTML
  (paragraphs/tables/slides). Legacy binary Office (.doc/.xls/.ppt) and other
  unreadable containers fall through to ``binary``.
- ``media`` — ``audio/*`` / ``video/*``: original bytes are streamed and the
  browser's native media player renders them inside the preview frame.
- ``archive`` — zip / tar / tar.gz / tgz / gz: a table of archive members.
- ``binary`` — everything else: an honest metadata + hex preview page, so a
  preview surface always exists instead of a dead "unsupported" spinner.

The corresponding web capability matrix lives in
``rxycode_server.api.auth._web_capabilities`` and must stay in sync with
``ALL_KINDS``.
"""

from __future__ import annotations

FRONTEND_STATIC = "frontend_static"
IMAGE = "image"
PDF = "pdf"
OFFICE = "office"
MEDIA = "media"
ARCHIVE = "archive"
BINARY = "binary"

#: Every kind the preview pipeline can produce. Keep the ordering stable: the
#: web capability matrix and tests assert these keys.
ALL_KINDS: tuple[str, ...] = (
    FRONTEND_STATIC,
    IMAGE,
    PDF,
    OFFICE,
    MEDIA,
    ARCHIVE,
    BINARY,
)

_HTML_EXTS = (".html", ".htm", ".xhtml")
_IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".cur",
    ".avif", ".tif", ".tiff", ".svg", ".heic", ".heif",
)
_PDF_EXTS = (".pdf",)
_OFFICE_EXTS = (
    ".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm",
    ".odt", ".ods", ".odp",
)
_AUDIO_EXTS = (
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma",
)
_VIDEO_EXTS = (
    ".mp4", ".m4v", ".webm", ".ogv", ".mov", ".mkv", ".avi", ".wmv", ".mpeg",
    ".mpg",
)
_ARCHIVE_EXTS = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".gz", ".bz2", ".tbz2", ".xz", ".txz",
    ".7z", ".rar",
)
_TEXT_EXTS = (
    # docs / data
    ".md", ".markdown", ".mdx", ".txt", ".log", ".text", ".rst",
    ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".yaml", ".yml", ".toml",
    ".xml", ".ini", ".cfg", ".conf", ".env", ".properties", ".diff", ".patch",
    # code
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue",
    ".svelte", ".css", ".scss", ".less", ".html", ".htm", ".sh", ".bash",
    ".zsh", ".fish", ".ps1", ".bat", ".cmd", ".sql", ".graphql", ".gql",
    ".java", ".kt", ".kts", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".go",
    ".rs", ".rb", ".php", ".lua", ".swift", ".dart", ".scala", ".clj", ".ex",
    ".exs", ".erl", ".hs", ".r", ".jl", ".pl", ".pm", ".m", ".mm", ".asm",
    ".s", ".proto", ".thrift", ".tf", ".hcl", ".dockerfile", ".makefile",
    ".cmake", ".gradle", ".groovy", ".lock", ".gitignore", ".editorconfig",
)

_OFFICE_MIME_PREFIXES = (
    "application/vnd.openxmlformats-officedocument.",
    "application/vnd.oasis.opendocument.",
)
_OFFICE_MIMES = {
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    "application/rtf",
}
_ARCHIVE_MIMES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-tar",
    "application/gzip",
    "application/x-gzip",
    "application/x-bzip2",
    "application/x-xz",
    "application/x-7z-compressed",
    "application/vnd.rar",
    "application/x-rar-compressed",
}
_TEXT_MIMES_PREFIXES = ("text/",)
_TEXT_MIMES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-yaml",
    "application/yaml",
    "application/toml",
    "application/x-sh",
    "application/x-httpd-php",
    "application/sql",
    "application/x-python-code",
}
_BINARY_NAME_EXTS = (".doc", ".xls", ".ppt", ".bin", ".exe", ".dll", ".so", ".dylib", ".o", ".a", ".jar", ".war", ".class", ".pyc", ".pkl", ".npy", ".npz", ".mat", ".db", ".sqlite", ".parquet", ".pb", ".onnx", ".gguf", ".iso", ".img", ".dmg", ".msi", ".deb", ".rpm", ".apk", ".ipa")


def _lower_name(filename: str | None) -> str:
    return (filename or "").strip().lower()


def _ext(name: str) -> str:
    """Best-effort suffix including compound forms like ``.tar.gz``."""
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    return "." + name.rsplit(".", 1)[-1] if "." in name.rsplit("/", 1)[-1] else ""


def preview_kind_for(filename: str | None, content_type: str | None) -> str:
    """Classify one deliverable into a preview kind.

    Content type wins when it is specific (``image/png``, ``text/html`` …);
    the filename suffix is the fallback for ``application/octet-stream``
    registrations where the worker's ``mimetypes`` guess was empty.
    """
    ctype = (content_type or "").split(";")[0].strip().lower()
    name = _lower_name(filename)
    ext = _ext(name)

    # HTML first: text/html must never fall into the generic text branch.
    if ctype in {"text/html", "application/xhtml+xml"} or ext in _HTML_EXTS:
        return FRONTEND_STATIC
    if ctype.startswith("image/"):
        return IMAGE
    if ctype == "application/pdf" or ext in _PDF_EXTS:
        return PDF
    if ctype.startswith(("audio/", "video/")):
        return MEDIA
    if ctype.startswith(_OFFICE_MIME_PREFIXES) or ctype in _OFFICE_MIMES:
        return OFFICE
    if ctype in _ARCHIVE_MIMES:
        return ARCHIVE
    if ctype.startswith(_TEXT_MIMES_PREFIXES) or ctype in _TEXT_MIMES:
        return FRONTEND_STATIC

    if ext in _IMAGE_EXTS:
        return IMAGE
    if ext in _AUDIO_EXTS or ext in _VIDEO_EXTS:
        return MEDIA
    if ext in _OFFICE_EXTS:
        return OFFICE
    if ext in _ARCHIVE_EXTS:
        return ARCHIVE
    if ext in _TEXT_EXTS:
        return FRONTEND_STATIC
    # Legacy Office and other container/binary formats: honest metadata page.
    return BINARY
