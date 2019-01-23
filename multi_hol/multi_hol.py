import sys
import re
import os
import keyring
import datetime
from requests import Session
import urllib.parse
import xml.etree.ElementTree as ET
import json
from time import sleep
from easygui import multenterbox
import logging
import getpass

# Get the users input
def get_mmsids(msg=""):
    """Return the MMS-IDs of the bibrecord and the target-holding."""

    if msg == "":
        msg =  "Bitte folgende Daten eingeben."
    else:
        msg = msg

    bib_mms, target_hol_id = multenterbox(msg=msg,
                                           title="Multi-HOL-Bereinigung",
                                           fields=["MMS-ID des Bibsatzes", "MMS-ID des Zielholdings"])
    # check the input
    if (not bib_mms.startswith("99")
            or not bib_mms.endswith("3339")
            or not target_hol_id.startswith("22")):
        msg = """*** Formaler Fehler in der Eingabe ***

    1. Die MMS-ID des Bibsatzes muss mit "99" beginnen
    2. Die MMS-ID des Bibsatzes muss mit "3339" enden
    3. Die MMS-ID des HOL-Satzes muss mit "22" beginnen
"""
        get_mmsids(msg)
    else:
        return bib_mms, target_hol_id

# set up the backup
backup_dir = os.path.join(os.path.expanduser("~"), "Dokumente", "ALMA_multi-hol")
# make the directory if it does not exist
if not os.path.exists(backup_dir):
    os.makedirs(backup_dir)
#configure logging
def logging_setup(bib_mms, target_hol_id):
    # now = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    log_file = os.path.join(backup_dir, f"{bib_mms}_{target_hol_id}.log")
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # add handlers
    log_stream_handler = logging.StreamHandler(sys.stdout)
    log_stream_handler.setLevel(logging.INFO)
    log_stream_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(log_stream_handler)

    log_file_handler = logging.FileHandler(log_file)
    log_file_handler.setLevel(logging.DEBUG)
    log_file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(log_file_handler)

    return logger

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

# function for backing up JSON to disk
def save_json(json_list, filename, count=1):
    """Save JSON-file with a list of items to disk.

    Takes a list of JSON-objects."""

    fname = f"{filename}_{count}.json"
    try:
        with open(fname, "x") as backup:
            backup.write(json.dumps(json_list))
    except FileExistsError:
        save_json(json_list, filename, count + 1)

# functions for checking the api-responses
def get_bch(holding_id):
    hol = session.get(holdings_api + "/" + holding_id, headers = {"accept": "application/xml"})
    try:
        holxml = ET.fromstring(hol.text)
        b = holxml.find('.//*[@tag="852"]/*[@code="b"]').text
        c = holxml.find('.//*[@tag="852"]/*[@code="c"]').text
        h = holxml.find('.//*[@tag="852"]/*[@code="h"]').text
    except:
        logger.exception("Fehler beim Lesen des Zielholdings (XML).")
        print("Ein Fehler ist aufgetreten. Kontrollieren Sie die Log-Datei.")
        input("Drücken Sie ENTER um das Programm zu beenden.")
        sys.exit(1)

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

# Get the items
def get_items(mms_id, target_hol_id):
    mms_id = mms_id
    outlist = []
    hol_bch = get_bch(target_hol_id)

    # get the item-list from Alma
    item_list = session.get(item_api.format(mms_id=mms_id, holding_id="ALL"),
                            params={"limit": "100"})

    # DONE check response
    if item_list.status_code == 200:
        item_list = item_list.json()
    else:
        logger.error(f"Fehler beim Holen der Daten: {item_list.text}")
        input("Drücken Sie ENTER um das Programm zu beenden.")
        sys.exit(1)

    # append the items to the list to be returned, if they pass the tests
    logger.debug("get_items(): Items zur outlist hinzufügen")
    for item in item_list["item"]:
        if check_bch(item, hol_bch):
            outlist.append(item)

    # check if there are more than 100 items
    total_record_count = int(item_list["total_record_count"])
    if total_record_count > 100:
        # calculate number of needed additional calls
        add_calls = total_record_count // 100
        logger.debug(f"get_items(): {total_record_count} items vorhanden, {add_calls} weitere API-calls notwendig.")
        # make the additional calls and add answer to the outlist
        for i in range(add_calls):
            offset = (i + 1) * 100
            logger.debug(f"get_items(): additional call {offset}")

            next_list = session.get(item_api.format(mms_id=mms_id, holding_id="ALL"),
                                    params={"limit": "100", "offset": offset}).json()
            logger.debug(f"get_items(): weitere items zu outlist hinzufügen (call {offset}/{add_calls})")
            for item in next_list["item"]:
                if check_bch(item, hol_bch):
                    outlist.append(item)

    # DONE save the item list to disk
    logger.info("Schreibe Backup.")
    backup_file = os.path.join(backup_dir, f"{mms_id}_{hol_bch[0]}_{hol_bch[1]}_{hol_bch[2].replace('.', '').replace(',', '').replace('/', '').replace(' ', '-')}")
    save_json(outlist, backup_file)
    return outlist

