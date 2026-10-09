from walkie.sync.qr import qr_blocks


def test_qr_blocks_returns_multiline_text():
    art = qr_blocks("http://192.168.1.10:8000/")
    lines = art.splitlines()
    assert len(lines) > 3
    # half-block characters are what pack two QR rows per line
    assert any(ch in art for ch in "▀▄█")


def test_qr_blocks_same_url_is_deterministic():
    url = "http://10.0.0.2:8000/"
    assert qr_blocks(url) == qr_blocks(url)


def test_qr_blocks_encodes_content():
    # a longer URL needs a denser code than a short one
    short = qr_blocks("http://a/")
    long = qr_blocks("http://192.168.100.42:8000/output/card.html?x=1")
    assert len(long) > len(short)
