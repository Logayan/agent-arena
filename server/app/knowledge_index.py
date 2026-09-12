from __future__ import annotations

import csv
import html
import io
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree


TEXT_SUFFIXES = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".htm",
    ".xml", ".py", ".js", ".ts", ".tsx", ".vue", ".sql", ".toml",
    ".ini", ".log", ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
}
OFFICE_SUFFIXES = {".pdf", ".docx", ".xlsx", ".pptx"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | OFFICE_SUFFIXES


@dataclass(frozen=True)
class ExtractedSection:
    title: str
    locator: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeChunk:
    title: str
    locator: str
    content: str
    token_estimate: int
    metadata: dict[str, Any]


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _clean_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"\r\n?", "\n", value)
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def _extract_text_document(filename: str, suffix: str, content: bytes) -> list[ExtractedSection]:
    text = _decode_text(content)
    if suffix == ".json":
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            pass
    elif suffix == ".csv":
        rows = list(csv.reader(io.StringIO(text)))
        text = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)
    elif suffix in {".html", ".htm", ".xml"}:
        text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "\n", text)
        text = html.unescape(text)
    return [ExtractedSection(filename, "全文", _clean_text(text), {"kind": "text"})]


def _extract_pdf(filename: str, content: bytes) -> list[ExtractedSection]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    sections: list[ExtractedSection] = []
    for page_no, page in enumerate(reader.pages, start=1):
        text = _clean_text(page.extract_text() or "")
        if text:
            sections.append(ExtractedSection(f"第 {page_no} 页", f"page:{page_no}", text, {"page": page_no}))
    return sections


def _extract_docx(filename: str, content: bytes) -> list[ExtractedSection]:
    namespaces = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    }
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    sections: list[ExtractedSection] = []
    current_title = filename
    buffer: list[str] = []

    def flush(locator: str) -> None:
        nonlocal buffer
        text = _clean_text("\n".join(buffer))
        if text:
            sections.append(ExtractedSection(current_title, locator, text, {"kind": "document"}))
        buffer = []

    section_no = 1
    table_no = 0
    body = root.find("w:body", namespaces)
    for element in list(body) if body is not None else []:
        kind = element.tag.rsplit("}", 1)[-1]
        if kind == "p":
            value = "".join(node.text or "" for node in element.findall(".//w:t", namespaces)).strip()
            if not value:
                continue
            style = element.find("w:pPr/w:pStyle", namespaces)
            style_value = style.get(f"{{{namespaces['w']}}}val", "") if style is not None else ""
            if "heading" in style_value.lower() or "标题" in style_value:
                flush(f"section:{section_no}")
                section_no += 1
                current_title = value
            else:
                buffer.append(value)
        elif kind == "tbl":
            table_no += 1
            rows = []
            for row in element.findall(".//w:tr", namespaces):
                cells = [
                    "".join(node.text or "" for node in cell.findall(".//w:t", namespaces)).strip()
                    for cell in row.findall("w:tc", namespaces)
                ]
                rows.append(" | ".join(cells))
            if rows:
                buffer.append(f"\n[表格 {table_no}]\n" + "\n".join(rows))
    flush(f"section:{section_no}")
    return sections


def _extract_xlsx(filename: str, content: bytes) -> list[ExtractedSection]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sections: list[ExtractedSection] = []
    try:
        for sheet in workbook.worksheets:
            rows: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value) for value in row]
                if any(cell.strip() for cell in cells):
                    rows.append(" | ".join(cells))
            text = _clean_text("\n".join(rows))
            if text:
                sections.append(ExtractedSection(sheet.title, f"sheet:{sheet.title}", text, {"sheet": sheet.title}))
    finally:
        workbook.close()
    return sections


def _extract_pptx(filename: str, content: bytes) -> list[ExtractedSection]:
    sections: list[ExtractedSection] = []
    namespace = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        slide_names = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
            key=lambda name: int(re.search(r"slide(\d+)\.xml", name).group(1)),
        )
        for slide_no, slide_name in enumerate(slide_names, start=1):
            root = ElementTree.fromstring(archive.read(slide_name))
            lines = [(node.text or "").strip() for node in root.findall(".//a:t", namespace) if (node.text or "").strip()]
            text = _clean_text("\n".join(lines))
            if text:
                title = lines[0][:100] if lines else f"第 {slide_no} 页"
                sections.append(ExtractedSection(title, f"slide:{slide_no}", text, {"slide": slide_no}))
    return sections


