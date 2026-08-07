import sys
import types

from common.token_utils import num_tokens_from_string
from rag.nlp import naive_merge


class FakeRAGFlowPdfParser:
    @staticmethod
    def remove_tag(txt):
        return txt


fake_pdf_parser = types.ModuleType("deepdoc.parser.pdf_parser")
fake_pdf_parser.RAGFlowPdfParser = FakeRAGFlowPdfParser
sys.modules["deepdoc.parser.pdf_parser"] = fake_pdf_parser


def test_naive_merge_splits_single_oversized_section_by_delimiter():
    section = "Sentence one. Sentence two. Sentence three. Sentence four."

    chunks = naive_merge([(section, "")], chunk_token_num=4, delimiter=".")
    chunks = [chunk for chunk in chunks if chunk.strip()]

    assert len(chunks) > 1
    assert "".join(chunk.lstrip("\n") for chunk in chunks).replace("\n", "") == section
    assert all(num_tokens_from_string(chunk) <= 8 for chunk in chunks)


def test_naive_merge_preserves_position_tag_on_split_oversized_section():
    position = "@@1\t0.0\t100.0\t0.0\t100.0##"
    section = "Sentence one. Sentence two. Sentence three."

    chunks = naive_merge([(section, position)], chunk_token_num=4, delimiter=".")
    chunks = [chunk for chunk in chunks if chunk.strip()]

    assert len(chunks) > 1
    assert all(position in chunk for chunk in chunks)
