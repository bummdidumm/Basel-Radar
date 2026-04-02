from scraper.utils import normalize_text, uniq_list
import pytest

def test_normalize_text_basic():
    assert normalize_text("  Hello   World  ") == "hello world"

def test_normalize_text_case():
    assert normalize_text("PYTHON") == "python"

def test_normalize_text_delimiters():
    assert normalize_text("a|b–c—d-e_f:g;h,i.j/k\\l") == "a b c d e f g h i j k l"

def test_normalize_text_parentheses():
    assert normalize_text("Event (with extra info)") == "event"
    assert normalize_text("Artist (DJ Set) at Venue") == "artist at venue"

def test_normalize_text_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""

def test_normalize_text_multiple_spaces_after_delimiters():
    assert normalize_text("a ||  b") == "a b"
    assert normalize_text("a (remove) b") == "a b"


def test_uniq_list_basic():
    items = ["Apple", "Banana", "apple", "BANANA", "Cherry"]
    expected = ["Apple", "Banana", "Cherry"]
    assert uniq_list(items) == expected

def test_uniq_list_formatting_preservation():
    items = ["  apple  ", "APPLE", "Apple"]
    # The first item is "  apple  ", it should be stripped to "apple" and kept.
    # Subsequent items that normalize to "apple" should be ignored.
    assert uniq_list(items) == ["apple"]

def test_uniq_list_normalization_edge_cases():
    items = ["Artist (DJ Set)", "Artist", "ARTIST"]
    # Both "Artist (DJ Set)" and "Artist" normalize to "artist"
    assert uniq_list(items) == ["Artist (DJ Set)"]

def test_uniq_list_delimiters_and_spaces():
    items = ["Event | Venue", "Event - Venue", "Event: Venue", "event venue"]
    # All these normalize to "event venue"
    assert uniq_list(items) == ["Event | Venue"]

def test_uniq_list_empty_and_whitespace():
    items = ["", "   ", "Valid", ""]
    # Empty and whitespace-only items normalize to "" and are skipped by `if n and n not in seen:`
    assert uniq_list(items) == ["Valid"]

def test_uniq_list_empty_input():
    assert uniq_list([]) == []
