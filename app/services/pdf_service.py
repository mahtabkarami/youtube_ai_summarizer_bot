import os
import warnings
import fpdf
from fpdf import FPDF
from arabic_reshaper import reshape
from bidi.algorithm import get_display


def _contains_non_ascii(text: str) -> bool:
    return any(ord(char) > 127 for char in text)


def _clean_markdown(text: str) -> str:
    """Remove Markdown syntax and AI meta-commentary from text before PDF rendering."""
    import re

    # Meta-commentary patterns the AI sometimes adds (Persian)
    meta_patterns = [
        r"^متن شما.*$",
        r"^این جزوه.*$",
        r"^اگر نیاز به توضیح.*$",
        r"^لطفا بفرمایید.*$",
        r"^در صورت نیاز.*$",
        r"^امیدوارم.*$",
        r"^موفق باشید.*$",
    ]

    lines = text.splitlines()
    cleaned_lines = []

    for line in lines:
        # Skip meta-commentary lines
        skip = False
        for pattern in meta_patterns:
            if re.match(pattern, line.strip()):
                skip = True
                break
        if skip:
            continue

        # Remove horizontal rules (--- or ___ or ***)
        if re.match(r"^\s*[-_*]{3,}\s*$", line):
            continue

        # Remove leading # characters from headings (keep the text)
        line = re.sub(r"^#{1,6}\s*", "", line)

        # Remove **bold** and __bold__ markers
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        line = re.sub(r"__(.+?)__", r"\1", line)

        # Remove *italic* and _italic_ markers
        line = re.sub(r"\*(.+?)\*", r"\1", line)
        line = re.sub(r"_(.+?)_", r"\1", line)

        # Normalize bullet points: collapse multiple leading dashes/asterisks to a single "-"
        line = re.sub(r"^\s*[-*]{2,}\s*", "- ", line)
        # Ensure a single leading "- " has proper spacing
        line = re.sub(r"^\s*-\s+", "- ", line)

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def create_pdf(text: str, output_path: str, images: list = None) -> None:
    """
    Create a PDF with text and optional images.
    
    Args:
        text: The text content to include in the PDF
        output_path: Path where the PDF will be saved
        images: Optional list of image paths to include after the text
    """
    os.makedirs(os.path.dirname(output_path) or "data", exist_ok=True)
    pdf = FPDF()
    pdf.add_page()

    use_unicode_font = False
    font_path = "fonts/Vazirmatn-Medium.ttf"
    if os.path.exists(font_path):
        try:
            # Works on both pyfpdf (1.x) and fpdf2 when TTF support is available.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="cmap value too big/small.*",
                    category=UserWarning,
                )
                pdf.add_font("Vazirmatn", "", font_path, uni=True)
            pdf.set_font("Vazirmatn", size=12)
            use_unicode_font = True
        except Exception as exc:
            if _contains_non_ascii(text):
                raise RuntimeError(
                    "Cannot render Unicode text in PDF. "
                    "Verify fonts/Vazirmatn-Medium.ttf and fpdf font support."
                ) from exc
            pdf.set_font("Arial", size=12)
    else:
        if _contains_non_ascii(text):
            raise RuntimeError(
                "Unicode PDF font not found at fonts/Vazirmatn-Medium.ttf."
            )
        pdf.set_font("Arial", size=12)

    # پاک‌سازی Markdown و متن‌های اضافی قبل از رندر
    text = _clean_markdown(text)

    # اصلاح متن برای نمایش صحیح فارسی (RTL)
    reshaped_text = reshape(text)
    bidi_text = get_display(reshaped_text)

    if not use_unicode_font:
        # ASCII-only fallback.
        bidi_text = bidi_text.encode("latin-1", errors="replace").decode("latin-1")

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="cmap value too big/small.*",
            category=UserWarning,
        )
        pdf.multi_cell(0, 10, txt=bidi_text, align="R")
    
    # Add images if provided
    if images and len(images) > 0:
        for img_path in images:
            if os.path.exists(img_path):
                # Add a new page for images
                pdf.add_page()
                
                # Get page width for image sizing
                page_width = pdf.w - 20  # 10mm margin on each side
                
                try:
                    # Try to get image dimensions
                    from PIL import Image
                    with Image.open(img_path) as img:
                        img_width, img_height = img.size
                        
                        # Calculate aspect ratio to fit image on page
                        ratio = img_height / img_width
                        new_width = page_width
                        new_height = page_width * ratio
                        
                        # If image is too tall, scale by height instead
                        max_height = pdf.h - 40  # 20mm margin top/bottom
                        if new_height > max_height:
                            new_height = max_height
                            new_width = new_height / ratio
                        
                        # Center the image horizontally
                        x = (pdf.w - new_width) / 2
                        pdf.image(img_path, x=x, y=20, w=new_width, h=new_height)
                except ImportError:
                    # Fallback if PIL is not available - just use simple sizing
                    pdf.image(img_path, x=10, y=20, w=page_width)
                except Exception as e:
                    # Skip images that fail to load
                    print(f"Warning: Could not add image {img_path}: {e}")
                    continue
    
    pdf.output(output_path)

