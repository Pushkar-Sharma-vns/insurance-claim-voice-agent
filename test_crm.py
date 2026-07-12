from app.services.crm import _digits


def test_digits_normalizes_formats():
    assert _digits("+1 (415) 555-0100") == "4155550100"
    assert _digits("415.555.0100") == "4155550100"
    assert _digits("4155550100") == "4155550100"
    assert _digits("") == ""


if __name__ == "__main__":
    test_digits_normalizes_formats()
    print("ok")
