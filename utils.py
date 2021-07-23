from selenium import webdriver


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