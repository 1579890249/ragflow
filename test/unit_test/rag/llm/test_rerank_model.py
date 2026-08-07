import pytest

from rag.llm.rerank_model import GPUStackRerank, OpenAI_APIRerank


def test_openai_api_rerank_preserves_base_url_path(monkeypatch):
    requested_urls = []

    class Response:
        @staticmethod
        def json():
            return {
                "results": [
                    {"index": 0, "relevance_score": 0.2},
                    {"index": 1, "relevance_score": 0.8},
                ]
            }

    def post(url, **kwargs):
        requested_urls.append(url)
        return Response()

    monkeypatch.setattr("rag.llm.rerank_model.requests.post", post)

    reranker = OpenAI_APIRerank("api-key", "bge-reranker-large", "http://example.test/v1")
    scores, _ = reranker.similarity("query", ["doc one", "doc two"])

    assert requested_urls == ["http://example.test/v1/rerank"]
    assert scores.tolist() == pytest.approx([0.0, 1.0])


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("http://example.test", "http://example.test/v1/rerank"),
        ("http://example.test/v1", "http://example.test/v1/rerank"),
        ("http://example.test/v1/", "http://example.test/v1/rerank"),
        ("http://example.test/v1/rerank", "http://example.test/v1/rerank"),
    ],
)
def test_gpustack_rerank_normalizes_base_url(base_url, expected_url):
    reranker = GPUStackRerank("api-key", "bge-reranker-v2-m3", base_url)

    assert reranker.base_url == expected_url
