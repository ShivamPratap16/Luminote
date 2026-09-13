"""PDF generation service.

Renders structured notes to HTML using Jinja2 templates, then converts
HTML to PDF using Playwright's headless Chromium. PDF generation is
completely independent of the AI provider.
"""
import os
import uuid
import tempfile
import structlog
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader
from app.core.config import settings
from app.schemas.notes import StructuredNotes

logger = structlog.get_logger(__name__)


class PdfGenerationError(Exception):
    """Raised when PDF generation fails."""
    pass


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format."""
    total = int(seconds)
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


class PdfService:
    """Renders structured notes into a PDF file."""

    def __init__(self, template_dir: str | None = None):
        self.template_dir = template_dir or os.path.abspath(settings.PDF_TEMPLATE_DIR)
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=True,
        )
        # Register helper functions in the template environment
        self.env.globals["format_timestamp"] = format_timestamp

    def render_html(
        self,
        notes: StructuredNotes,
        source_url: str | None = None,
    ) -> str:
        """Render structured notes to an HTML string."""
        template = self.env.get_template("notes.html")
        return template.render(
            notes=notes,
            source_url=source_url,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        )

    def generate_pdf(
        self,
        notes: StructuredNotes,
        source_url: str | None = None,
        output_dir: str | None = None,
    ) -> str:
        """Generate a PDF from structured notes.

        1. Render notes to HTML via Jinja2 template
        2. Use Playwright to render HTML to PDF
        3. Validate the output file exists and is non-empty

        Returns the path to the generated PDF file.
        Raises PdfGenerationError on failure.
        """
        html_content = self.render_html(notes, source_url)
        out_dir = output_dir or tempfile.mkdtemp(prefix="lecture_pdf_")
        pdf_path = os.path.join(out_dir, f"notes_{uuid.uuid4().hex[:8]}.pdf")

        logger.info("Generating PDF", output_path=pdf_path)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_content(html_content, wait_until="networkidle")
                page.pdf(
                    path=pdf_path,
                    format="A4",
                    margin={
                        "top": "2cm",
                        "bottom": "2cm",
                        "left": "2cm",
                        "right": "2cm",
                    },
                    print_background=True,
                )
                browser.close()

        except Exception as e:
            logger.error("PDF generation failed", error=str(e))
            raise PdfGenerationError(f"Failed to generate PDF: {e}")

        # Validate output
        if not os.path.exists(pdf_path):
            raise PdfGenerationError("PDF file was not created")
        if os.path.getsize(pdf_path) == 0:
            raise PdfGenerationError("PDF file is empty")

        logger.info(
            "PDF generated successfully",
            path=pdf_path,
            size_bytes=os.path.getsize(pdf_path),
        )
        return pdf_path