def extract_document(filename: str, content: bytes) -> tuple[str, list[ExtractedSection]]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("knowledge_file_type_not_supported")
    if suffix in TEXT_SUFFIXES:
        parser = "text"
        sections = _extract_text_document(filename, suffix, content)
    elif suffix == ".pdf":
        parser = "pypdf"
        sections = _extract_pdf(filename, content)
    elif suffix == ".docx":
        parser = "docx-openxml"
        sections = _extract_docx(filename, content)
    elif suffix == ".xlsx":
        parser = "openpyxl"
        sections = _extract_xlsx(filename, content)
    elif suffix == ".pptx":
        parser = "pptx-openxml"
        sections = _extract_pptx(filename, content)
    else:
        raise ValueError("knowledge_file_type_not_supported")
    sections = [section for section in sections if section.text.strip()]
    if not sections:
        raise ValueError("knowledge_file_has_no_extractable_text")
    return parser, sections


def _paragraph_windows(text: str, target_size: int, overlap: int) -> Iterable[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", text) if item.strip()]
    if not paragraphs:
        return
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > target_size:
            if current:
                yield current
                current = ""
            step = max(1, target_size - overlap)
            for start in range(0, len(paragraph), step):
                window = paragraph[start:start + target_size].strip()
                if window:
                    yield window
            continue
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= target_size:
            current = candidate
            continue
        if current:
            yield current
            tail = current[-overlap:].strip() if overlap else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
    if current:
        yield current


def chunk_sections(
    sections: list[ExtractedSection],
    target_size: int = 1800,
    overlap: int = 220,
) -> list[KnowledgeChunk]:
    chunks: list[KnowledgeChunk] = []
    for section in sections:
        windows = list(_paragraph_windows(section.text, target_size, overlap))
        for part_no, content in enumerate(windows, start=1):
            chunks.append(
                KnowledgeChunk(
                    title=section.title,
                    locator=f"{section.locator}#chunk:{part_no}",
                    content=content,
                    token_estimate=max(1, math.ceil(len(content) / 4)),
                    metadata={**section.metadata, "part": part_no},
                )
            )
    return chunks


def retrieval_terms(value: str) -> set[str]:
    normalized = value.lower()
    terms = set(re.findall(r"[a-z0-9_][a-z0-9_.-]{1,}", normalized))
    for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
        terms.update(sequence)
        for size in (2, 3):
            terms.update(sequence[index:index + size] for index in range(max(0, len(sequence) - size + 1)))
    return {term for term in terms if term.strip()}


def score_chunks(query: str, chunks: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    query_terms = retrieval_terms(query)
    normalized_query = re.sub(r"\s+", "", query.lower())
    scored: list[dict[str, Any]] = []
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        title = str(chunk.get("title") or "")
        content_terms = retrieval_terms(f"{title}\n{content}")
        overlap = query_terms & content_terms
        if query_terms:
            coverage = len(overlap) / len(query_terms)
            precision = len(overlap) / max(1, math.sqrt(len(content_terms)))
        else:
            coverage = precision = 0.0
        normalized_content = re.sub(r"\s+", "", content.lower())
        phrase_bonus = 0.35 if normalized_query and len(normalized_query) >= 4 and normalized_query in normalized_content else 0.0
        title_terms = retrieval_terms(title)
        title_bonus = min(0.35, len(query_terms & title_terms) * 0.07)
        score = min(1.0, coverage * 0.68 + precision * 0.22 + phrase_bonus + title_bonus)
        if score <= 0:
            continue
        scored.append({**chunk, "score": round(score, 6), "matched_terms": sorted(overlap)[:16]})
    scored.sort(key=lambda item: (float(item["score"]), -int(item.get("chunk_index", 0))), reverse=True)
    return scored[: max(1, min(limit, 20))]
