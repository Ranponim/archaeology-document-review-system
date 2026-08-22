from app.api.reference_corpora import _corpus_upload_mime
from app.services.adobe_conversion_client import (
    ADOBE_WINDOWS_AGENT_VERSION,
    ConversionResult,
    SubprocessAdobeConversionClient,
)


def test_browser_generic_binary_mime_is_normalized_only_at_corpus_boundary():
    assert _corpus_upload_mime("application/octet-stream") is None
    assert _corpus_upload_mime("") is None
    assert _corpus_upload_mime("application/x-indesign") == "application/x-indesign"
    assert _corpus_upload_mime("application/postscript") == "application/postscript"


def test_adobe_subprocess_client_and_result_share_windows_agent_version():
    client = SubprocessAdobeConversionClient(command=["fake-adobe-agent"])
    assert ADOBE_WINDOWS_AGENT_VERSION == "adobe-windows-agent-v1"
    assert client.version == ADOBE_WINDOWS_AGENT_VERSION
    assert ConversionResult.__dataclass_fields__["converter_version"].default == ADOBE_WINDOWS_AGENT_VERSION
