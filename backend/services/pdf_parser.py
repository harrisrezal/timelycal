import io
import pdfplumber


def parse_pdf(file_bytes: bytes) -> list[str]:
    """
    Extract Caltrain schedule data from a PDF.
    Uses table-aware parsing — each train row becomes one chunk:
      'Train 101 | Northbound | San Francisco: 8:00am | Bayshore: 8:09am | ...'
    Falls back to line-based chunking if no tables are detected.
    """
    chunks = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    chunks.extend(_parse_table(table))
            else:
                text = page.extract_text()
                if text:
                    chunks.extend(_parse_lines(text.strip()))

    return [c for c in chunks if c.strip()]


def _parse_table(table: list[list]) -> list[str]:
    """
    Convert a pdfplumber table into one chunk per train row.
    Assumes first row contains station/column headers.
    """
    if not table or len(table) < 2:
        return []

    headers = [str(h).strip() if h else "" for h in table[0]]
    chunks = []

    for row in table[1:]:
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        cells = [str(c).strip() if c else "" for c in row]

        # Build a readable chunk: "Header: value | Header: value | ..."
        parts = []
        for header, value in zip(headers, cells):
            if value and value != "--" and value != "-":
                label = header if header else "Info"
                parts.append(f"{label}: {value}")

        if parts:
            chunks.append(" | ".join(parts))

    return chunks


def _parse_lines(text: str) -> list[str]:
    """
    Fallback: split text into non-empty lines as chunks.
    Groups lines into blocks of 5 for context.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    chunks = []
    block_size = 5
    for i in range(0, len(lines), block_size):
        block = " | ".join(lines[i:i + block_size])
        chunks.append(block)
    return chunks
