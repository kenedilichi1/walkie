import pytest

from walkie import geo

GOOD = (6.31625, 8.11691)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("6.31625, 8.11691", GOOD),
        ("6.31625 8.11691", GOOD),
        ("6.31625;8.11691", GOOD),
        ("-6.31625,-8.11691", (-6.31625, -8.11691)),
        ("  6.31625,   8.11691  ", GOOD),
        ("https://www.google.com/maps?q=6.31625,8.11691", GOOD),
        (
            "https://www.google.com/maps/place/Riverside/"
            "@6.31625,8.11691,17z/data=!4m1!3s",
            GOOD,
        ),
        ("https://maps.google.com/?ll=6.31625,8.11691", GOOD),
        (
            "https://www.google.com/maps/dir/?api=1"
            "&destination=6.31625%2C8.11691",
            GOOD,
        ),
        ("https://www.openstreetmap.org/#map=17/6.31625/8.11691", GOOD),
        ("geo:6.31625,8.11691", GOOD),
        ("geo:0,0?q=6.31625,8.11691", GOOD),
        ("https://osmand.net/map?lat=6.31625&lon=8.11691&z=15", GOOD),
        ("https://maps.app.goo.gl/AbCdEfGh", None),
        ("Riverside", None),
        ("", None),
        ("   ", None),
        ("91.5, 8.1", None),
        ("6.3, 181.0", None),
        ("0,0", None),
        ("https://www.google.com/maps/place/Riverside", None),
        ("https://www.google.com/maps/place/Trees?query=lagos", None),
        ("https://www.google.com/maps/place/Trees/@4.0,7.2?query=lagos", (4.0, 7.2)),
        # real-world paste noise: invisible chars, unicode commas, degree marks
        ("\u200b6.31625, 8.11691\u200b", GOOD),
        ("\ufeff6.31625, 8.11691", GOOD),
        ("\u20666.31625, 8.11691\u2069", GOOD),
        ("6.31625，8.11691", GOOD),
        ("6.31625،8.11691", GOOD),
        ("6.31625°, 8.11691°", GOOD),
        ("6.31625° N, 8.11691° E", GOOD),
        ("6.31625 S, 8.11691 W", (-6.31625, -8.11691)),
        ("6.31625\u00a0, 8.11691\u202f", GOOD),
    ],
)
def test_parse_place(text, expected):
    assert geo.parse_place(text) == expected


def test_haversine_zero_and_known_distance():
    assert geo.haversine_m(6.0, 8.0, 6.0, 8.0) == 0
    assert 110_000 < geo.haversine_m(6.0, 8.0, 7.0, 8.0) < 112_000
