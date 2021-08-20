import re
from datetime import datetime

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

    driver = webdriver.Firefox(options=opts, firefox_profile=profile)
    return driver


# Functions to download specified datasets from infoshare
def navigate_to_dataset(driver, dataset_ref):
    category, group, dataset = dataset_ref
    try:
        category_elem = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH,
              "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest') "
              f"and contains(text(), '{category}')]"
            ))
        )
    except TimeoutException:
        raise TimeoutException(f"'{category}' folder not found.")
    category_elem.click()
    
    try:
        group_elem = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest') "
                    f"and contains(text(), '{group}')]"
            ))
        )
    except TimeoutException:
        raise TimeoutException(f"'{group}' folder not found.")
    group_elem.click()
    
    try:
        dataset_elem = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.XPATH,
                "//a[starts-with(@id, 'ctl00_MainContent_tvBrowseNodest')]"
                f"/u[contains(text(), '{dataset}')]"
            ))
        )
    except TimeoutException:
        raise TimeoutException(f"'{dataset}' link not found.")
    dataset_elem.click()
    
    return driver


def make_infoshare_selections(driver, title_to_options, dataset_name, save_dir):
    """
    Selects infoshare options according to 'title_to_options' dictionary. Then
    downloads the dataset using download_dataset().
    """
    select_var_boxes = driver.find_elements_by_xpath(
        "//td[@class = 'FunctionalArea_SelectVariablesBlock']"
        "//td[contains(@id, 'headerRow')]"
    )
    for box in select_var_boxes:
        title = box.find_element_by_xpath("./h6").text
        options = title_to_options[title]
        select_elem = Select(box.find_element_by_xpath(
            "../../..//select[contains(@id, 'lbVariableOptions')]"
        ))
        
        options_dt_check = re.match('USE_LATEST_DATETIME<(.*)>', options[0])
        if options_dt_check:
            dt_format = options_dt_check.group(1)
            options_dt = [datetime.strptime(o.text, dt_format)
                          for o in select_elem.options if o.text]
            latest_dt_str = datetime.strftime(max(options_dt), dt_format)
            select_elem.select_by_visible_text(latest_dt_str)
        else:
            for opt in options:
                select_elem.select_by_visible_text(opt)
    
    driver = download_dataset(driver, dataset_name, save_dir)
    return driver


def download_dataset(driver, dataset_name, save_dir):
    try:
        go = WebDriverWait(driver, 2).until(
            EC.presence_of_element_located((By.ID,
                'ctl00_MainContent_btnGo'
            ))
        )
    except TimeoutException:
        raise TimeoutException("Can't find the Go button.")
    go.click()
    # first 'pxtable' is data, second is metadata
    data = driver.find_element_by_xpath("//table[@class = 'pxtable']")
    data_soup = BeautifulSoup(data.get_attribute('outerHTML'), 'html.parser')
    data_df = pd.read_html(str(data_soup))[0]
    data_df.to_csv(f"{save_dir}/{dataset_name}.csv", index=False)

    return driver


def get_infoshare_dataset(dataset_ref, title_to_options, dataset_name, save_dir):
    """
    To use most recent period for a 'Time' selection, set the corresponding
    value in 'title_to_options' dictionary to a list[str] of length one
    with the (single) element 'USE_LATEST_DATETIME<***>' where *** is the
    datetime format of the infoshare options.
    
    dataset_name should not include file extension; this is added later (.csv)
    """
    print(dataset_name)
    driver = get_firefox_driver(save_dir, ['text/csv'])
    driver.get("http://infoshare.stats.govt.nz/")
    driver = navigate_to_dataset(driver, dataset_ref)
    driver = make_infoshare_selections(driver, title_to_options,
                                       dataset_name, save_dir)
    driver.quit()
