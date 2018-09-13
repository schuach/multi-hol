from sys import argv
import re
import os
import keyring
from requests import Session
import urllib.parse
import xml.etree.ElementTree as ET
import json
from time import sleep
from easygui import multenterbox

# get everything ready for making the API-Calls
# api-url-templates
base_url = 'https://api-eu.hosted.exlibrisgroup.com/almaws/v1'
barcode_api = base_url + "/items?item_barcode={barcode}"
holdings_api = base_url + "/bibs/{mms_id}/holdings"
bib_api = base_url + "/bibs/{mms_id}"
item_api = base_url + "/bibs/{mms_id}/holdings/{holding_id}/items"
# get api key from system keyring
api_key = keyring.get_password("ALMA-API", "BIB-Sandbox").rstrip()
# session um immer gleiche header zu schicken etc.
session = Session()
session.headers.update({
    "accept": "application/json",
    "authorization": f"apikey {api_key}"
})

# functions for checking the api-responses
def check_response_item(response):
    return "ok"
def get_bch(holding_id):
    hol = session.get(holdings_api + "/" + holding_id, headers = {"accept": "application/xml"})
    holxml = ET.fromstring(hol.text)
    b = holxml.find('.//*[@tag="852"]/*[@code="b"]').text
    c = holxml.find('.//*[@tag="852"]/*[@code="c"]').text
    h = holxml.find('.//*[@tag="852"]/*[@code="h"]').text

    return b, c, h
# check if the item fits the target holding's 852 b, c and h

def check_bch(item, hol_bch):
    """Check if the item fits the target holdings library, location and call number.

    Take an item object (dict) and return True or False."""

    hol_b, hol_c, hol_h = hol_bch

    item_b = item["item_data"]["library"]["value"]
    item_c = item["item_data"]["location"]["value"]
    item_h = item["holding_data"]["call_number"]
    item_alt = item["item_data"]["alternative_call_number"]
    item_h_from_alt = re.sub(r"^.* ; ", "", item_alt)

    bch_check = [False, False, False]

    if hol_b == item_b:
        bch_check[0] = True

    if hol_c == item_c:
        bch_check[1] = True

    if item_h.startswith(hol_h):
        bch_check[2] = True
    elif item_h_from_alt.startswith(hol_h):
        # if the item has already been moved to a false holding because the false
        # call number is a substring of the right one
        bch_check[2] = True

    if False in bch_check:
        return False
    else:
        return True

# set up the backup
backup_dir = os.path.join(os.path.expanduser("~"), "Dokumente", "ALMA_multi-hol")
# make the directory if it does not exist
if not os.path.exists(backup_dir):
    os.makedirs(backup_dir)
# function for backing up JSON to disk
def save_json(json_list, filename):
    """Save JSON-file with a list of items to disk.

    Takes a list of JSON-objects."""

    with open(filename, "w") as backup:
        try:
            backup.write(json.dumps(json_list))
        except:
            # TODO log error/display message and quit()
            print("!!! Backup konnte nicht geschrieben werden.\n!!! Verarbeitung wird abgebrochen")
            return 1
backup = "tests/testdata/testitems.json"
with open(backup) as backup:
    items = json.load(backup)
    for item in items:
        post_item_response = session.post(item_api.format(mms_id="9929806060303339", holding_id="22327292200003339"), json=item)

# Get the users input
def get_mmsids():
    """Return the MMS-IDs of the bibrecord and the target-holding."""
    bib_mms, target_hol_id = multenterbox(msg="Bitte folgende Daten eingeben",
                                           title="Multi-HOL-Bereinigung",
                                           fields=["MMS-ID des Bibsatzes", "MMS-ID des Zielholdings"])
    return bib_mms, target_hol_id
bib_mms, target_hol_id = get_mmsids()
# Get the items
def get_items(mms_id):
    mms_id = mms_id
    outlist = []
    hol_bch = get_bch(target_hol_id)

    # get the item-list from Alma
    item_list = session.get(item_api.format(mms_id=mms_id, holding_id="ALL"),
                            params={"limit": "100"})

    # TODO check response
    if check_response_item(item_list) == "ok":
        item_list = item_list.json()

    # append the items to the list to be returned, if they pass the tests
    for item in item_list["item"]:
        if check_bch(item, hol_bch):
            outlist.append(item)

    # check if there are more than 100 items
    total_record_count = int(item_list["total_record_count"])
    if total_record_count > 100:
        # calculate number of needed additional calls
        add_calls = total_record_count // 100

        # make the additional calls and add answer to the outlist
        for i in range(add_calls):
            offset = (i + 1) * 100

            next_list = session.get(item_api.format(mms_id=mms_id, holding_id="ALL"),
                                    params={"limit": "100", "offset": offset}).json()
            for item in next_list["item"]:
                if check_bch(item, hol_bch):
                    outlist.append(item)

    # TODO save the item list to disk
    backup_file = os.path.join(backup_dir, f"{mms_id}_{hol_bch[0]}_{hol_bch[1]}_{hol_bch[2].replace('.', '').replace(',', '').replace('/', '').replace(' ', '-')}.json")
    save_json(outlist, backup_file)
    return outlist


# Change item information like call numbers etc.
def change_item_information(item):
    """Make all necessary changes to the item object"""
    # Set the alternative call number
    alt_call_nr = item["item_data"]["alternative_call_number"]
    hol_call_nr = item["holding_data"]["call_number"]
    
    # check if the alternative call number is empty
    if alt_call_nr == "":
        item["item_data"]["alternative_call_number"] = hol_call_nr
        item["item_data"]["alternative_call_number_type"]["value"] = 8
        item["item_data"]["alternative_call_number_type"]["desc"] = "Other scheme"
    else:
        item["item_data"]["alternative_call_number"] = f"{alt_call_nr} ; {hol_call_nr}"
    

    # clear the item policy
    item["item_data"]["policy"]["desc"] == None
    item["item_data"]["policy"]["value"] == ''
    return item

# Move the item to the target holding
# TODO Still broken!
def move_items(item_list, target_hol_id):
    """Move items to other holding and delete source-holding"""
    for item in item_list:
        # delete the items, but prevent the target-hol from being deleted
        if not target_hol_id in item["link"]:
            delete_item_response = session.delete(item["link"], params={"holdings": "delete"})
        else:
            delete_item_response = session.delete(item["link"], params={"holdings": "retain"})

    # sleep for some seconds to give alma time
    sleep(5)

    for item in item_list:
        post_item_response = session.post(item_api.format(mms_id=bib_mms, holding_id=target_hol_id), json=item)


item_list = get_items(bib_mms)
print(len(item_list))

for item in item_list:
    change_item_information(item)

move_items(item_list, target_hol_id)
