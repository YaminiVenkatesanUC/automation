import os, inspect
import csv
import re
from datetime import datetime

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select


def get_firefox_driver(save_dir, download_filetypes):
    """
    save_dir should be full/absolute (not relative) filepath
    """
    opts = webdriver.FirefoxOptions()
    opts.add_argument("--headless")
    # Profile preferences necessary for download-on-click files
    profile = webdriver.FirefoxProfile()
    profile.set_preference("browser.download.folderList", 2)
    profile.set_preference("browser.download.manager.showWhenStarting", False)
    profile.set_preference("browser.download.dir", save_dir)
    profile.set_preference("browser.helperApps.neverAsk.saveToDisk", 
                           ','.join(download_filetypes))

    this_fpath = os.path.abspath(__file__)
    gecko_fpath = os.path.join(os.path.dirname(this_fpath), 'geckodriver.log')
    driver = webdriver.Firefox(options=opts, firefox_profile=profile,
                               log_path=gecko_fpath)
    return driver


# Functions to download specified datasets from infoshare
def navigate_to_dataset(driver, dataset_ref):
    category, group, dataset = dataset_ref
    category_elem = WebDriverWait(driver, 2).until(
        EC.presence_of_element_located((By.XPATH,
            "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest') "
            f"and contains(text(), '{category}')]"
        )),
        message=f"'{category}' folder not found."
    )
    category_elem.click()
    
    group_elem = WebDriverWait(driver, 2).until(
        EC.presence_of_element_located((By.XPATH,
            "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest') "
            f"and contains(text(), '{group}')]"
        )),
        message=f"'{group}' folder not found."
    )
    group_elem.click()
    
    dataset_elem = WebDriverWait(driver, 2).until(
        EC.presence_of_element_located((By.XPATH,
            "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest')]"
            f"/u[contains(text(), '{dataset}')]"
        )),
        message=f"'{dataset}' link not found."
    )
    dataset_elem.click()
    
    return driver


def make_infoshare_selections(driver, 
                              dataset_ref, title_to_options, 
                              dataset_name, save_dir,
                              show_status_flags):
    """
    Selects infoshare options according to 'title_to_options' dictionary. Then
    downloads the dataset using download_dataset().
    """
    _ = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, 
            'FunctionalArea_SelectVariablesBlock'
        )),
        message="Select-Variable-Blocks not found."
    )
    select_var_boxes = driver.find_elements_by_xpath(
        "//td[@class = 'FunctionalArea_SelectVariablesBlock']"
        "//td[contains(@id, 'headerRow')]"
    )
    
    # Infoshare only allows you to view 50,000 cells at once :(
    # If the combination of options-to-select exceeds that, then it is necessary
    # to chunk the requests and merge the resulting CSVs.
    NUM_CELLS_PER_CHUNK = 50000
    # Convert any options="ALL" into explicit list of options
    title_to_options_explicit = {}
    for box in select_var_boxes:
        title = box.find_element_by_xpath("./h6").text
        options = title_to_options[title]
        if title_to_options[title] == 'ALL':
            select_elem = Select(box.find_element_by_xpath(
                "../../..//select[contains(@id, 'lbVariableOptions')]"
            ))
            title_to_options_explicit[title] = [opt.text for opt in select_elem.options]
        else:
            title_to_options_explicit[title] = title_to_options[title]
    # Determine whether chunking is required. If so, split on 'Time' variable.
    # Splitting on the variable box with the most options might speed up
    # downloading, but make the CSV-merging logic FAR more complicated since the
    # header rows *could* differ between chunks. >:|
    
    len_per_options = [(title, len(options)) for title, options in
                       title_to_options_explicit.items()]
    num_cells = np.prod([opt_len for title, opt_len in len_per_options])
    num_chunks = int(np.ceil(num_cells / NUM_CELLS_PER_CHUNK))
    if num_chunks > 1:
        # To use another variable to split for chunks, change this:
        # max_spot = np.argmax([opt_len for title, opt_len in len_per_options])
        max_spot = [title for title, opt_len in len_per_options].index('Time')
        title_max, opt_len_max = len_per_options[max_spot]
        opt_max_chunk_size = int(np.ceil(opt_len_max / num_chunks))
        
        chunked_title_to_options = [
            {
                title: options if title != title_max
                else options[opt_max_chunk_size*i : opt_max_chunk_size*(i+1)]
                for title, options in title_to_options_explicit.items()
            }
            for i in range(num_chunks) 
        ]
        driver.quit()
        get_chunked_infoshare_dataset(dataset_ref, chunked_title_to_options, 
                                      dataset_name, save_dir, 
                                      show_status_flags)
        return  # exit original stack
        
    for box in select_var_boxes:
        title = box.find_element_by_xpath("./h6").text
        options = title_to_options[title]
        select_elem = Select(box.find_element_by_xpath(
            "../../..//select[contains(@id, 'lbVariableOptions')]"
        ))
        
        if isinstance(options, list):
            for opt in options:
                select_elem.select_by_visible_text(opt)
        elif isinstance(options, str):
            options_dt_check = re.match('USE_LATEST_DATETIME<(.*)>', options)
            if options_dt_check:
                dt_format = options_dt_check.group(1)
                options_dt = [datetime.strptime(o.text, dt_format)
                              for o in select_elem.options if o.text]
                latest_dt_str = datetime.strftime(max(options_dt), dt_format)
                select_elem.select_by_visible_text(latest_dt_str)
            elif options == "ALL":
                for i in range(len(select_elem.options)):
                    select_elem.select_by_index(i)
    
    driver = download_dataset(driver, dataset_name, save_dir, show_status_flags)
    return driver


