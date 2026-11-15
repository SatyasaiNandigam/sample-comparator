import pymupdf

def extract_doc_as_markdown(pdf_path: str) -> str:
    """
    Extract text content from a PDF document and return it as Markdown.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Extracted document content as a Markdown string.
    """
    markdown_content = []

    with pymupdf.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            markdown_content.append(f"\n<!-- Page {page_number} -->\n")

            # Extract text while preserving reading order
            page_text = page.get_text("text", sort=True)

            markdown_content.append(page_text)

    return "\n".join(markdown_content)


# Example usage
if __name__ == "__main__":
    markdown = extract_doc_as_markdown("sample.docx")
    print(markdown)

    # Optionally save the extracted content
    with open("output.md", "w", encoding="utf-8") as file:
        file.write(markdown)