# Change item information like call numbers etc.
def clean_cn(cn):
         """Return call numbers with '/' as delimiter after base call number"""
         # matches correct prefixes only
         match = re.match(r'(^I{1,3}V?,?(?:I{1,3}V?)? [0-9]+)(, ?)(.*$)', cn)
         # matches all prefixes
         # match = re.match(r'(^[IV,]+? [0-9]+)(, ?)(.*$)', cn)
         if match:
             print(match.groups())
             cn = match[1] + "/" + match[3]
         return cn
def change_item_information(item):
    """Make all necessary changes to the item object"""
    # Set the alternative call number
    alt_call_nr = clean_cn(item["item_data"]["alternative_call_number"])
    hol_call_nr = clean_cn(item["holding_data"]["call_number"])
    
    # check if the alternative call number is empty
    if alt_call_nr == "":
        item["item_data"]["alternative_call_number"] = hol_call_nr
        item["item_data"]["alternative_call_number_type"]["value"] = 8
        item["item_data"]["alternative_call_number_type"]["desc"] = "Other scheme"
    elif " ; " in alt_call_nr or hol_call_nr in alt_call_nr:
        pass
    else:
        item["item_data"]["alternative_call_number"] = f"{alt_call_nr} ; {hol_call_nr}"

    # clear the item policy
    item["item_data"]["policy"]["desc"] == None
    item["item_data"]["policy"]["value"] == ''
    return item

# Move the item to the target holding
def move_item(item, bib_mms, target_hol_id):
    """Move items to other holding and delete source-holding"""
    # delete the items, but prevent the target-hol from being deleted
    barcode = item["item_data"]["barcode"]
    title = item["bib_data"]["title"]
    target = item_api.format(mms_id=bib_mms, holding_id=target_hol_id)
    if not target_hol_id in item["link"]:
        logger.debug(f"move_item(): lösche {barcode}")
        delete_item_response = session.delete(item["link"], params={"holdings": "delete"})
    else:
        logger.debug(f"move_item(): lösche {barcode}")
        delete_item_response = session.delete(item["link"], params={"holdings": "retain"})

    if not delete_item_response.status_code == 204:
        logger.error(f"move_item(): löschen fehlgeschlagen bei {barcode}. {delete_item_response.text}")
        return

    # post the item. Wait for 1 second before that, so that Alma can update the
    # barcode index. Try again, if barcode index is not updated.
    sleep(1)
    tries = 0
    logger.debug(f"move_item(): POST von {barcode}")
    post_item_response = session.post(target, json=item).json()
    while "errorsExist" in post_item_response:
        if tries > 5:
            error = post_item_response["errorList"]["error"][0]["errorMessage"]
            # errors.append([bib_mms, barcode, title, error])
            logger.error(f"move_item(): {barcode} Fünfter POST-Versuch fehlgeschlagen, Abbruch.")
            break
        elif post_item_response["errorList"]["error"][0]["errorCode"] == "401873":
            # if the error is an existing barcode, try again
            logger.info(f"move_item(): {barcode}: weiterer POST-Versuch ({tries + 1}x)")
            sleep(1)
            post_item_response = session.post(target, json=item).json()
            tries += 1
        else:
            error = post_item_response["errorList"]["error"][0]["errorMessage"]
            (f"move_item(): unerwarteter Fehler bei POST {error}")
            break

def main():
    # assign values to bib_mms and target_hol_id
    if len(sys.argv) == 3:
        bib_mms = sys.argv[1]
        target_hol_id = sys.argv[2]
    else:
        bib_mms, target_hol_id = get_mmsids()

    global logger
    logger = logging_setup(bib_mms, target_hol_id)

    # log who started the program
    logger.debug(f"Programm gestartet von {getpass.getuser()}.")
    logger.debug(f"bib_mms: {bib_mms}, target_hol_id: {target_hol_id}")

    # do your work
    logger.info("Hole Daten von Alma ...")
    item_list = get_items(bib_mms, target_hol_id)
    item_count = len(item_list)
    logger.info(f"Zu bearbeitende Exemplare: {item_count}")

    for idx, item in enumerate(item_list):
        logger.info(f"Exemplar {idx + 1} von {item_count}: {item['item_data']['barcode']}")
        logger.info("Bearbeite Exemplardaten ...")
        change_item_information(item)

        logger.info("Verschieben an Zielholding ...")
        move_item(item, bib_mms, target_hol_id)

    input("Verarbeitung abgeschlossen!\nDrücken Sie ENTER um das Programm zu verlassen.")

main()
