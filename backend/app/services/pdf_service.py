"""PDF generation service for packing slips."""

import os
from datetime import datetime

from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML


def generate_packing_slip_pdf(
    packing_slip_number: str,
    project_name: str,
    shipped_by: str,
    shipped_at: datetime,
    opening_items: list[dict],
    loose_items: list[dict],
) -> bytes:
    """
    Generate a packing slip PDF from data.

    Args:
        packing_slip_number: Unique slip number
        project_name: Project description/name
        shipped_by: Person who shipped
        shipped_at: Timestamp of shipment
        opening_items: list of dicts with keys: opening_number, building, floor, location
        loose_items: list of dicts with keys: opening_number, product_code, hardware_category, quantity

    Returns:
        PDF file as bytes
    """
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("packing_slip.html")

    html_content = template.render(
        packing_slip_number=packing_slip_number,
        project_name=project_name,
        shipped_by=shipped_by,
        shipped_at=shipped_at.strftime("%Y-%m-%d %H:%M"),
        opening_items=opening_items,
        loose_items=loose_items,
        total_opening_items=len(opening_items),
        total_loose_items=sum(item["quantity"] for item in loose_items),
    )

    pdf_bytes = HTML(string=html_content).write_pdf()
    return pdf_bytes