def download_dataset(driver, dataset_name, save_dir, show_status_flags):
    go = WebDriverWait(driver, 2).until(
        EC.presence_of_element_located((By.ID,
            'ctl00_MainContent_btnGo'
        )),
        message="Can't find the Go button."
    )
    go.click()
    
    try:
        _ = WebDriverWait(driver, 1).until(
            EC.alert_is_present()
        )
        alert = driver.switch_to.alert
        alert.accept()
    except TimeoutException:
        pass  # no Alert about "Large amount of cells"
    
    if show_status_flags:
        edit_table = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID,
                'ctl00_MainContent_dlEditOptions'
            )),
            message="'Edit table' dropdown not found."
        )
        Select(edit_table).select_by_visible_text('Show status flags')
        # Wait until associated text has disappeared
        _ = WebDriverWait(driver, 2).until_not(
            EC.text_to_be_present_in_element(
                (By.CLASS_NAME, 'footnote'), 'Status flags are not displayed'
            ),
            message="Status flags text won't disappear."
        )
    
    # first 'pxtable' is data, second is metadata
    data = driver.find_element_by_xpath("//table[@class = 'pxtable']")
    data_soup = BeautifulSoup(data.get_attribute('outerHTML'), 'html.parser')
    data_df = pd.read_html(str(data_soup))[0]
    data_df.to_csv(os.path.join(save_dir, f"{dataset_name}.csv"), index=False)

    return driver


def get_chunked_infoshare_dataset(dataset_ref, chunked_title_to_options, 
                                  dataset_name, save_dir, 
                                  show_status_flags):
    """
    This function should not be directly called! It is used by
    get_infoshare_dataset() when necessary.
    
    Download dataset according to specified chunks. For each chunk, save the
    corresponding data into a CSV with a unique name. Then merge CSVs and delete
    individual CSVs.
    Note:
    - chunked_title_to_options is a list of 'title_to_options' objects (in an
      appropriate form for get_infoshare_dataset function).
    - chunked_option (str) specifies which option was split for the chunks.
    """
    num_chunks = len(chunked_title_to_options)
    print(f"Downloading in {num_chunks} partial-CSVs and then merging.")
    for i, title_to_options_i in enumerate(chunked_title_to_options):
        get_infoshare_dataset(dataset_ref,
                              title_to_options_i,
                              f"{dataset_name}__temp{i}",
                              save_dir,
                              show_status_flags=show_status_flags)
    
    # Currently only supports chunking on 'Time' variable
    assert chunked_title_to_options[0]['Time'] != chunked_title_to_options[1]['Time']
    # Automatically detect the header rows
    temp_csv_fpaths = [os.path.join(save_dir, f"{dataset_name}__temp{i}.csv") 
                       for i in range(num_chunks)]
                       
    with open(temp_csv_fpaths[0]) as f1, open(temp_csv_fpaths[1]) as f2:
        chunk1 = csv.reader(f1)
        chunk2 = csv.reader(f2)
        for i, (chunk1_line, chunk2_line) in enumerate(zip(chunk1, chunk2)):
            if chunk1_line != chunk2_line:
                num_header_rows = i
                break
    if num_header_rows is None:
        raise NotImplementedError("Two chunk-CSVs were identical.")
    # Combine CSVs into single dataframe
    header_idxs = list(range(num_header_rows))
    merged = pd.concat(
      (pd.read_csv(fpath, header=header_idxs, index_col=0)
       for fpath in temp_csv_fpaths)
    )
    merged = merged.sort_index(ascending=False)
    merged.to_csv(os.path.join(save_dir, f"{dataset_name}.csv"))
    
    for fpath in temp_csv_fpaths:
        os.remove(fpath)
        
    print(dataset_name, "- Finished")


def get_infoshare_dataset(dataset_ref, title_to_options, dataset_name, save_dir,
                          show_status_flags=False):
    """
    Selects infoshare options according to 'title_to_options' dictionary, which
    maps title of variable box (str) to options to select (list[str] OR str).
    
    Acceptable formats for options:
      - list[str] of specific options to select.
      - 'USE_LATEST_DATETIME<***>' (str) for selecting latest Time period, 
        where ** is the date format of the Infoshare options 
        (eg 'USE_LATEST_DATETIME<%YM%m>' would work for '2021M06').
      - 'ALL' will select all available options.
    
    dataset_name should not include file extension; this is added later (.csv)
    """
    print(dataset_name)
    driver = get_firefox_driver(save_dir, ['text/csv'])
    driver.get("http://infoshare.stats.govt.nz/")
    driver = navigate_to_dataset(driver, dataset_ref)
    driver = make_infoshare_selections(driver, 
                                       dataset_ref, title_to_options,
                                       dataset_name, save_dir,
                                       show_status_flags)
    if driver is not None:
        driver.quit()
