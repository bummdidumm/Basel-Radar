from scraper.utils import normalize_text, uniq_list

def test_normalize_text_basic():
    assert normalize_text("Hello World") == "hello world"
    assert normalize_text("  trimmed  ") == "trimmed"
    assert normalize_text("UPPER CASE") == "upper case"

def test_normalize_text_spaces():
    assert normalize_text("multiple   spaces") == "multiple spaces"
    assert normalize_text("tabs\tand\nnewlines") == "tabs and newlines"

def test_normalize_text_special_chars():
    # s = re.sub(r"[|–—\-_:;,./\\]+", " ", s)
    assert normalize_text("item1|item2") == "item1 item2"
    assert normalize_text("item1-item2") == "item1 item2"
    assert normalize_text("item1:item2") == "item1 item2"
    assert normalize_text("item1 / item2") == "item1 item2"
    assert normalize_text("complex: separator | test --- multi") == "complex separator test multi"

def test_normalize_text_parentheses():
    # s = re.sub(r"\([^)]*\)", " ", s)
    assert normalize_text("Artist (Remix)") == "artist"
    assert normalize_text("Some (unwanted) Text") == "some text"
    assert normalize_text("Multiple (first) (second) pairs") == "multiple pairs"

def test_normalize_text_none_and_empty():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""
    assert normalize_text("   ") == ""

def test_normalize_text_complex_combination():
    input_str = "  DJ Name (Real Name) - Live @ Club | Genre1 / Genre2  "
    assert normalize_text(input_str) == "dj name live @ club genre1 genre2"

def test_uniq_list():
    items = ["  apple  ", "Apple", "  Banana  ", "apple", "cherry"]
    # Normalizes to: ["apple", "apple", "banana", "apple", "cherry"]
    # Uniq logic: keep original strip() version of first occurrence
    assert uniq_list(items) == ["apple", "Banana", "cherry"]

def test_uniq_list_with_none_and_empty():
    items = ["apple", None, "", "  ", "apple"]
    assert uniq_list(items) == ["apple"]
