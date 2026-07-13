"""ponytail self-check for crm fuzzy matching (pure, no network). Run: python test_fuzzy_match.py

Field names mirror Airtable: separate First Name / Last Name. idx0 and idx1 are a deliberately
close pair (edit distance 2) for the ambiguity case; John is isolated for clean single matches."""
from app.schemas.internal import Customer
from app.services import crm

C = [
    Customer(first_name="Pushkar", last_name="Sharma", phone="(555) 111-0000", claim_status="Approved"),
    Customer(first_name="Priya", last_name="Sharma", phone="5551110002", claim_status="Pending"),
    Customer(first_name="John", last_name="Doe", phone="9998887777", claim_status="Approved"),
]


def test():
    # exact, formatting-insensitive on both sides
    assert crm.match(C, phone="5551110000") == [C[0]]
    assert crm.match(C, phone="555.111.0000") == [C[0]]
    # one digit off, isolated record -> single fuzzy match
    assert crm.match(C, phone="9998887770") == [C[2]]
    # close pair -> a between-number is within distance 2 of both -> ambiguous
    amb = crm.match(C, phone="5551110001")
    assert len(amb) == 2, amb
    # disambiguate the ambiguous pair by name
    assert crm.match(C, phone="5551110001", name="Pushkar Sharma") == [C[0]]
    # far-off number -> no match
    assert crm.match(C, phone="2020200000") == []
    # alternative verification by name only (phone unusable)
    assert crm.match(C, phone="", name="john doe") == [C[2]]
    # STT typo in surname still matches (edit distance 1)
    assert crm.match(C, phone="", name="John Doo") == [C[2]]
    # nothing to match on
    assert crm.match(C) == []
    # levenshtein sanity
    assert crm._lev("kitten", "sitting") == 3
    assert crm._lev("abc", "abc") == 0
    print("OK: all fuzzy-match assertions passed")


if __name__ == "__main__":
    test()
