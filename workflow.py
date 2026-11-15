from group_prompts import split_markdown_pages, extract_group
from LLMClient import call_openai
from doc_extract import extract_doc_as_markdown

def process_document(pdf_path: str) -> str:
    """
    Process a PDF document by extracting its content, splitting it into pages,
    and generating a response using OpenAI's API.

    Args:
        pdf_path: Path to the PDF file.
        response_format: Desired format for the OpenAI response.

    Returns:
        Generated response as a string.
    """
    # Step 1: Extract text from the PDF document
    markdown_content = extract_doc_as_markdown(pdf_path)

    # Step 2: Split the extracted content into pages
    pages = split_markdown_pages(markdown_content)

    # Step 3: call OpenAI for each page and collect responses
    results = extract_group(call_openai, pages, "availability")
    return results


if __name__ == "__main__":
    # Example usage
    pdf_path = "sample.docx"
    result = process_document(pdf_path)
    print(result)