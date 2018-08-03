import pytest
from multi_hol.multi_hol import *
# with alternative call number
with open("tests/testdata/10items_alt.json") as fh:
    items_alt = json.load(fh)["item"]
# without alternative call number
with open("tests/testdata/10items_no_alt.json") as fh:
    items_no_alt = json.load(fh)["item"]

item_alt = items_alt.pop(0)
item_no_alt = items_no_alt.pop(0)

def test_get_item():
    items = get_items("990006489880203339")
    assert len(items) == 106
    barcodes = []
    for item in items:
        barcodes.append(item["item_data"]["barcode"])
    assert len(items) == len(barcodes)
    assert len(set(barcodes)) == len(barcodes)

def test_get_bch():
    assert get_bch("22312549980003339") == ("BDEPO", "DHB40", "II 140137, 219,Ind. 1879")

def test_save_json():
    pass

def test_change_item_info():
    # load items
    # with alternative call number
    with open("tests/testdata/10items_alt.json") as fh:
        items_alt = json.load(fh)["item"]
    # without alternative call number
    with open("tests/testdata/10items_no_alt.json") as fh:
        items_no_alt = json.load(fh)["item"]

    item_alt = items_alt.pop(0)
    item_no_alt = items_no_alt.pop(0)

    assert change_item_information(item_alt)["item_data"]["alternative_call_number"] == "HB20-918 ; I 380584/1971,2"
    assert change_item_information(item_no_alt)["item_data"]["alternative_call_number"] == "I 380010/48"
    assert change_item_information(item_no_alt)["item_data"]["alternative_call_number_type"]["value"] == 8
    assert change_item_information(item_no_alt)["item_data"]["alternative_call_number_type"]["desc"] == "Other scheme"
